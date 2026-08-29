"""Print a safe aggregate audit of immutable failed Pilot V4 evidence."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_pilot_v4 import DEFAULT_OUTPUT_ROOT
from src.pilot_qualification import assess_pilot_v4, pilot_v4_safe_cross_tab


def main() -> int:
    assessment = assess_pilot_v4(output_root=DEFAULT_OUTPUT_ROOT, persist=False)
    stats = assessment.statistics
    print("PILOT V4 SAFE AGGREGATE AUDIT - TECHNICAL EVIDENCE ONLY")
    print("requested_model | resolved_model | provider | finish_reason | truncated | count")
    for row in pilot_v4_safe_cross_tab(output_root=DEFAULT_OUTPUT_ROOT):
        print(
            f"{row['requested_model']} | {row['resolved_model']} | "
            f"{row['resolved_provider']} | {row['finish_reason']} | "
            f"{str(row['truncated']).lower()} | {row['response_count']}"
        )
    print(f"missing_response_slots={stats['missing_response_slots']}")
    print(f"remaining_attempt_allowance={stats['remaining_attempt_allowance']}")
    print("resume_would_perform_useful_work=no")
    print("qualification_can_become_pass_via_resume=no")
    print("reason=successful turns are immutable; a new versioned pilot is required")
    print(f"verdict={assessment.verdict.value}")
    print(f"source_evidence_hash={assessment.source_evidence_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
