"""Operational-script tests; no test in this module may use the network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import generate_demo, generate_snapshot, run_pilot
from src.provider_client import DeterministicFixtureProvider
from src.schemas import (
    AnnotationEvent,
    ConversationRecord,
    ObservationStatus,
    ProviderResult,
)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_demo_generator_is_complete_offline_and_byte_deterministic(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = generate_demo.generate_demo(first_root)
    second = generate_demo.generate_demo(second_root)

    assert first == second
    assert first["display_label"] == generate_demo.DEMO_BANNER
    assert first["network_called"] is False
    assert first["conversation_count"] == 4
    assert first["response_count"] == 24
    assert first["annotation_count"] == 24
    assert _tree_digest(first_root) == _tree_digest(second_root)

    records = [
        ConversationRecord.model_validate(value)
        for value in json.loads((first_root / "conversations.json").read_text(encoding="utf-8"))
    ]
    assert len(records) == 4
    for record in records:
        assert record.header.data_status == "demo_fixture"
        assert record.header.provider == "deterministic_fixture"
        assert len(record.turns) == 6
        assert [turn.turn_number for turn in record.turns] == list(range(1, 7))
        for turn in record.turns:
            assert turn.result.latency_ms == 0
            assert turn.result.provider_name == "deterministic_fixture"

    event_lines = (first_root / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
    events = [AnnotationEvent.model_validate_json(line) for line in event_lines]
    assert len(events) == 24
    assert all(event.scores.complete() for event in events)
    assert all("total" not in event.scores.model_dump() for event in events)
    assert all(generate_demo.DEMO_BANNER in event.notes for event in events)


def test_pilot_plan_is_stable_bounded_and_never_calls_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NetworkForbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("OpenRouter must not be constructed in dry-run mode")

    monkeypatch.setattr(run_pilot, "OpenRouterProvider", NetworkForbidden)
    plan_path = tmp_path / "plan.json"
    first = run_pilot.build_pilot_plan(destination=plan_path)
    second = run_pilot.build_pilot_plan(destination=plan_path)

    assert first == second
    assert first["network_called"] is False
    assert first["pilot_version"] == "technical-pilot-v3.0.0"
    assert first["conversation_count"] == 6
    assert first["planned_successful_response_slots"] == 36
    assert first["bounded_failure_attempts"] == 12
    assert first["maximum_generation_calls"] == 48
    assert first["maximum_http_generation_attempts_including_retries"] == 48
    assert first["minimum_live_request_start_interval_seconds"] == 5.0
    assert len({run["run_id"] for run in first["runs"]}) == 6
    assert all(run["run_id"].startswith("technical-pilot-v3_") for run in first["runs"])
    assert all(
        "technical-pilot-v1" not in run["run_id"]
        and "technical-pilot-v2" not in run["run_id"]
        for run in first["runs"]
    )
    assert {run["model_slot"] for run in first["runs"]} == {
        "model_a",
        "model_b",
        "model_c",
    }
    assert {run["context_condition"] for run in first["runs"]} == {
        "no_preloaded_context",
        "standardised_preloaded_context",
    }
    assert sum(len(run["payloads"]) for run in first["runs"]) == 36
    assert all(
        payload["network_called"] is False for run in first["runs"] for payload in run["payloads"]
    )
    assert run_pilot.main([]) == 0

    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="different content"):
        run_pilot.build_pilot_plan(destination=plan_path)


def test_live_pilot_requires_environment_gate_and_key() -> None:
    with pytest.raises(run_pilot.PilotPreflightError, match="explicit --live"):
        run_pilot.execute_live_pilot(environ={})
    with pytest.raises(run_pilot.PilotPreflightError, match="final --confirm-live"):
        run_pilot.execute_live_pilot(live_requested=True, environ={})
    with pytest.raises(run_pilot.PilotPreflightError, match="RUN_LIVE_PILOT=1"):
        run_pilot.require_live_gate({})
    with pytest.raises(run_pilot.PilotPreflightError, match="API_KEY"):
        run_pilot.require_live_gate({"RUN_LIVE_PILOT": "1"})
    assert (
        run_pilot.require_live_gate({"RUN_LIVE_PILOT": "1", "OPENROUTER_API_KEY": "test-secret"})
        == "test-secret"
    )


def test_live_execution_uses_catalogue_preflight_cap_and_resume_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances = []

    class FakeProvider(DeterministicFixtureProvider):
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "not-a-real-key"
            super().__init__(profile="safe")
            self.catalogue_checks: list[str] = []
            instances.append(self)

        def validate_exact_model(self, model_id: str, timeout_seconds: float = 20) -> None:
            assert timeout_seconds <= 20
            self.catalogue_checks.append(model_id)

        def validate_exact_models(
            self, model_ids: tuple[str, ...], timeout_seconds: float = 20
        ) -> None:
            assert timeout_seconds <= 20
            self.catalogue_checks.extend(model_ids)

    gate = {
        "RUN_LIVE_PILOT": "1",
        "OPENROUTER_API_KEY": "not-a-real-key",
    }
    first = run_pilot.execute_live_pilot(
        output_root=tmp_path / "pilot",
        live_requested=True,
        live_confirmed=True,
        environ=gate,
        provider_factory=FakeProvider,
    )
    assert len(first) == 6
    assert all(len(record.turns) == 6 for record in first)
    assert len(instances[0].calls) == 36
    run_ids = [record.header.run_id for record in first]
    assert run_pilot._stored_generation_attempts(
        run_pilot.RawRunStore(tmp_path / "pilot"), run_ids
    ) == 36
    assert instances[0].catalogue_checks == [
        "google/gemma-4-31b-it:free",
        "minimax/minimax-m3:free",
        "z-ai/glm-5.2:free",
    ]

    second = run_pilot.execute_live_pilot(
        output_root=tmp_path / "pilot",
        live_requested=True,
        live_confirmed=True,
        environ=gate,
        provider_factory=FakeProvider,
    )
    assert len(second) == 6
    assert len(instances[1].calls) == 0
    assert instances[1].catalogue_checks == instances[0].catalogue_checks

    summary = run_pilot.build_live_summary(first, tmp_path / "pilot")
    assert summary["pilot_version"] == "technical-pilot-v3.0.0"
    assert summary["completed_conversations"] == 6
    assert summary["planned_conversations"] == 6
    assert summary["successful_responses"] == 36
    assert summary["technical_errors"] == 0
    assert summary["http_error_types"] == {}
    assert summary["remaining_attempt_allowance"] == 12
    assert summary["required_responses_remaining"] == 0
    assert summary["remaining_allowance_sufficient"] is True
    assert len(summary["cells"]) == 6


def test_live_summary_reports_http_errors_and_remaining_cap_without_network(
    tmp_path: Path,
) -> None:
    class HttpErrorProvider(DeterministicFixtureProvider):
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "not-a-real-key"
            super().__init__()

        def validate_exact_models(
            self, model_ids: tuple[str, ...], timeout_seconds: float = 20
        ) -> None:
            del model_ids, timeout_seconds

        def generate(self, *, model_id, messages, generation):  # noqa: ANN001, ANN202
            del messages, generation
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=model_id,
                provider_name="openrouter",
                latency_ms=0,
                retry_count=2,
                http_status=503,
                error_type="http_503",
                error_message="upstream unavailable",
            )

    output_root = tmp_path / "pilot"
    records = run_pilot.execute_live_pilot(
        output_root=output_root,
        live_requested=True,
        live_confirmed=True,
        environ={
            "RUN_LIVE_PILOT": "1",
            "OPENROUTER_API_KEY": "not-a-real-key",
        },
        provider_factory=HttpErrorProvider,
    )
    summary = run_pilot.build_live_summary(records, output_root)
    assert summary["completed_conversations"] == 0
    assert summary["successful_responses"] == 0
    assert summary["technical_errors"] == 6
    assert summary["http_error_types"] == {"http_503": 6}
    assert summary["remaining_attempt_allowance"] == 30
    assert summary["required_responses_remaining"] == 36
    assert summary["remaining_allowance_sufficient"] is False
    assert all(cell["status"] == "failed" for cell in summary["cells"])


def test_later_invocation_resumes_append_only_in_v3_namespace(
    tmp_path: Path,
) -> None:
    policies: list[tuple[bool, float]] = []

    class FirstInvocationProvider(DeterministicFixtureProvider):
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "not-a-real-key"
            super().__init__()
            self.retry_429 = True
            self.interval = 0.0

        def set_retry_rate_limits(self, enabled: bool) -> None:
            self.retry_429 = enabled

        def set_minimum_request_interval(self, seconds: float) -> None:
            self.interval = seconds

        def validate_exact_models(
            self, model_ids: tuple[str, ...], timeout_seconds: float = 20
        ) -> None:
            del model_ids, timeout_seconds
            policies.append((self.retry_429, self.interval))

        def generate(self, *, model_id, messages, generation):  # noqa: ANN001, ANN202
            del messages, generation
            return ProviderResult(
                status=ObservationStatus.RATE_LIMITED,
                requested_model_id=model_id,
                provider_name="openrouter",
                latency_ms=0,
                retry_count=0,
                http_status=429,
                error_type="http_429",
                error_message="rate limited",
            )

    class ResumeProvider(FirstInvocationProvider):
        def generate(self, *, model_id, messages, generation):  # noqa: ANN001, ANN202
            return DeterministicFixtureProvider.generate(
                self, model_id=model_id, messages=messages, generation=generation
            )

    gate = {
        "RUN_LIVE_PILOT": "1",
        "OPENROUTER_API_KEY": "not-a-real-key",
    }
    output_root = tmp_path / "pilot"
    first = run_pilot.execute_live_pilot(
        output_root=output_root,
        live_requested=True,
        live_confirmed=True,
        environ=gate,
        provider_factory=FirstInvocationProvider,
    )
    error_paths = sorted(output_root.rglob("turn-01-error-01.json"))
    original_errors = {path: path.read_bytes() for path in error_paths}

    assert len(first) == 6
    assert len(error_paths) == 6
    assert all(path.parent.name.startswith("technical-pilot-v3_") for path in error_paths)
    assert not list(output_root.glob("technical-pilot-v1*"))
    assert not list(output_root.glob("technical-pilot-v2*"))

    resumed = run_pilot.execute_live_pilot(
        output_root=output_root,
        live_requested=True,
        live_confirmed=True,
        environ=gate,
        provider_factory=ResumeProvider,
    )

    assert all(len(record.turns) == 6 for record in resumed)
    assert all(path.read_bytes() == original_errors[path] for path in error_paths)
    assert all(len(record.errors) == 1 for record in resumed)
    assert policies == [(False, 5.0), (False, 5.0)]
    summary = run_pilot.build_live_summary(resumed, output_root)
    assert summary["attempts_used"] == 42
    assert summary["remaining_attempt_allowance"] == 6
    assert summary["remaining_allowance_sufficient"] is True


def test_v3_rejects_request_pacing_below_five_seconds() -> None:
    with pytest.raises(run_pilot.PilotPreflightError, match="at least five seconds"):
        run_pilot.execute_live_pilot(
            live_requested=True,
            live_confirmed=True,
            environ={
                "RUN_LIVE_PILOT": "1",
                "OPENROUTER_API_KEY": "not-a-real-key",
            },
            request_interval_seconds=4.99,
        )


def test_failed_exact_model_preflight_is_stored_as_technical_failure(
    tmp_path: Path,
) -> None:
    class MissingModelProvider(DeterministicFixtureProvider):
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "not-a-real-key"
            super().__init__()

        def validate_exact_models(
            self, model_ids: tuple[str, ...], timeout_seconds: float = 20
        ) -> None:
            del model_ids, timeout_seconds
            raise RuntimeError("configured exact model is unavailable")

    output_root = tmp_path / "pilot"
    with pytest.raises(run_pilot.PilotPreflightError, match="technical failure record"):
        run_pilot.execute_live_pilot(
            output_root=output_root,
            live_requested=True,
            live_confirmed=True,
            environ={
                "RUN_LIVE_PILOT": "1",
                "OPENROUTER_API_KEY": "not-a-real-key",
            },
            provider_factory=MissingModelProvider,
        )
    failure_paths = list(output_root.rglob("*.json"))
    assert len(failure_paths) == 1
    failure = json.loads(failure_paths[0].read_text(encoding="utf-8"))
    assert failure["status"] == "technical_failure"
    assert failure["generation_requests_made"] == 0
    assert "not-a-real-key" not in failure_paths[0].read_text(encoding="utf-8")


def test_static_snapshot_is_generated_only_from_demo_outputs(tmp_path: Path) -> None:
    demo_root = tmp_path / "demo"
    generate_demo.generate_demo(demo_root)
    first = generate_snapshot.generate_snapshot(demo_root, tmp_path / "snapshot-first.html")
    second = generate_snapshot.generate_snapshot(demo_root, tmp_path / "snapshot-second.html")

    assert first.read_bytes() == second.read_bytes()
    content = first.read_text(encoding="utf-8")
    assert generate_demo.DEMO_BANNER in content
    assert "24" in content
    assert "Network called:</strong> false" in content
    assert "No combined seven-axis score" in content
