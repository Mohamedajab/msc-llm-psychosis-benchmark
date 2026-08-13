"""Operational-script tests; no test in this module may use the network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import generate_demo, generate_snapshot, run_pilot
from src.provider_client import DeterministicFixtureProvider
from src.schemas import AnnotationEvent, ConversationRecord


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _set_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_MODEL_A", "example/model-a:free")
    monkeypatch.setenv("OPENROUTER_MODEL_B", "example/model-b:free")


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
    _set_models(monkeypatch)

    class NetworkForbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("OpenRouter must not be constructed in dry-run mode")

    monkeypatch.setattr(run_pilot, "OpenRouterProvider", NetworkForbidden)
    plan_path = tmp_path / "plan.json"
    first = run_pilot.build_pilot_plan(destination=plan_path)
    second = run_pilot.build_pilot_plan(destination=plan_path)

    assert first == second
    assert first["network_called"] is False
    assert first["conversation_count"] == 4
    assert first["maximum_generation_calls"] == 24
    assert first["maximum_http_generation_attempts_including_retries"] == 24
    assert len({run["run_id"] for run in first["runs"]}) == 4
    assert {run["model_slot"] for run in first["runs"]} == {
        "model_a",
        "model_b",
    }
    assert {run["context_condition"] for run in first["runs"]} == {
        "no_preloaded_context",
        "standardised_preloaded_context",
    }
    assert sum(len(run["payloads"]) for run in first["runs"]) == 24
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
    _set_models(monkeypatch)
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

    gate = {
        "RUN_LIVE_PILOT": "1",
        "OPENROUTER_API_KEY": "not-a-real-key",
    }
    first = run_pilot.execute_live_pilot(
        output_root=tmp_path / "pilot",
        live_requested=True,
        environ=gate,
        provider_factory=FakeProvider,
    )
    assert len(first) == 4
    assert all(len(record.turns) == 6 for record in first)
    assert len(instances[0].calls) == 24
    assert instances[0].catalogue_checks == [
        "example/model-a:free",
        "example/model-b:free",
    ]

    second = run_pilot.execute_live_pilot(
        output_root=tmp_path / "pilot",
        live_requested=True,
        environ=gate,
        provider_factory=FakeProvider,
    )
    assert len(second) == 4
    assert len(instances[1].calls) == 0
    assert instances[1].catalogue_checks == instances[0].catalogue_checks


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
