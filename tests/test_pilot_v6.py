"""Comprehensive zero-network tests for selection-bound Pilot V6."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from scripts import assess_pilot_v6 as assess_script
from scripts import run_pilot_v6, run_study
from src.active_study import (
    FINAL_MANIFEST_RELATIVE_PATH,
    FINAL_MODELS_RELATIVE_PATH,
    ActiveStudyError,
    freeze_active_study_bundle,
    verify_active_study_bundle,
)
from src.main_study_readiness import evaluate_main_study_readiness
from src.pilot_v6 import (
    FINAL_CONFIGURATION_VERSION,
    MAX_HTTP_ATTEMPTS,
    MINIMAX_MODEL_ID,
    PILOT_V6_NAMESPACE,
    PilotV6Verdict,
    assess_pilot_v6,
    build_pilot_v6_offline_plan,
    load_pilot_v6_configuration,
    pilot_v6_rows,
)
from src.provider_client import DeterministicFixtureProvider
from src.replacement_screening import (
    MAX_HTTP_ATTEMPTS as SCREEN_MAX_ATTEMPTS,
)
from src.replacement_screening import (
    build_catalogue_evidence,
    execute_screen_conversations,
    persist_catalogue_evidence,
)
from src.replacement_selection import create_replacement_selection
from src.schemas import ObservationStatus, ProviderResult
from src.storage import RawRunStore
from src.study_execution import execute_manifest_rows

ROOT = Path(__file__).parents[1]
REPLACEMENT = "example/final-replacement:free"
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _entry(model_id: str = REPLACEMENT) -> dict[str, object]:
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": "Synthetic final replacement",
        "description": "General purpose text assistant.",
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "supported_parameters": ["seed", "max_tokens", "temperature"],
        "context_length": 65_536,
        "top_provider": {"max_completion_tokens": 4096},
    }


class AttemptFixture(DeterministicFixtureProvider):
    def __init__(self, *, api_key: str = "test-only") -> None:
        assert api_key
        super().__init__()
        self.request_attempt_count = 0
        self.maximum = MAX_HTTP_ATTEMPTS
        self.retry_429: bool | None = None
        self.interval: float | None = None
        self.routing = None
        self.catalogue_checked = False
        self.sent_parameters: list[tuple[str, dict[str, object]]] = []

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def set_retry_rate_limits(self, enabled: bool) -> None:
        self.retry_429 = enabled

    def set_minimum_request_interval(self, seconds: float) -> None:
        self.interval = seconds

    def set_provider_routing(self, policy) -> None:  # noqa: ANN001
        self.routing = policy

    def validate_exact_models_strict(self, model_ids, **kwargs) -> None:  # noqa: ANN001, ANN003
        assert tuple(model_ids) == (MINIMAX_MODEL_ID, REPLACEMENT)
        assert kwargs["minimum_context_tokens"] == 16_384
        assert kwargs["required_completion_tokens"] == 4096
        assert kwargs["completion_limit_parameters"] == {
            MINIMAX_MODEL_ID: "max_tokens",
            REPLACEMENT: "max_tokens",
        }
        self.catalogue_checked = True

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        self.sent_parameters.append((kwargs["model_id"], kwargs["generation"].request_parameters()))
        if self.request_attempt_count >= self.maximum:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=kwargs["model_id"],
                provider_name="SyntheticProvider",
                latency_ms=0,
                retry_count=0,
                http_attempts=0,
                error_type="request_budget_exhausted",
            )
        self.request_attempt_count += 1
        return (
            super()
            .generate(**kwargs)
            .model_copy(update={"provider_name": "SyntheticProvider", "http_attempts": 1})
        )


def _prerequisites(tmp_path: Path) -> tuple[Path, Path, Path]:
    catalogue_record = persist_catalogue_evidence(
        build_catalogue_evidence([_entry()], retrieved_at=NOW),
        tmp_path / "catalogue",
    )
    screen_root = tmp_path / "screens"
    screen_provider = AttemptFixture()
    execute_screen_conversations(
        candidate_model_id=REPLACEMENT,
        repository_root=ROOT,
        output_root=screen_root,
        provider=screen_provider,
        maximum_http_attempts=SCREEN_MAX_ATTEMPTS,
        completion_limit_parameter="max_tokens",
    )
    _, selection_path = create_replacement_selection(
        candidate_model_id=REPLACEMENT,
        catalogue_record_path=catalogue_record,
        screen_output_root=screen_root,
        repository_root=ROOT,
        selection_root=tmp_path / "selection",
        selected_at=NOW,
    )
    return catalogue_record, screen_root, selection_path


def _configuration(tmp_path: Path):  # noqa: ANN202
    catalogue, screens, selection = _prerequisites(tmp_path)
    configured = load_pilot_v6_configuration(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
    )
    return catalogue, screens, selection, configured


def _write_pilot(tmp_path: Path, *, attempts: int = MAX_HTTP_ATTEMPTS):  # noqa: ANN202
    catalogue, screens, selection, configured = _configuration(tmp_path)
    _, _, _, models, scripts, histories = configured
    rows = pilot_v6_rows(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
    )
    output = tmp_path / "pilot-v6"
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=AttemptFixture(),
        store=RawRunStore(output),
        data_status="technical_pilot",
        maximum_http_attempts=attempts,
    )
    return catalogue, screens, selection, output, rows


def _assess(paths) -> object:  # noqa: ANN001
    catalogue, screens, selection, output, _ = paths
    return assess_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=output,
        repository_root=ROOT,
    )


def _mutate(path: Path, transform) -> None:  # noqa: ANN001, ANN202
    value = json.loads(path.read_text(encoding="utf-8"))
    transform(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _approved_governance(tmp_path: Path) -> Path:
    path = tmp_path / "governance.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": "main-study-governance-v1.0.0",
                "supervisor_protocol_approval": "APPROVED",
                "ethics_approval": "APPROVED",
                "rubric_approval": "APPROVED",
                "annotation_adjudication_approval": "APPROVED",
                "data_management_approval": "APPROVED",
                "notes": ["Synthetic test fixture only."],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_current_pilot_v6_is_not_configured_and_default_is_zero_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NetworkForbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("offline Pilot V6 must not construct a provider")

    monkeypatch.setattr(run_pilot_v6, "OpenRouterProvider", NetworkForbidden)
    plan = build_pilot_v6_offline_plan(
        selection_record_path=None,
        catalogue_record_path=None,
        screen_output_root=Path("unused"),
        repository_root=ROOT,
    )
    assert plan["status"] == "NOT_CONFIGURED"
    assert plan["network_requests"] == 0
    assert run_pilot_v6.main([]) == 0
    output = capsys.readouterr().out
    assert "pilot_v6=NOT_CONFIGURED" in output
    assert "network_requests=0" in output

    assessment = assess_pilot_v6(
        selection_record_path=None,
        catalogue_record_path=None,
        screen_output_root=Path("unused"),
        pilot_output_root=Path("unused"),
        repository_root=ROOT,
    )
    assert assessment.verdict == PilotV6Verdict.NOT_CONFIGURED
    assert assessment.failed_criteria == ("replacement_selection_not_frozen",)


def test_configured_offline_plan_freezes_final_pair_generation_and_subset(tmp_path: Path) -> None:
    catalogue, screens, selection, configured = _configuration(tmp_path)
    selected, script, _, models, _, _ = configured
    assert selected.selected_model_id == REPLACEMENT
    assert models.version == FINAL_CONFIGURATION_VERSION
    assert {slot: value.default_model_id for slot, value in models.model_slots.items()} == {
        "model_minimax": MINIMAX_MODEL_ID,
        "model_replacement": REPLACEMENT,
    }
    assert models.generation.version == "generation-v4"
    assert models.generation.temperature == 0.2
    assert models.generation.top_p == 1.0
    assert models.generation.max_tokens == 4096
    assert models.repetition_seeds == {1: 20260814, 2: 20260815}
    plan = build_pilot_v6_offline_plan(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
    )
    assert plan["network_requests"] == 0
    assert plan["planned_conversations"] == 4
    assert plan["planned_response_slots"] == 24
    assert plan["maximum_http_attempts"] == 32
    assert plan["failure_attempt_allowance"] == 8
    assert plan["minimum_request_interval_seconds"] == 5.0
    assert all(run["payload_count"] == 6 for run in plan["runs"])
    assert {run["model_slot"] for run in plan["runs"]} == {
        "model_minimax",
        "model_replacement",
    }
    assert {run["context_condition"] for run in plan["runs"]} == {
        "no_preloaded_context",
        "standardised_preloaded_context",
    }
    assert script.script_id == "monitoring_fixed_belief_v1"


def test_configured_but_absent_pilot_is_not_run(tmp_path: Path) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)
    assessment = assess_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=tmp_path / "empty-pilot",
        repository_root=ROOT,
    )
    assert assessment.verdict == PilotV6Verdict.NOT_RUN


def test_partial_pilot_is_incomplete_and_clean_24_of_24_passes(tmp_path: Path) -> None:
    partial = _write_pilot(tmp_path / "partial", attempts=3)
    partial_assessment = _assess(partial)
    assert partial_assessment.verdict == PilotV6Verdict.INCOMPLETE
    assert partial_assessment.statistics["successful_response_slots"] == 3

    complete = _write_pilot(tmp_path / "complete")
    complete_assessment = _assess(complete)
    assert complete_assessment.verdict == PilotV6Verdict.PASS
    assert complete_assessment.statistics["successful_response_slots"] == 24
    assert complete_assessment.statistics["truncation_count"] == 0
    assert complete_assessment.statistics["finish_reasons"] == {"stop": 24}


@pytest.mark.parametrize(
    ("change", "criterion"),
    [
        (
            lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
            "zero_truncated_responses",
        ),
        (
            lambda value: value["result"].update({"resolved_model_id": "wrong/model:free"}),
            "resolved_model_equals_requested_model",
        ),
        (
            lambda value: value["result"].update({"provider_name": None}),
            "provider_and_finish_reason_reported",
        ),
        (
            lambda value: value["result"].update({"text": ""}),
            "evidence_is_well_formed_unique_and_verifiable",
        ),
        (
            lambda value: value["result"].update({"http_attempts": 10}),
            "persisted_http_attempts_at_most_32",
        ),
        (
            lambda value: value.update({"request_parameters": {"seed": 999}}),
            "pilot_v6_request_payload_integrity",
        ),
    ],
)
def test_pilot_v6_fails_closed_for_invalid_response_or_request_metadata(
    tmp_path: Path,
    change,
    criterion: str,  # noqa: ANN001
) -> None:
    paths = _write_pilot(tmp_path)
    success = next(paths[3].rglob("turn-*-success.json"))
    _mutate(success, change)
    assessment = _assess(paths)
    assert assessment.verdict == PilotV6Verdict.FAIL
    assert criterion in assessment.failed_criteria


@pytest.mark.parametrize(
    "header_change",
    [
        {"study_version": "technical-pilot-v5.0.0"},
        {"script_id": "wrong_scenario"},
        {"context_condition": "no_preloaded_context", "history_id": "wrong_history"},
        {"requested_model_id": "wrong/model:free"},
        {"model_slot": "model_nemotron"},
        {"configuration_hash": "0" * 64},
    ],
)
def test_wrong_version_scenario_context_model_or_config_fails_closed(
    tmp_path: Path, header_change: dict[str, object]
) -> None:
    paths = _write_pilot(tmp_path)
    header = next(paths[3].rglob("run.json"))
    _mutate(header, lambda value: value.update(header_change))
    assessment = _assess(paths)
    assert assessment.verdict == PilotV6Verdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in assessment.failed_criteria


def test_pilot_v6_namespace_ignores_other_evidence_but_rejects_mixed_v6_run(
    tmp_path: Path,
) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)
    output = tmp_path / "pilot"
    for namespace in (
        "technical-pilot-v5_foreign",
        "replacement-screen-v2.0.0_foreign",
        "study-v2.1.0_foreign",
        "demo-fixture_foreign",
    ):
        directory = output / namespace
        directory.mkdir(parents=True)
        (directory / "run.json").write_text("{}", encoding="utf-8")
    assessment = assess_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=output,
        repository_root=ROOT,
    )
    assert assessment.verdict == PilotV6Verdict.NOT_RUN
    mixed = output / f"{PILOT_V6_NAMESPACE}_unexpected"
    mixed.mkdir()
    (mixed / "run.json").write_text("{}", encoding="utf-8")
    assessment = assess_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=output,
        repository_root=ROOT,
    )
    assert assessment.verdict == PilotV6Verdict.FAIL


@pytest.mark.parametrize(
    ("live", "confirmed", "environment", "message"),
    [
        (False, True, {"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "x"}, "--live"),
        (True, False, {"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "x"}, "confirm"),
        (True, True, {"OPENROUTER_API_KEY": "x"}, "RUN_LIVE_PILOT_V6"),
        (True, True, {"RUN_LIVE_PILOT_V6": "1"}, "API key"),
    ],
)
def test_every_live_gate_is_required_before_provider_construction(
    tmp_path: Path,
    live: bool,
    confirmed: bool,
    environment: dict[str, str],
    message: str,
) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)
    constructed = False

    def forbidden(**kwargs):  # noqa: ANN003, ANN202
        nonlocal constructed
        constructed = True
        raise AssertionError("provider construction must remain unreachable")

    with pytest.raises(Exception, match=message):
        run_pilot_v6.execute_live_pilot_v6(
            selection_record_path=selection,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            output_root=tmp_path / "pilot",
            live_requested=live,
            live_confirmed=confirmed,
            environ=environment,
            provider_factory=forbidden,
        )
    assert constructed is False


def test_missing_selection_blocks_before_provider_and_network(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="NOT_CONFIGURED"):
        run_pilot_v6.execute_live_pilot_v6(
            selection_record_path=None,
            catalogue_record_path=None,
            live_requested=True,
            live_confirmed=True,
            environ={"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "x"},
            provider_factory=lambda **_: (_ for _ in ()).throw(AssertionError("unreachable")),
        )


def test_mocked_live_path_enforces_routing_pacing_catalogue_and_passes(tmp_path: Path) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)
    instances: list[AttemptFixture] = []

    def factory(*, api_key: str) -> AttemptFixture:
        instance = AttemptFixture(api_key=api_key)
        instances.append(instance)
        return instance

    assessment = run_pilot_v6.execute_live_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        output_root=tmp_path / "pilot",
        assessment_root=tmp_path / "assessment",
        live_requested=True,
        live_confirmed=True,
        environ={"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "test-only"},
        provider_factory=factory,
    )
    assert assessment.verdict == PilotV6Verdict.PASS
    assert instances[0].retry_429 is False
    assert instances[0].interval == 5.0
    assert instances[0].routing.allow_fallbacks is False
    assert instances[0].routing.require_parameters is True
    assert instances[0].catalogue_checked is True
    assert len(instances[0].sent_parameters) == 24
    assert all(parameters["max_tokens"] == 4096 for _, parameters in instances[0].sent_parameters)


def test_catalogue_failure_is_append_only_and_sends_zero_generation_posts(tmp_path: Path) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)

    class CatalogueFailure(AttemptFixture):
        def validate_exact_models_strict(self, model_ids, **kwargs) -> None:  # noqa: ANN001, ANN003
            del model_ids, kwargs
            raise RuntimeError("synthetic catalogue failure")

    instance = CatalogueFailure()
    preflight_root = tmp_path / "preflight"
    with pytest.raises(Exception, match="failed before POST"):
        run_pilot_v6.execute_live_pilot_v6(
            selection_record_path=selection,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            output_root=tmp_path / "pilot",
            preflight_root=preflight_root,
            live_requested=True,
            live_confirmed=True,
            environ={"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "test-only"},
            provider_factory=lambda **_: instance,
        )
    assert instance.request_attempt_count == 0
    records = list(preflight_root.glob("*.json"))
    assert len(records) == 1
    saved = json.loads(records[0].read_text(encoding="utf-8"))
    assert saved["generation_requests_made"] == 0
    assert "test-only" not in records[0].read_text(encoding="utf-8")


def test_429_stops_current_invocation_and_later_resume_is_append_only(tmp_path: Path) -> None:
    catalogue, screens, selection, _ = _configuration(tmp_path)

    class RateLimited(AttemptFixture):
        def generate(self, **kwargs):  # noqa: ANN003, ANN202
            self.request_attempt_count += 1
            return ProviderResult(
                status=ObservationStatus.RATE_LIMITED,
                requested_model_id=kwargs["model_id"],
                provider_name="SyntheticProvider",
                latency_ms=0,
                retry_count=0,
                http_attempts=1,
                http_status=429,
                error_type="http_429",
            )

    first = run_pilot_v6.execute_live_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        output_root=tmp_path / "pilot",
        assessment_root=tmp_path / "assessment",
        live_requested=True,
        live_confirmed=True,
        environ={"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "test-only"},
        provider_factory=lambda **_: RateLimited(),
    )
    assert first.verdict == PilotV6Verdict.INCOMPLETE
    error_path = next((tmp_path / "pilot").rglob("*-error-01.json"))
    original = error_path.read_bytes()
    second = run_pilot_v6.execute_live_pilot_v6(
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        output_root=tmp_path / "pilot",
        assessment_root=tmp_path / "assessment",
        live_requested=True,
        live_confirmed=True,
        environ={"RUN_LIVE_PILOT_V6": "1", "OPENROUTER_API_KEY": "test-only"},
        provider_factory=lambda **_: AttemptFixture(),
    )
    assert second.verdict == PilotV6Verdict.PASS
    assert error_path.read_bytes() == original
    assert second.statistics["http_attempts_used"] == 25


def test_assessor_output_is_content_free_and_append_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_pilot(tmp_path)
    catalogue, screens, selection, output, _ = paths
    args = [
        "--selection-record",
        str(selection),
        "--catalogue-record",
        str(catalogue),
        "--screen-output-root",
        str(screens),
        "--pilot-output-root",
        str(output),
        "--assessment-root",
        str(tmp_path / "assessments"),
    ]
    assert assess_script.main(args) == 0
    assert assess_script.main(args) == 0
    assert len(list((tmp_path / "assessments").glob("*.json"))) == 2
    output_text = capsys.readouterr().out
    private_markers = (
        "I can see why that stood out",
        "request_messages",
        "user_message",
        "request_payload_hash",
        "OPENROUTER_API_KEY",
    )
    assert all(value not in output_text for value in private_markers)


def test_active_bundle_cannot_be_created_without_selection_or_v6_pass(tmp_path: Path) -> None:
    with pytest.raises(ActiveStudyError, match="selection and Pilot V6 PASS"):
        freeze_active_study_bundle(
            repository_root=ROOT,
            artifact_root=tmp_path / "artifacts",
            bundle_root=tmp_path / "bundle",
            selection_record_path=None,
            catalogue_record_path=None,
            screen_output_root=None,
            pilot_output_root=None,
            software_commit="synthetic-test",
        )

    catalogue, screens, selection, _ = _configuration(tmp_path / "not-run")
    with pytest.raises(ActiveStudyError, match="NOT_RUN, not PASS"):
        freeze_active_study_bundle(
            repository_root=ROOT,
            artifact_root=tmp_path / "artifacts-not-run",
            bundle_root=tmp_path / "bundle-not-run",
            selection_record_path=selection,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            pilot_output_root=tmp_path / "empty-pilot",
            software_commit="synthetic-test",
        )


def _freeze_valid_bundle(tmp_path: Path):  # noqa: ANN202
    paths = _write_pilot(tmp_path / "evidence")
    catalogue, screens, selection, pilot_output, _ = paths
    artifacts = tmp_path / "artifacts"
    bundle = tmp_path / "bundle"
    metadata = freeze_active_study_bundle(
        repository_root=ROOT,
        artifact_root=artifacts,
        bundle_root=bundle,
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=pilot_output,
        created_at=NOW,
        software_commit="synthetic-test",
    )
    return catalogue, screens, selection, pilot_output, artifacts, bundle, metadata


def test_final_freeze_creates_exact_72_row_selected_pair_and_safe_bundle(tmp_path: Path) -> None:
    catalogue, screens, selection, pilot, artifacts, bundle, metadata = _freeze_valid_bundle(
        tmp_path
    )
    assert metadata.study_version == "study-v2.1.0"
    assert metadata.configuration_version == "2.3.0"
    assert metadata.generation_version == "generation-v4"
    assert len(metadata.generation_profile_hash) == 64
    assert metadata.planned_conversations == 72
    assert metadata.planned_response_slots == 432
    assert metadata.model_ids == {
        "model_minimax": MINIMAX_MODEL_ID,
        "model_replacement": REPLACEMENT,
    }
    frame = pd.read_csv(artifacts / FINAL_MANIFEST_RELATIVE_PATH)
    assert len(frame) == 72
    assert frame["run_id"].nunique() == 72
    assert set(frame["requested_model_id"]) == {MINIMAX_MODEL_ID, REPLACEMENT}
    assert set(frame["repetition"]) == {1, 2}
    assert set(frame["planned_seed"]) == {20260814, 20260815}
    assert set(frame["context_condition"]) == {
        "no_preloaded_context",
        "standardised_preloaded_context",
    }
    assert (artifacts / FINAL_MODELS_RELATIVE_PATH).is_file()
    verified = verify_active_study_bundle(
        bundle_root=bundle,
        repository_root=ROOT,
        artifact_root=artifacts,
        selection_record_path=selection,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        pilot_output_root=pilot,
    )
    assert verified == metadata
    bundled_paths = {item.bundle_path for item in metadata.items}
    assert all("data/raw" not in value for value in bundled_paths)
    assert all("response" not in value for value in bundled_paths)


def test_active_bundle_detects_bundled_or_current_source_tampering(tmp_path: Path) -> None:
    catalogue, screens, selection, pilot, artifacts, bundle, _ = _freeze_valid_bundle(tmp_path)
    bundled_manifest = bundle / "files" / "artifact" / FINAL_MANIFEST_RELATIVE_PATH
    bundled_manifest.write_bytes(bundled_manifest.read_bytes() + b"\n")
    with pytest.raises(ActiveStudyError, match="hash mismatch"):
        verify_active_study_bundle(
            bundle_root=bundle,
            repository_root=ROOT,
            artifact_root=artifacts,
            selection_record_path=selection,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            pilot_output_root=pilot,
        )

    second = _freeze_valid_bundle(tmp_path / "second")
    second[4].joinpath(FINAL_MODELS_RELATIVE_PATH).write_text("version: tampered\n")
    with pytest.raises(ActiveStudyError, match="Current-source mismatch"):
        verify_active_study_bundle(
            bundle_root=second[5],
            repository_root=ROOT,
            artifact_root=second[4],
            selection_record_path=second[2],
            catalogue_record_path=second[0],
            screen_output_root=second[1],
            pilot_output_root=second[3],
        )


def test_readiness_is_blocked_today_and_ready_only_on_complete_synthetic_chain(
    tmp_path: Path,
) -> None:
    current = evaluate_main_study_readiness(
        repository_root=ROOT,
        governance_path=ROOT / "config" / "main-study-governance.yaml",
    )
    assert current.replacement_catalogue == "NOT_FETCHED"
    assert current.replacement_screen == "NOT_RUN"
    assert current.replacement_selection == "NOT_SELECTED"
    assert current.pilot_v6 == "NOT_CONFIGURED"
    assert current.active_bundle == "NOT_CREATED"
    assert current.main_study == "BLOCKED"
    assert current.network_requests == 0

    catalogue, screens, selection, pilot, artifacts, bundle, _ = _freeze_valid_bundle(
        tmp_path / "ready"
    )
    ready = evaluate_main_study_readiness(
        repository_root=ROOT,
        governance_path=_approved_governance(tmp_path),
        catalogue_record_path=catalogue,
        selection_record_path=selection,
        screen_output_root=screens,
        pilot_output_root=pilot,
        active_bundle_root=bundle,
        final_artifact_root=artifacts,
    )
    assert ready.replacement_screen == "PASS"
    assert ready.replacement_selection == "PASS"
    assert ready.pilot_v6 == "PASS"
    assert ready.active_bundle == "PASS"
    assert ready.governance == "PASS"
    assert ready.main_study == "READY"
    assert ready.blockers == ()


def test_main_study_blocks_before_provider_without_chain_and_uses_mock_only_when_ready(
    tmp_path: Path,
) -> None:
    constructed = False

    def forbidden(**kwargs):  # noqa: ANN003, ANN202
        nonlocal constructed
        constructed = True
        raise AssertionError("provider construction must remain unreachable")

    with pytest.raises(run_study.StudyPreflightError, match="replacement_endpoint_not_frozen"):
        run_study.execute_live_study(
            maximum_http_attempts=1,
            live_requested=True,
            live_confirmed=True,
            protocol_confirmed=True,
            output_root=tmp_path / "blocked-output",
            pilot_output_root=tmp_path / "blocked-pilot",
            environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test-only"},
            provider_factory=forbidden,
        )
    assert constructed is False

    catalogue, screens, selection, pilot, artifacts, bundle, _ = _freeze_valid_bundle(
        tmp_path / "allowed"
    )
    instances: list[AttemptFixture] = []

    def factory(*, api_key: str) -> AttemptFixture:
        instance = AttemptFixture(api_key=api_key)
        instances.append(instance)
        return instance

    summary = run_study.execute_live_study(
        maximum_http_attempts=1,
        live_requested=True,
        live_confirmed=True,
        protocol_confirmed=True,
        output_root=tmp_path / "allowed-output",
        pilot_output_root=pilot,
        catalogue_record_path=catalogue,
        selection_record_path=selection,
        screen_output_root=screens,
        active_bundle_root=bundle,
        final_artifact_root=artifacts,
        governance_path=_approved_governance(tmp_path / "allowed-governance"),
        environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test-only"},
        provider_factory=factory,
    )
    assert instances and instances[0].request_attempt_count == 1
    assert summary["http_attempts_used"] == 1
