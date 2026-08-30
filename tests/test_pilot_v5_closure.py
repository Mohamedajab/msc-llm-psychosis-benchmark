"""Offline tests for Pilot V5 closure and the replacement-pending Study V2 state."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import audit_pilot_v5, run_study
from scripts.run_pilot_v5 import DEFAULT_OUTPUT_ROOT
from src.pilot_qualification import (
    QualificationVerdict,
    assess_pilot_v5,
    pilot_v5_safe_cross_tab,
)
from src.study_status import (
    STATUS_VERSION,
    final_model_pair_not_qualified,
    load_study_v2_status,
    replacement_endpoint_not_frozen,
)

ROOT = Path(__file__).parents[1]


def _has_local_v5_evidence() -> bool:
    return any((ROOT / "data" / "raw" / "runs").glob("technical-pilot-v5_*"))


def test_pilot_v5_source_hash_is_exact() -> None:
    if not _has_local_v5_evidence():
        pytest.skip("Pilot V5 raw evidence is deliberately excluded from a fresh clone")
    assessment = assess_pilot_v5(output_root=DEFAULT_OUTPUT_ROOT, persist=False)
    assert assessment.source_evidence_hash == (
        "4b8fed25b622c7cdbabd4483e0484ea9587e7bebfea7ad18deee5386c11647d0"
    )


def test_pilot_v5_cross_tab_is_derived_from_evidence() -> None:
    if not _has_local_v5_evidence():
        pytest.skip("Pilot V5 raw evidence is deliberately excluded from a fresh clone")
    assert pilot_v5_safe_cross_tab(output_root=DEFAULT_OUTPUT_ROOT) == [
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
            "response_count": 11,
        },
        {
            "requested_model": "nvidia/nemotron-3-super-120b-a12b:free",
            "resolved_model": "nvidia/nemotron-3-super-120b-a12b:free",
            "resolved_provider": "Nvidia",
            "finish_reason": "stop",
            "truncated": False,
            "response_count": 1,
        },
    ]


def test_pilot_v5_remains_fail_and_cannot_resume_into_pass() -> None:
    if not _has_local_v5_evidence():
        pytest.skip("Pilot V5 raw evidence is deliberately excluded from a fresh clone")
    assessment = assess_pilot_v5(output_root=DEFAULT_OUTPUT_ROOT, persist=False)
    assert assessment.verdict == QualificationVerdict.FAIL
    assert assessment.main_study_blocked is True
    assert assessment.statistics["missing_response_slots"] == 0
    # Complete-but-truncated evidence is terminal: immutable successful turns cannot
    # be replaced, so no further invocation can change FAIL into PASS.
    assert "zero_truncated_responses" in assessment.failed_criteria
    assert "only_complete_finish_reasons" in assessment.failed_criteria


def test_pilot_v5_audit_prints_no_response_content(capsys: pytest.CaptureFixture[str]) -> None:
    if not _has_local_v5_evidence():
        pytest.skip("Pilot V5 raw evidence is deliberately excluded from a fresh clone")
    assert audit_pilot_v5.main() == 0
    output = capsys.readouterr().out.casefold()
    assert "response text" not in output
    assert "request_messages" not in output
    assert "request_payload" not in output
    assert "api_key" not in output
    assert "verdict=fail" in output
    assert "source_evidence_hash=4b8fed25" in output
    assert "qualification_can_become_pass_via_resume=no" in output


def test_original_pair_requalification_status_is_versioned_and_blocked() -> None:
    status = load_study_v2_status()
    assert status.version == STATUS_VERSION
    assert status.replacement_endpoint_status == "NOT_SELECTED"
    assert status.pilot_v6_status == "NOT_RUN"
    assert status.final_pair_status == "NOT_QUALIFIED"
    assert status.final_pair_source == "NONE"
    assert status.replacement_required is False
    assert status.main_study_status == "BLOCKED"
    assert status.blocker == "final_model_pair_not_qualified"
    assert status.intended_model_a == "minimax/minimax-m3:free"
    assert status.intended_model_b == "nvidia/nemotron-3-super-120b-a12b:free"
    assert replacement_endpoint_not_frozen(status) is False
    assert final_model_pair_not_qualified(status) is True


def test_study_status_rejects_unknown_fields() -> None:
    from src.study_status import StudyV2Status

    with pytest.raises(ValueError):
        StudyV2Status.model_validate(
            {
                "version": STATUS_VERSION,
                "replacement_endpoint_status": "NOT_SELECTED",
                "pilot_v6_status": "NOT_RUN",
                "final_pair_status": "NOT_QUALIFIED",
                "final_pair_source": "NONE",
                "replacement_required": False,
                "main_study_status": "BLOCKED",
                "blocker": "final_model_pair_not_qualified",
                "intended_model_a": "minimax/minimax-m3:free",
                "intended_model_b": "nvidia/nemotron-3-super-120b-a12b:free",
                "unexpected": "field",
            }
        )


def test_final_pair_blocker_not_bypassable_by_cli_confirmation(tmp_path: Path, monkeypatch) -> None:
    class NetworkForbidden:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("provider must not be constructed while replacement pending")

    monkeypatch.setattr(run_study, "OpenRouterProvider", NetworkForbidden)
    monkeypatch.setattr(run_study, "verify_historical_bundle", lambda: {})
    with pytest.raises(run_study.StudyPreflightError, match="final_model_pair_not_qualified"):
        run_study.execute_live_study(
            maximum_http_attempts=1,
            live_requested=True,
            live_confirmed=True,
            protocol_confirmed=True,
            output_root=tmp_path / "study",
            pilot_output_root=tmp_path / "runs",
            environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test-only-value"},
        )
