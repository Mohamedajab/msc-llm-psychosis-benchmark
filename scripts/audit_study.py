"""Print a no-content Study V2 reconciliation and technical audit."""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_study import DEFAULT_OUTPUT_ROOT, load_frozen_study
from src.study_audit import audit_study_evidence


def main() -> int:
    try:
        _, _, _, rows = load_frozen_study()
        report = audit_study_evidence(rows, DEFAULT_OUTPUT_ROOT)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
