"""Print and persist a safe aggregate audit of immutable failed Pilot V5 evidence."""

# ruff: noqa: E402
from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_pilot_v5 import DEFAULT_OUTPUT_ROOT
from src.pilot_qualification import assess_pilot_v5, pilot_v5_safe_cross_tab
from src.storage import atomic_write_json

AUDIT_VERSION = "pilot-v5-audit-v1.0.0"
DERIVED_ROOT = ROOT / "data" / "derived"


def _persist_safe_aggregate(assessment, cross_tab: list[dict]) -> Path:  # noqa: ANN001, ANN202
    stats = assessment.statistics
    timestamp = datetime.now(UTC)
    return atomic_write_json(
        DERIVED_ROOT
        / "pilot-v5-audit"
        / f"{AUDIT_VERSION}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}.json",
        {
            "audit_version": AUDIT_VERSION,
            "record_type": "PILOT V5 SAFE AGGREGATE AUDIT - TECHNICAL EVIDENCE ONLY",
            "audited_at": timestamp.isoformat(),
            "pilot_version": assessment.pilot_version,
            "verdict": assessment.verdict.value,
            "failed_criteria": list(assessment.failed_criteria),
            "main_study_blocked": assessment.main_study_blocked,
            "source_evidence_hash": assessment.source_evidence_hash,
            "statistics": stats,
            "cross_tab": cross_tab,
            "resume_would_perform_useful_work": False,
            "qualification_can_become_pass_via_resume": False,
            "immutable": True,
        },
    )


def main() -> int:
    assessment = assess_pilot_v5(output_root=DEFAULT_OUTPUT_ROOT, persist=False)
    stats = assessment.statistics
    cross_tab = pilot_v5_safe_cross_tab(output_root=DEFAULT_OUTPUT_ROOT)
    print("PILOT V5 SAFE AGGREGATE AUDIT - TECHNICAL EVIDENCE ONLY")
    print("requested_model | resolved_model | provider | finish_reason | truncated | count")
    for row in cross_tab:
        print(
            f"{row['requested_model']} | {row['resolved_model']} | "
            f"{row['resolved_provider']} | {row['finish_reason']} | "
            f"{str(row['truncated']).lower()} | {row['response_count']}"
        )
    print(f"successful_response_slots={stats['successful_response_slots']}/24")
    print(f"missing_response_slots={stats['missing_response_slots']}")
    print(f"http_attempts={stats['http_attempts_used']}/32")
    print(f"remaining_attempt_allowance={stats['remaining_attempt_allowance']}")
    print("resume_would_perform_useful_work=no")
    print("qualification_can_become_pass_via_resume=no")
    print("reason=successful turns are immutable; 11 truncated responses cannot be replaced")
    print(f"verdict={assessment.verdict.value}")
    print(f"source_evidence_hash={assessment.source_evidence_hash}")
    persisted = _persist_safe_aggregate(assessment, cross_tab)
    print(f"persisted_safe_aggregate={persisted.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
