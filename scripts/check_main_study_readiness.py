# ruff: noqa: E402
"""Print the safe offline end-to-end Study V2 readiness state."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.main_study_readiness import evaluate_main_study_readiness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue-record", type=Path)
    parser.add_argument("--selection-record", type=Path)
    parser.add_argument("--screen-output-root", type=Path)
    parser.add_argument("--pilot-output-root", type=Path)
    parser.add_argument("--active-bundle-root", type=Path)
    parser.add_argument("--final-artifact-root", type=Path)
    parser.add_argument(
        "--governance",
        type=Path,
        default=ROOT / "config" / "main-study-governance.yaml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_main_study_readiness(
        repository_root=ROOT,
        governance_path=args.governance,
        catalogue_record_path=args.catalogue_record,
        selection_record_path=args.selection_record,
        screen_output_root=args.screen_output_root,
        pilot_output_root=args.pilot_output_root,
        active_bundle_root=args.active_bundle_root,
        final_artifact_root=args.final_artifact_root,
    )
    print("MAIN STUDY V2 READINESS - OFFLINE / SAFE AGGREGATES ONLY")
    for field in (
        "replacement_catalogue",
        "replacement_screen",
        "replacement_selection",
        "pilot_v6",
        "final_pair_status",
        "final_pair_source",
        "replacement_required",
        "active_bundle",
        "governance",
        "main_study",
    ):
        print(f"{field}={getattr(result, field)}")
    print(f"blockers={list(result.blockers)}")
    print("network_requests=0")
    return 0 if result.main_study == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
