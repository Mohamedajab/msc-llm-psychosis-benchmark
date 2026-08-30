"""Audit Pilot V4/V5 token budgets without printing response content."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.generation_budget import audit_generation_budget
from src.storage import atomic_write_json

DEFAULT_OUTPUT_ROOT = ROOT / "data" / "raw" / "runs"
DEFAULT_DERIVED_ROOT = ROOT / "data" / "derived" / "generation-budget"


def _format(value: object) -> str:
    return "NOT_REPORTED" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--derived-root", type=Path, default=DEFAULT_DERIVED_ROOT)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)
    audit = audit_generation_budget(args.output_root)
    print(audit.record_type)
    for name, pilot in audit.pilots.items():
        print(
            f"{name}: verdict={pilot['verdict']}; "
            f"successful={pilot['successful_response_slots']}; "
            f"source_evidence_hash={pilot['source_evidence_hash']}"
        )
        for row in pilot["rows"]:
            print(
                " | ".join(
                    (
                        str(row["requested_model"]),
                        str(row["resolved_model"]),
                        str(row["provider"]),
                        str(row["context_condition"]),
                        str(row["finish_reason"]),
                        f"truncated={str(row['truncated']).lower()}",
                        f"count={row['response_count']}",
                        f"prompt_median={_format(row['median_prompt_tokens'])}",
                        f"completion_median={_format(row['median_completion_tokens'])}",
                        f"reasoning_median={_format(row['median_reasoning_tokens'])}",
                        f"visible_tokens_median={_format(row['median_visible_completion_tokens'])}",
                        f"visible_words_median={_format(row['median_visible_words'])}",
                        f"latency_ms_median={_format(row['median_latency_ms'])}",
                    )
                )
            )
    print(f"reasoning_contribution={audit.reasoning_contribution}")
    if not args.no_persist:
        now = datetime.now(UTC)
        path = atomic_write_json(
            args.derived_root / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json",
            {"audited_at": now.isoformat(), **audit.model_dump(mode="json")},
        )
        print(f"persisted_safe_aggregate={path.relative_to(ROOT)}")
    print("substantive_content_printed=no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
