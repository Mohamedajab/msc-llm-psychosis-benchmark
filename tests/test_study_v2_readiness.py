"""Focused offline safety tests for Pilot V4 and Study V2 readiness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts import analyse_study, run_pilot_v4, run_pilot_v5, run_study
from scripts.check_documentation_links import broken_links
from scripts.check_repository_safety import audit_tracked_files
from scripts.protocol_bundle import verify_historical_bundle
from src.config_loader import load_histories, load_models, load_scripts
from src.provider_client import (
    DeterministicFixtureProvider,
    OpenRouterProvider,
    qualify_catalogue_entry,
)
from src.schemas import ObservationStatus, ProviderResult
from src.storage import RawRunStore
from src.study_audit import StudyEvidenceError, audit_study_evidence
from src.study_execution import execute_manifest_rows, stored_http_attempts

ROOT = Path(__file__).parents[1]


def _entry(model_id: str, **updates):  # noqa: ANN003, ANN202
    value = {
        "id": model_id,
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["seed", "temperature", "max_tokens"],
        "context_length": 262_144,
    }
    value.update(updates)
    return value


def test_pilot_v4_offline_shape_namespace_and_zero_network(monkeypatch) -> None:
    class NetworkForbidden:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("network provider constructed in offline mode")

    monkeypatch.setattr(run_pilot_v4, "OpenRouterProvider", NetworkForbidden)
    plan = run_pilot_v4.build_offline_plan()
    assert plan["network_called"] is False
    assert plan["planned_conversations"] == 4
    assert plan["planned_response_slots"] == 24
    assert plan["maximum_http_attempts"] == 32
    assert all(run["run_id"].startswith("technical-pilot-v4_") for run in plan["runs"])
    assert not any("technical-pilot-v3_" in run["run_id"] for run in plan["runs"])
    assert plan["pilot_version"] == "technical-pilot-v4.0.0"


def test_pilot_v5_offline_shape_namespace_generation_and_zero_network(monkeypatch) -> None:
    class NetworkForbidden:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("network provider constructed in offline mode")

    monkeypatch.setattr(run_pilot_v5, "OpenRouterProvider", NetworkForbidden)
    plan = run_pilot_v5.build_offline_plan()
    assert plan["network_called"] is False
    assert plan["pilot_version"] == "technical-pilot-v5.0.0"
    assert plan["generation_version"] == "generation-v3"
    assert plan["max_tokens"] == 1024
    assert plan["planned_conversations"] == 4
    assert plan["planned_response_slots"] == 24
    assert plan["maximum_http_attempts"] == 32
    assert all(run["run_id"].startswith("technical-pilot-v5_") for run in plan["runs"])
    assert not any("technical-pilot-v4_" in run["run_id"] for run in plan["runs"])


def test_all_live_gates_fail_closed() -> None:
    with pytest.raises(run_pilot_v4.PilotV4PreflightError):
        run_pilot_v4.execute_live_pilot_v4()
    with pytest.raises(run_pilot_v4.PilotV4PreflightError):
        run_pilot_v4.require_live_gate({})
    with pytest.raises(run_pilot_v5.PilotV5PreflightError):
        run_pilot_v5.execute_live_pilot_v5()
    with pytest.raises(run_pilot_v5.PilotV5PreflightError):
        run_pilot_v5.require_live_gate({})
    with pytest.raises(run_study.StudyPreflightError):
        run_study.require_live_gate(
            live_requested=True,
            live_confirmed=True,
            protocol_confirmed=False,
            environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "fake"},
        )


@pytest.mark.parametrize(
    ("live_requested", "live_confirmed", "environ"),
    [
        (False, False, {}),
        (True, False, {"RUN_LIVE_PILOT": "1", "OPENROUTER_API_KEY": "test"}),
        (True, True, {}),
        (True, True, {"RUN_LIVE_PILOT": "1"}),
    ],
)
def test_every_pilot_v5_live_gate_is_required(
    live_requested: bool,
    live_confirmed: bool,
    environ: dict[str, str],
) -> None:
    with pytest.raises(run_pilot_v5.PilotV5PreflightError):
        run_pilot_v5.execute_live_pilot_v5(
            live_requested=live_requested,
            live_confirmed=live_confirmed,
            environ=environ,
        )


@pytest.mark.parametrize(
    "entry",
    [
        _entry("different/model:free"),
        _entry("openrouter/auto"),
        _entry("model/test:free", pricing={"prompt": "0.1", "completion": "0"}),
        _entry(
            "model/test:free",
            architecture={"input_modalities": ["image"], "output_modalities": ["text"]},
        ),
        _entry("model/test:free", supported_parameters=["temperature"]),
        _entry("model/test:free", context_length=4096),
    ],
)
def test_strict_catalogue_qualification_rejects_invalid_endpoint(entry) -> None:  # noqa: ANN001
    with pytest.raises(RuntimeError):
        qualify_catalogue_entry("model/test:free", entry, minimum_context_tokens=16_384)


def test_routing_policy_and_truncation_are_recorded_without_reasoning() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "model/test:free",
                "provider": "Example",
                "choices": [{"message": {"content": "Observed text."}, "finish_reason": "length"}],
            },
        )

    models = load_models(ROOT / "config" / "models.yaml")
    provider = OpenRouterProvider(
        api_key="fake-secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    provider.set_provider_routing(models.provider_routing)
    result = provider.generate(
        model_id="model/test:free",
        messages=[],
        generation=models.generation.model_copy(
            update={"completion_limit_parameter": "max_tokens"}
        ),
    )
    assert captured["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    assert "models" not in captured
    assert result.status == ObservationStatus.RESPONSE
    assert result.truncated is True
    assert result.http_attempts == 1


class _BudgetedFixture(DeterministicFixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_attempt_count = 0
        self.maximum = 0

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        if self.request_attempt_count >= self.maximum:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=kwargs["model_id"],
                latency_ms=0,
                retry_count=0,
                http_attempts=0,
                error_type="request_budget_exhausted",
            )
        self.request_attempt_count += 1
        return super().generate(**kwargs).model_copy(update={"http_attempts": 1})


def test_manifest_execution_batches_and_resumes_append_only(tmp_path: Path) -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    rows = run_study.generate_manifest(scripts, models)[:2]
    store = RawRunStore(tmp_path / "study-v2")
    first_provider = _BudgetedFixture()
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=first_provider,
        store=store,
        data_status="main_study",
        maximum_http_attempts=3,
        max_new_conversations=1,
    )
    first_paths = {path: path.read_bytes() for path in store.root.rglob("*-success.json")}
    assert len(first_paths) == 3
    assert stored_http_attempts(store, [row.run_id for row in rows]) == 3
    second_provider = _BudgetedFixture()
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=second_provider,
        store=store,
        data_status="main_study",
        maximum_http_attempts=3,
        max_new_conversations=1,
    )
    assert all(path.read_bytes() == value for path, value in first_paths.items())
    assert len(store.successful_turns(rows[0].run_id)) == 6


def test_analysis_is_honestly_unavailable_without_real_ratings(tmp_path: Path) -> None:
    report = analyse_study.build_analysis(
        annotations_path=tmp_path / "missing.jsonl",
        map_path=tmp_path / "missing-map.json",
        output_directory=tmp_path / "out",
    )
    assert report["availability"] == "unavailable"
    assert not (tmp_path / "out").exists()


def test_main_study_default_preflight_is_zero_network_and_bundle_verified(
    monkeypatch,
) -> None:
    class NetworkForbidden:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("network provider constructed in offline mode")

    monkeypatch.setattr(run_study, "OpenRouterProvider", NetworkForbidden)
    report = run_study.build_offline_preflight()
    assert report["network_called"] is False
    assert report["planned_conversations"] == 72
    assert report["planned_response_slots"] == 432
    assert report["configuration_version"] == "2.2.0"
    assert report["generation_version"] == "generation-v4"
    assert report["historical_configuration_version"] == "2.1.0"
    assert report["historical_generation_version"] == "generation-v3"
    assert report["replacement_endpoint_status"] == "NOT_SELECTED"
    assert report["pilot_v6_status"] == "PASS"
    assert report["final_pair_status"] == "QUALIFIED"
    assert report["final_pair_source"] == "ORIGINAL_PAIR_V6"
    assert report["replacement_required"] is False
    assert report["main_study_status"] == "BLOCKED"
    assert verify_historical_bundle()["study_version"] == "study-v2.0.0"


def test_repository_safety_and_documentation_links() -> None:
    assert audit_tracked_files() == []
    assert broken_links() == []


def test_study_audit_rejects_pilot_mixing(tmp_path: Path) -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    models = load_models(ROOT / "config" / "models.yaml")
    rows = run_study.generate_manifest(scripts, models)
    root = tmp_path / "study-v2"
    (root / "foreign").mkdir(parents=True)
    (root / "foreign" / "run.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StudyEvidenceError, match="Unexpected run"):
        audit_study_evidence(rows, root)


def _fingerprint(paths: list[Path]) -> str:
    payload = b"".join(
        path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
        for path in sorted(paths)
    )
    return hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    ("namespace", "expected_count", "expected_hash"),
    [
        (
            "technical-pilot-v1",
            25,
            "f1c3a050c306d69cff0fea7dc9ca03fe1b7f8bd0e3d6fccb3e7d49661b4f2496",
        ),
        (
            "technical-pilot-v2",
            22,
            "e08b1a247662cc8a5c60e60e84086974cd2d4742c21118c92dea5b2b1beabda0",
        ),
        (
            "technical-pilot-v3",
            26,
            "dab2e3aafe0a65273aeec9e174ff089181c59db28c80b8673c3f8467042d3952",
        ),
        (
            "technical-pilot-v4",
            28,
            "679034620c7d73ba84195bb57317b06db5a1168795feb3875ab27ead33ed750a",
        ),
        (
            "technical-pilot-v5",
            28,
            "c8b597a08085ea053faaeb89e802bae62a428aebe63e75ee82d7b61b1cba28d1",
        ),
    ],
)
def test_local_historical_pilot_evidence_is_immutable(
    namespace: str, expected_count: int, expected_hash: str
) -> None:
    paths = sorted(
        path
        for directory in (ROOT / "data" / "raw" / "runs").glob(f"{namespace}_*")
        for path in directory.rglob("*")
        if path.is_file()
    )
    if not paths:
        pytest.skip("Raw evidence is deliberately excluded from a fresh clone")
    assert len(paths) == expected_count
    assert _fingerprint(paths) == expected_hash


def test_local_endpoint_screen_is_immutable() -> None:
    paths = sorted(
        path
        for directory in (ROOT / "data" / "raw" / "screens").glob("technical-endpoint-screen-v1_*")
        for path in directory.rglob("*")
        if path.is_file()
    )
    if not paths:
        pytest.skip("Screen evidence is deliberately excluded from a fresh clone")
    assert len(paths) == 1
    assert _fingerprint(paths) == "dae8db55367fc1f8f8c92e1ec231801ef5f58f6d89fb221aed8f867edc81837b"


def test_local_pilot_v4_assessment_records_are_immutable() -> None:
    paths = sorted((ROOT / "data" / "raw" / "pilot-v4-qualification").glob("*.json"))
    if not paths:
        pytest.skip("Private qualification records are excluded from a fresh clone")
    assert len(paths) == 5
    assert _fingerprint(paths) == "965694b364a8a3ef9a017e6452824ff10ae08aba4c18435df14ae168736629c9"


def test_local_pilot_v5_assessment_records_are_immutable() -> None:
    paths = sorted((ROOT / "data" / "raw" / "pilot-v5-qualification").glob("*.json"))
    if not paths:
        pytest.skip("Private qualification records are excluded from a fresh clone")
    assert len(paths) == 4
    assert _fingerprint(paths) == "945ade153e419339a7f22d793a5ffc843470a917fd1c315e2a95dd0864d4e1f2"


def test_scenarios_histories_and_frozen_rubric_are_unchanged() -> None:
    scenarios = sorted((ROOT / "config" / "scenarios").glob("*.json"))
    histories = sorted((ROOT / "config" / "histories").glob("*.json"))
    rubric = [ROOT / "config" / "rubric.yaml"]
    assert len(scenarios) == 9
    assert len(histories) == 3
    assert _fingerprint(scenarios) == (
        "8c730208b66f08bc9f1a71911b3895cb14202280f412a7a4b96667fc288147b6"
    )
    assert _fingerprint(histories) == (
        "895748698d6faaffcedda72e740ff5b50f8de8ba4a3701550bd3d3d06ade4ee9"
    )
    assert _fingerprint(rubric) == (
        "b998e112dcc93abdd97aefbf669b53fd9aad840723df9b18e80e9264e9cb5b6a"
    )


def test_historical_protocol_bundle_is_byte_identical() -> None:
    from scripts.protocol_bundle import historical_bundle_fingerprint

    assert historical_bundle_fingerprint() == (
        "1ac2fcb151c6cac1d6f59464fc2074dc6ecc15ac1df9a98480224c509bcfb97b"
    )
