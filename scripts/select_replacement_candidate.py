"""Create a governed replacement selection from retained technical PASS evidence."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.replacement_screening import SCREEN_VERSION
from src.replacement_selection import (
    SELECTION_NAMESPACE,
    create_replacement_selection,
)

DEFAULT_SCREEN_ROOT = ROOT / "data" / "private" / SCREEN_VERSION
DEFAULT_SELECTION_ROOT = ROOT / "data" / "private" / SELECTION_NAMESPACE


def print_not_selected() -> None:
    print("REPLACEMENT SELECTION - NOT RESEARCH DATA")
    print("replacement_catalogue=NOT_FETCHED")
    print("replacement_screen=NOT_RUN")
    print("replacement_selection=NOT_SELECTED")
    print("selection_record_created=no")
    print("network_requests=0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--confirm-selection", action="store_true")
    parser.add_argument("--candidate-model-id")
    parser.add_argument("--catalogue-record", type=Path)
    parser.add_argument("--screen-output-root", type=Path, default=DEFAULT_SCREEN_ROOT)
    parser.add_argument("--selection-root", type=Path, default=DEFAULT_SELECTION_ROOT)
    args = parser.parse_args(argv)
    if not args.select:
        print_not_selected()
        return 0
    if not args.confirm_selection:
        print("ERROR: selection requires --confirm-selection", file=sys.stderr)
        return 2
    if not args.candidate_model_id or args.catalogue_record is None:
        print(
            "ERROR: selection requires an exact candidate and retained catalogue record",
            file=sys.stderr,
        )
        return 2
    try:
        record, path = create_replacement_selection(
            candidate_model_id=args.candidate_model_id,
            catalogue_record_path=args.catalogue_record,
            screen_output_root=args.screen_output_root,
            repository_root=ROOT,
            selection_root=args.selection_root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("REPLACEMENT SELECTION - NOT RESEARCH DATA")
    print("replacement_selection=SELECTED")
    print(f"selected_model_id={record.selected_model_id}")
    print(f"selection_reason_code={record.selection_reason_code}")
    print(f"selection_record={path.resolve()}")
    print("response_content_consulted=no")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
