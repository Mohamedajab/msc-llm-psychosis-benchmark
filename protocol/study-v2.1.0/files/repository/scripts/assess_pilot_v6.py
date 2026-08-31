"""Assess original-pair Pilot V6 evidence without any network request."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_pilot_v6 import DEFAULT_ASSESSMENT_ROOT, DEFAULT_OUTPUT_ROOT
from src.pilot_v6 import (
    PILOT_V6_NAMESPACE,
    PilotV6Verdict,
    assess_pilot_v6,
    print_safe_pilot_v6_assessment,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--assessment-root", type=Path, default=DEFAULT_ASSESSMENT_ROOT)
    args = parser.parse_args(argv)
    evidence_present = args.pilot_output_root.is_dir() and any(
        args.pilot_output_root.glob(f"{PILOT_V6_NAMESPACE}_*")
    )
    try:
        assessment = assess_pilot_v6(
            pilot_output_root=args.pilot_output_root,
            repository_root=ROOT,
            assessment_root=args.assessment_root,
            persist=evidence_present,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: Pilot V6 qualification unavailable ({type(error).__name__})")
        return 2
    print_safe_pilot_v6_assessment(assessment)
    if assessment.verdict == PilotV6Verdict.PASS:
        return 0
    if assessment.verdict == PilotV6Verdict.FAIL:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
