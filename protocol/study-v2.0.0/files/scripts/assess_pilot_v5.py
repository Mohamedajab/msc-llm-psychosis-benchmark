"""Assess private Pilot V5 evidence locally and persist a safe qualification record."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_pilot_v5 import DEFAULT_OUTPUT_ROOT
from src.pilot_qualification import (
    QualificationVerdict,
    assess_pilot_v5,
    print_safe_assessment,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--assessment-root", type=Path)
    args = parser.parse_args(argv)
    try:
        assessment = assess_pilot_v5(
            output_root=args.pilot_output_root,
            assessment_root=args.assessment_root,
            persist=True,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: qualification could not be safely computed ({type(error).__name__})")
        return 2
    print_safe_assessment(assessment)
    if assessment.verdict == QualificationVerdict.PASS:
        return 0
    if assessment.verdict == QualificationVerdict.FAIL:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
