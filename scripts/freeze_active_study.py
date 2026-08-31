# ruff: noqa: E402
"""Create or verify the prospective final Study V2 active protocol bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.active_study import freeze_active_study_bundle, verify_active_study_bundle
from src.pilot_v6 import PILOT_V6_VERSION

DEFAULT_BUNDLE = ROOT / "protocol" / "study-v2.1.0"
DEFAULT_PILOT_OUTPUT_ROOT = ROOT / "data" / "private" / PILOT_V6_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--confirm-freeze", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--artifact-root", type=Path, default=ROOT)
    parser.add_argument("--catalogue-record", type=Path)
    parser.add_argument("--selection-record", type=Path)
    parser.add_argument("--screen-output-root", type=Path)
    parser.add_argument("--pilot-output-root", type=Path, default=DEFAULT_PILOT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if args.create:
        if not args.confirm_freeze:
            print("ERROR: --create requires --confirm-freeze", file=sys.stderr)
            return 2
        operation = freeze_active_study_bundle
    else:
        operation = verify_active_study_bundle
    try:
        metadata = operation(
            bundle_root=args.bundle_root,
            repository_root=ROOT,
            artifact_root=args.artifact_root,
            selection_record_path=args.selection_record,
            catalogue_record_path=args.catalogue_record,
            screen_output_root=args.screen_output_root,
            pilot_output_root=args.pilot_output_root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"active_bundle=NOT_CREATED_OR_INVALID; error_type={type(error).__name__}")
        print("network_requests=0")
        return 1
    print(f"active_bundle=PASS; study_version={metadata.study_version}")
    print(f"planned_conversations={metadata.planned_conversations}")
    print(f"planned_response_slots={metadata.planned_response_slots}")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
