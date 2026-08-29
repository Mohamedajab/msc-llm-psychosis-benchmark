"""Assess one private replacement screen without making any network request."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_replacement_screen import DEFAULT_OUTPUT_ROOT
from src.replacement_screening import (
    ScreenVerdict,
    assess_replacement_screen,
    print_safe_assessment,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-model-id", required=True)
    parser.add_argument("--screen-output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--assessment-root", type=Path)
    args = parser.parse_args(argv)
    try:
        assessment = assess_replacement_screen(
            candidate_model_id=args.candidate_model_id,
            repository_root=ROOT,
            output_root=args.screen_output_root,
            assessment_root=args.assessment_root,
            persist=True,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: screen qualification could not be safely computed ({type(error).__name__})")
        return 2
    print_safe_assessment(assessment)
    if assessment.verdict == ScreenVerdict.PASS:
        return 0
    if assessment.verdict == ScreenVerdict.FAIL:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
