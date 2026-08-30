"""Run the benign generation-budget calibration; offline by default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.generation_calibration import (
    CALIBRATION_LABEL,
    CALIBRATION_VERSION,
    execute_calibration,
    load_calibration_summary,
    offline_calibration_plan,
)
from src.provider_client import OpenRouterProvider

DEFAULT_OUTPUT_ROOT = ROOT / "data" / "private" / CALIBRATION_VERSION


def require_live_gates(
    *, live_requested: bool, live_confirmed: bool, environ: Mapping[str, str]
) -> str:
    if not live_requested:
        raise RuntimeError("Live calibration requires --live")
    if not live_confirmed:
        raise RuntimeError("Live calibration requires --confirm-live")
    if environ.get("RUN_LIVE_CALIBRATION") != "1":
        raise RuntimeError("Live calibration requires RUN_LIVE_CALIBRATION=1")
    key = environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Live calibration requires an API key")
    return key


def _print_summary(summary) -> None:  # noqa: ANN001
    print(CALIBRATION_LABEL)
    print(f"verdict={summary.verdict.value}")
    print(f"generation_requests={summary.generation_requests}/6")
    for record in summary.records:
        print(
            f"condition={record['condition']}; requested_model={record['requested_model']}; "
            f"resolved_model={record['resolved_model']}; provider={record['provider']}; "
            f"status={record['status']}; http_status={record['http_status']}; "
            f"finish_reason={record['finish_reason']}; truncated={record['truncated']}; "
            f"prompt_tokens={record['prompt_tokens']}; "
            f"completion_tokens={record['completion_tokens']}; "
            f"reasoning_tokens={record['reasoning_tokens']}; "
            f"visible_completion_tokens={record['visible_completion_tokens']}; "
            f"visible_characters={record['visible_characters']}; "
            f"visible_words={record['visible_words']}; latency_ms={record['latency_ms']}; "
            f"zero_price_confirmed={record['zero_price_confirmed']}"
        )
    print("substantive_response_text_printed=no")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.live:
            summary = load_calibration_summary(args.output_root)
            if summary.generation_requests:
                _print_summary(summary)
                print("network_requests_this_invocation=0")
            else:
                plan = offline_calibration_plan()
                print(CALIBRATION_LABEL)
                for key, value in plan.items():
                    print(f"{key}={value}")
                print("substantive_response_text_printed=no")
            return 0
        if not args.confirm_live or os.environ.get("RUN_LIVE_CALIBRATION") != "1":
            require_live_gates(
                live_requested=True,
                live_confirmed=args.confirm_live,
                environ=os.environ,
            )
        load_dotenv(ROOT / ".env", override=False)
        key = require_live_gates(
            live_requested=True,
            live_confirmed=args.confirm_live,
            environ=os.environ,
        )
        summary = execute_calibration(
            provider=OpenRouterProvider(api_key=key), output_root=args.output_root
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
