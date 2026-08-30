"""Offline tests for immutable Pilot V4 and the active Pilot V5 qualification gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import audit_pilot_v4, run_pilot_v4, run_pilot_v5, run_study
from src.pilot_qualification import (
    QualificationVerdict,
    assess_pilot_v4,
    assess_pilot_v5,
    pilot_v4_safe_cross_tab,
)
from src.provider_client import DeterministicFixtureProvider
from src.schemas import ObservationStatus, ProviderResult
from src.storage import RawRunStore
from src.study_execution import execute_manifest_rows


class QualificationFixture(DeterministicFixtureProvider):
    """A deterministic provider whose calls represent persisted HTTP attempts."""

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


def _write_pilot(root: Path, *, attempts: int = 32) -> list[Path]:
    _, _, models, scripts, histories = run_pilot_v5._configuration()
    rows = run_pilot_v5.pilot_rows()
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=QualificationFixture(),
        store=RawRunStore(root),
        data_status="technical_pilot",
        maximum_http_attempts=attempts,
    )
    return sorted(root.rglob("turn-*-success.json"))


def _mutate(path: Path, transform) -> None:  # noqa: ANN001, ANN202
    value = json.loads(path.read_text(encoding="utf-8"))
    transform(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_no_pilot_v5_records_is_not_run_and_not_persisted_by_preflight(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.NOT_RUN
    assert result.main_study_blocked is True
    assert result.statistics["successful_response_slots"] == 0
    assert not (tmp_path / "pilot-v5-qualification").exists()


def test_pilot_v5_cannot_read_or_mix_earlier_pilot_evidence(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    earlier = root / "technical-pilot-v4_foreign"
    earlier.mkdir(parents=True)
    (earlier / "run.json").write_text("{}", encoding="utf-8")
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.NOT_RUN
    assert result.statistics["source_file_count"] == 0


def test_partial_pilot_is_incomplete_when_resume_is_mathematically_possible(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    _write_pilot(root, attempts=3)
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.INCOMPLETE
    assert result.statistics["successful_response_slots"] == 3
    assert result.statistics["mathematically_resumable"] is True


def test_valid_24_of_24_pilot_passes_and_assessments_are_append_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    assert len(_write_pilot(root)) == 24
    first = assess_pilot_v5(output_root=root, persist=True)
    second = assess_pilot_v5(output_root=root, persist=True)
    assert first.verdict == QualificationVerdict.PASS
    assert second.verdict == QualificationVerdict.PASS
    assert first.source_evidence_hash == second.source_evidence_hash
    assert len(list((tmp_path / "pilot-v5-qualification").glob("*.json"))) == 2


@pytest.mark.parametrize(
    ("change", "criterion"),
    [
        (
            lambda value: value["result"].update({"finish_reason": "stop", "truncated": True}),
            "evidence_is_well_formed_unique_and_verifiable",
        ),
        (
            lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
            "zero_truncated_responses",
        ),
        (
            lambda value: value["result"].update({"text": ""}),
            "evidence_is_well_formed_unique_and_verifiable",
        ),
        (
            lambda value: value["result"].update({"resolved_model_id": "wrong/model"}),
            "resolved_model_equals_requested_model",
        ),
        (
            lambda value: value["result"].update({"resolved_model_id": None}),
            "resolved_model_equals_requested_model",
        ),
        (
            lambda value: value["result"].update({"provider_name": None}),
            "provider_and_finish_reason_reported",
        ),
        (
            lambda value: value["result"].update({"http_attempts": 10}),
            "persisted_http_attempts_at_most_32",
        ),
    ],
)
def test_complete_pilot_fails_closed_for_invalid_success_evidence(
    tmp_path: Path,
    change,
    criterion: str,  # noqa: ANN001
) -> None:
    root = tmp_path / "runs"
    success = _write_pilot(root)[0]
    _mutate(success, change)
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.FAIL
    assert criterion in result.failed_criteria


def test_mixed_pilot_version_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _write_pilot(root)
    header = next(root.rglob("run.json"))
    _mutate(header, lambda value: value.update({"study_version": "technical-pilot-v4.0.0"}))
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in result.failed_criteria


def test_non_contiguous_turns_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    successes = _write_pilot(root)
    next(path for path in successes if path.name == "turn-03-success.json").unlink()
    result = assess_pilot_v5(output_root=root)
    assert result.verdict == QualificationVerdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in result.failed_criteria


def test_stale_persisted_pass_is_not_trusted_after_source_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    success = _write_pilot(root)[0]
    passed = assess_pilot_v5(output_root=root, persist=True)
    _mutate(success, lambda value: value["result"].update({"finish_reason": None}))
    recomputed = assess_pilot_v5(output_root=root)
    assert passed.verdict == QualificationVerdict.PASS
    assert recomputed.verdict == QualificationVerdict.FAIL
    assert recomputed.source_evidence_hash != passed.source_evidence_hash


def _live_environment() -> dict[str, str]:
    return {"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test-only-value"}


def test_main_study_blocks_before_provider_construction_when_replacement_pending(
    tmp_path: Path, monkeypatch
) -> None:
    constructed = False

    def forbidden_provider(**kwargs):  # noqa: ANN003, ANN202
        nonlocal constructed
        constructed = True
        raise AssertionError("provider construction must remain unreachable")

    monkeypatch.setattr(run_study, "verify_historical_bundle", lambda: {})
    with pytest.raises(run_study.StudyPreflightError, match="final_model_pair_not_qualified"):
        run_study.execute_live_study(
            maximum_http_attempts=1,
            live_requested=True,
            live_confirmed=True,
            protocol_confirmed=True,
            output_root=tmp_path / "study",
            pilot_output_root=tmp_path / "runs",
            environ=_live_environment(),
            provider_factory=forbidden_provider,
        )
    assert constructed is False


def test_main_study_blocks_after_recomputed_pass_when_replacement_pending(
    tmp_path: Path, monkeypatch
) -> None:
    pilot_root = tmp_path / "runs"
    _write_pilot(pilot_root)

    class MockedStudyProvider(QualificationFixture):
        constructed = False

        def __init__(self, *, api_key: str) -> None:
            assert api_key
            super().__init__()
            type(self).constructed = True

    monkeypatch.setattr(run_study, "verify_historical_bundle", lambda: {})
    with pytest.raises(run_study.StudyPreflightError, match="final_model_pair_not_qualified"):
        run_study.execute_live_study(
            maximum_http_attempts=1,
            live_requested=True,
            live_confirmed=True,
            protocol_confirmed=True,
            output_root=tmp_path / "study",
            pilot_output_root=pilot_root,
            environ=_live_environment(),
            provider_factory=MockedStudyProvider,
        )
    assert MockedStudyProvider.constructed is False


def test_offline_main_study_reports_gate_without_constructing_provider(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        run_study, "verify_historical_bundle", lambda: {"software_commit": "x", "items": []}
    )
    report = run_study.build_offline_preflight(pilot_output_root=tmp_path / "runs")
    assert report["network_called"] is False
    assert report["pilot_v4_qualification"] == "NOT_RUN"
    assert report["pilot_v5_qualification"] == "NOT_RUN"
    assert report["replacement_endpoint_status"] == "NOT_SELECTED"
    assert report["pilot_v6_status"] == "NOT_RUN"
    assert report["main_study_status"] == "BLOCKED"
    assert report["replacement_blocker"] == "final_model_pair_not_qualified"
    assert report["main_study_live_blocked"] is True


def test_local_pilot_v4_remains_failed_and_has_safe_verified_cross_tab() -> None:
    root = Path(__file__).parents[1] / "data" / "raw" / "runs"
    if not any(root.glob("technical-pilot-v4_*")):
        pytest.skip("Raw Pilot V4 evidence is deliberately excluded from a fresh clone")
    assessment = assess_pilot_v4(output_root=root, persist=False)
    assert assessment.verdict == QualificationVerdict.FAIL
    assert assessment.source_evidence_hash == (
        "36ba9906eed1628c95f50f18d4c149007bec7f04eac399c55c5599d5a858fb3e"
    )
    assert assessment.statistics["truncation_count"] == 12
    assert pilot_v4_safe_cross_tab(output_root=root) == [
        {
            "requested_model": "minimax/minimax-m3:free",
            "resolved_model": "minimax/minimax-m3:free",
            "resolved_provider": "GMICloud",
            "finish_reason": "stop",
            "truncated": False,
            "response_count": 12,
        },
        {
            "requested_model": "nvidia/nemotron-3-super-120b-a12b:free",
            "resolved_model": "nvidia/nemotron-3-super-120b-a12b:free",
            "resolved_provider": "Nvidia",
            "finish_reason": "length",
            "truncated": True,
            "response_count": 12,
        },
    ]


def test_pilot_v4_is_retired_and_cannot_be_resumed_into_pass() -> None:
    with pytest.raises(run_pilot_v4.PilotV4PreflightError, match="closed as immutable"):
        run_pilot_v4.execute_live_pilot_v4(
            live_requested=True,
            live_confirmed=True,
            environ={"RUN_LIVE_PILOT": "1", "OPENROUTER_API_KEY": "test-only-value"},
        )


def test_safe_v4_audit_prints_no_private_content(capsys) -> None:  # noqa: ANN001
    root = Path(__file__).parents[1] / "data" / "raw" / "runs"
    if not any(root.glob("technical-pilot-v4_*")):
        pytest.skip("Raw Pilot V4 evidence is deliberately excluded from a fresh clone")
    assert audit_pilot_v4.main() == 0
    output = capsys.readouterr().out.casefold()
    assert "response text" not in output
    assert "prompt text" not in output
    assert "request_messages" not in output
    assert "request_payload" not in output
    assert "api_key" not in output
