"""Run the selection-bound final-pair Pilot V6; offline by default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import resolve_model_ids
from src.pilot_v6 import (
    MAX_HTTP_ATTEMPTS,
    MINIMUM_REQUEST_INTERVAL_SECONDS,
    PILOT_V6_VERSION,
    PLANNED_RESPONSE_SLOTS,
    PilotV6Error,
    PilotV6Verdict,
    assess_pilot_v6,
    build_pilot_v6_offline_plan,
    load_pilot_v6_configuration,
    pilot_v6_rows,
    print_safe_pilot_v6_assessment,
)
from src.provider_client import OpenRouterProvider
from src.replacement_screening import SCREEN_VERSION
from src.replacement_selection import selection_record_hash
from src.storage import RawRunStore, atomic_write_json
from src.study_execution import execute_manifest_rows, stored_http_attempts

DEFAULT_SCREEN_ROOT = ROOT / "data" / "private" / SCREEN_VERSION
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "private" / PILOT_V6_VERSION
DEFAULT_ASSESSMENT_ROOT = ROOT / "data" / "private" / "pilot-v6-qualification"
DEFAULT_PREFLIGHT_ROOT = ROOT / "data" / "private" / "pilot-v6-preflight-failures"


def require_live_gates(
    *,
    live_requested: bool,
    live_confirmed: bool,
    environ: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    if not live_requested:
        raise PilotV6Error("Live Pilot V6 requires --live")
    if not live_confirmed:
        raise PilotV6Error("Live Pilot V6 requires --confirm-live")
    if values.get("RUN_LIVE_PILOT_V6") != "1":
        raise PilotV6Error("Live Pilot V6 requires RUN_LIVE_PILOT_V6=1")
    key = values.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise PilotV6Error("Live Pilot V6 requires an API key")
    return key


def _store_catalogue_failure(
    *,
    root: str | Path,
    model_ids: dict[str, str],
    selection_hash: str,
    error: Exception,
) -> Path:
    timestamp = datetime.now(UTC)
    return atomic_write_json(
        Path(root) / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json",
        {
            "pilot_version": PILOT_V6_VERSION,
            "record_type": "PILOT V6 PREFLIGHT FAILURE - NOT RESEARCH DATA",
            "timestamp": timestamp.isoformat(),
            "requested_models": model_ids,
            "selection_record_hash": selection_hash,
            "generation_requests_made": 0,
            "error_type": type(error).__name__,
        },
    )


def execute_live_pilot_v6(
    *,
    selection_record_path: str | Path | None,
    catalogue_record_path: str | Path | None,
    screen_output_root: str | Path = DEFAULT_SCREEN_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    assessment_root: str | Path = DEFAULT_ASSESSMENT_ROOT,
    preflight_root: str | Path = DEFAULT_PREFLIGHT_ROOT,
    live_requested: bool = False,
    live_confirmed: bool = False,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
    request_interval_seconds: float = MINIMUM_REQUEST_INTERVAL_SECONDS,
    repository_root: str | Path = ROOT,
):
    if selection_record_path is None or catalogue_record_path is None:
        raise PilotV6Error("Pilot V6 is NOT_CONFIGURED without a valid replacement selection")
    if request_interval_seconds < MINIMUM_REQUEST_INTERVAL_SECONDS:
        raise PilotV6Error("Pilot V6 request pacing must be at least five seconds")
    selection, _, _, models, scripts, histories = load_pilot_v6_configuration(
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        repository_root=repository_root,
    )
    key = require_live_gates(
        live_requested=live_requested,
        live_confirmed=live_confirmed,
        environ=environ,
    )
    rows = pilot_v6_rows(
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        repository_root=repository_root,
    )
    store = RawRunStore(output_root)
    prior_attempts = stored_http_attempts(store, [row.run_id for row in rows])
    successful = sum(
        len(store.successful_turns(row.run_id))
        if (store.run_directory(row.run_id) / "run.json").is_file()
        else 0
        for row in rows
    )
    missing = PLANNED_RESPONSE_SLOTS - successful
    remaining = MAX_HTTP_ATTEMPTS - prior_attempts
    if missing == 0:
        return assess_pilot_v6(
            selection_record_path=selection_record_path,
            catalogue_record_path=catalogue_record_path,
            screen_output_root=screen_output_root,
            pilot_output_root=output_root,
            repository_root=repository_root,
            assessment_root=assessment_root,
            persist=True,
        )
    if remaining <= 0 or remaining < missing:
        raise PilotV6Error("Pilot V6 lacks sufficient persisted attempts to finish")
    provider = provider_factory(api_key=key)
    provider.set_retry_rate_limits(False)
    provider.set_minimum_request_interval(request_interval_seconds)
    provider.set_provider_routing(models.provider_routing)
    model_ids = resolve_model_ids(models)
    try:
        provider.validate_exact_models_strict(
            tuple(model_ids.values()),
            minimum_context_tokens=models.provider_routing.minimum_context_tokens,
            timeout_seconds=min(20, models.generation.timeout_seconds),
        )
    except (OSError, RuntimeError, ValueError) as error:
        path = _store_catalogue_failure(
            root=preflight_root,
            model_ids=model_ids,
            selection_hash=selection_record_hash(selection),
            error=error,
        )
        raise PilotV6Error(
            f"Pilot V6 catalogue qualification failed before POST; record={path}"
        ) from error
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=provider,
        store=store,
        data_status="technical_pilot",
        maximum_http_attempts=remaining,
    )
    return assess_pilot_v6(
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        pilot_output_root=output_root,
        repository_root=repository_root,
        assessment_root=assessment_root,
        persist=True,
    )


def _print_offline(plan: dict[str, Any]) -> None:
    print("PILOT V6 OFFLINE PREFLIGHT - NO NETWORK CALL OCCURRED")
    print(f"pilot_v6={plan['status']}")
    if plan["status"] == PilotV6Verdict.NOT_CONFIGURED.value:
        print(f"blocker={plan['blocker']}")
        print("network_requests=0")
        return
    print(f"replacement_model={plan['selected_replacement_model_id']}")
    print(
        f"generation={plan['generation_version']}; max_tokens={plan['max_tokens']}; "
        f"conversations={plan['planned_conversations']}; "
        f"response_slots={plan['planned_response_slots']}; "
        f"maximum_http_attempts={plan['maximum_http_attempts']}"
    )
    print("network_requests=0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-record", type=Path)
    parser.add_argument("--catalogue-record", type=Path)
    parser.add_argument("--screen-output-root", type=Path, default=DEFAULT_SCREEN_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--assessment-root", type=Path, default=DEFAULT_ASSESSMENT_ROOT)
    parser.add_argument("--preflight-root", type=Path, default=DEFAULT_PREFLIGHT_ROOT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument(
        "--request-interval-seconds", type=float, default=MINIMUM_REQUEST_INTERVAL_SECONDS
    )
    args = parser.parse_args(argv)
    try:
        if not args.live:
            _print_offline(
                build_pilot_v6_offline_plan(
                    selection_record_path=args.selection_record,
                    catalogue_record_path=args.catalogue_record,
                    screen_output_root=args.screen_output_root,
                    repository_root=ROOT,
                )
            )
            return 0
        if not args.confirm_live or os.environ.get("RUN_LIVE_PILOT_V6") != "1":
            require_live_gates(
                live_requested=True,
                live_confirmed=args.confirm_live,
                environ=os.environ,
            )
        load_dotenv(ROOT / ".env", override=False)
        assessment = execute_live_pilot_v6(
            selection_record_path=args.selection_record,
            catalogue_record_path=args.catalogue_record,
            screen_output_root=args.screen_output_root,
            output_root=args.output_root,
            assessment_root=args.assessment_root,
            preflight_root=args.preflight_root,
            live_requested=True,
            live_confirmed=args.confirm_live,
            request_interval_seconds=args.request_interval_seconds,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_safe_pilot_v6_assessment(assessment)
    return 0 if assessment.verdict == PilotV6Verdict.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
