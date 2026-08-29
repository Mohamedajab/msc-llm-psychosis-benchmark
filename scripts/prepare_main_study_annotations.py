"""Create blinded annotation items from real Study V2 responses only."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_study import DEFAULT_OUTPUT_ROOT, load_frozen_study
from src.annotation import build_blinded_items, save_blinded_items, save_blinding_map
from src.storage import RawRunStore

DEFAULT_ITEMS = ROOT / "data" / "annotations" / "study-v2-blinded-items.json"
DEFAULT_MAP = ROOT / "data" / "private" / "study-v2-blinding-map.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--items-output", type=Path, default=DEFAULT_ITEMS)
    parser.add_argument("--map-output", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args(argv)
    try:
        _, _, _, rows = load_frozen_study()
        store = RawRunStore(DEFAULT_OUTPUT_ROOT)
        records = [
            store.load(row.run_id)
            for row in rows
            if (store.run_directory(row.run_id) / "run.json").is_file()
        ]
        if any(record.header.data_status != "main_study" for record in records):
            raise ValueError("Non-main-study evidence cannot enter Study V2 annotation items")
        response_count = sum(len(record.turns) for record in records)
        if response_count == 0:
            print("UNAVAILABLE: no real Study V2 responses exist; no files were created")
            return 3
        if not args.allow_partial and response_count != 432:
            raise ValueError(
                f"Study V2 is incomplete ({response_count}/432 responses); "
                "use --allow-partial only for an explicitly documented partial workflow"
            )
        key = os.environ.get("ANNOTATION_BLINDING_KEY", "").strip()
        if not key:
            raise ValueError(
                "ANNOTATION_BLINDING_KEY is required and is never written or printed"
            )
        items, mapping = build_blinded_items(records, blinding_key=key)
        save_blinded_items(args.items_output, items)
        save_blinding_map(args.map_output, mapping)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Blinded annotation items created: {len(items)}")
    print(f"Annotator file: {args.items_output.resolve()}")
    print(f"Private mapping: {args.map_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
