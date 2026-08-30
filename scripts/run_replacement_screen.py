"""Run one explicitly supplied replacement candidate screen; offline by default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.provider_client import OpenRouterProvider
from src.replacement_screening import (
    MAX_HTTP_ATTEMPTS,
    MINIMUM_CONTEXT_TOKENS,
    MINIMUM_REQUEST_INTERVAL_SECONDS,
    SCREEN_LABEL,
    SCREEN_VERSION,
    ReplacementScreenAssessment,
    ReplacementScreenError,
    ScreenVerdict,
    assess_replacement_screen,
    build_catalogue_evidence,
    build_offline_screen_plan,
    candidate_store_root,
    execute_screen_conversations,
    persist_catalogue_evidence,
    print_safe_assessment,
    screen_rows,
    stored_screen_attempts,
    validate_candidate_model_id,
)
from src.schemas import ProviderRoutingPolicy
from src.storage import RawRunStore

DEFAULT_OUTPUT_ROOT = ROOT / "data" / "private" / SCREEN_VERSION
DEFAULT_CATALOGUE_ROOT = ROOT / "data" / "private"


def require_live_gates(
    *,
    live_requested: bool,
    live_confirmed: bool,
    environ: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    if not live_requested:
        raise ReplacementScreenError("Live replacement screen requires --live")
    if not live_confirmed:
        raise ReplacementScreenError("Live replacement screen requires --confirm-live")
    if values.get("RUN_LIVE_SCREEN") != "1":
        raise ReplacementScreenError("Live replacement screen requires RUN_LIVE_SCREEN=1")
    key = values.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ReplacementScreenError("Live replacement screen requires an API key")
    return key


def execute_live_screen(
    *,
    candidate_model_id: str,
    live_requested: bool,
    live_confirmed: bool,
    environ: Mapping[str, str] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    catalogue_root: str | Path = DEFAULT_CATALOGUE_ROOT,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
    request_interval_seconds: float = MINIMUM_REQUEST_INTERVAL_SECONDS,
    repository_root: str | Path = ROOT,
) -> ReplacementScreenAssessment:
    candidate = validate_candidate_model_id(candidate_model_id)
    if request_interval_seconds < MINIMUM_REQUEST_INTERVAL_SECONDS:
        raise ReplacementScreenError("Replacement-screen pacing must be at least five seconds")
    key = require_live_gates(
        live_requested=live_requested,
        live_confirmed=live_confirmed,
        environ=environ,
    )
    rows = screen_rows(candidate, repository_root)
    store = RawRunStore(candidate_store_root(output_root, candidate))
    prior_attempts = stored_screen_attempts(store, rows)
    successful = sum(
        len(store.successful_turns(row.run_id))
        if (store.run_directory(row.run_id) / "run.json").is_file()
        else 0
        for row in rows
    )
    missing = 12 - successful
    remaining = MAX_HTTP_ATTEMPTS - prior_attempts
    if missing == 0:
        return assess_replacement_screen(
            candidate_model_id=candidate,
            repository_root=repository_root,
            output_root=output_root,
            persist=True,
        )
    if remaining <= 0 or remaining < missing:
        raise ReplacementScreenError(
            "Replacement screen has insufficient persisted attempt allowance to complete"
        )

    provider = provider_factory(api_key=key)
    provider.set_retry_rate_limits(False)
    provider.set_minimum_request_interval(request_interval_seconds)
    provider.set_provider_routing(
        ProviderRoutingPolicy(
            version="replacement-screen-routing-v1",
            allow_fallbacks=False,
            require_parameters=True,
            pinned_providers={},
            minimum_context_tokens=MINIMUM_CONTEXT_TOKENS,
        )
    )
    try:
        entry = provider.get_exact_model_catalogue_entry(candidate, timeout_seconds=20)
        catalogue_record = build_catalogue_evidence([entry], retrieved_at=datetime.now(UTC))
        persist_catalogue_evidence(catalogue_record, catalogue_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ReplacementScreenError(
            "Candidate catalogue preflight failed before any generation POST"
        ) from error
    evaluations = catalogue_record["candidate_evaluations"]
    if len(evaluations) != 1 or evaluations[0]["exact_model_id"] != candidate:
        raise ReplacementScreenError("Candidate catalogue evidence does not match exact model ID")
    if not evaluations[0]["eligible"]:
        reasons = ",".join(evaluations[0]["rejection_reasons"])
        raise ReplacementScreenError(f"Candidate is technically ineligible: {reasons}")

    execute_screen_conversations(
        candidate_model_id=candidate,
        repository_root=repository_root,
        output_root=output_root,
        provider=provider,
        maximum_http_attempts=remaining,
    )
    return assess_replacement_screen(
        candidate_model_id=candidate,
        repository_root=repository_root,
        output_root=output_root,
        persist=True,
    )


def print_offline_plan(plan: Mapping[str, Any]) -> None:
    print(SCREEN_LABEL)
    print("screen_status=NOT_RUN")
    print(f"candidate_model_id={plan['candidate_model_id']}")
    print(f"catalogue_status={plan['catalogue_status']}")
    print(f"planned_context_cells={plan['planned_conversations']}")
    print(f"planned_response_slots={plan['planned_response_slots']}")
    print(f"generation={plan['generation_version']}; completion_envelope={plan['max_tokens']}")
    print(f"maximum_http_attempts={plan['maximum_http_attempts']}")
    print(f"minimum_post_start_interval_seconds={plan['minimum_request_interval_seconds']}")
    print("network_requests=0")
    print("No evidence was written. Live screening requires explicit independent gates.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-model-id", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--catalogue-root", type=Path, default=DEFAULT_CATALOGUE_ROOT)
    parser.add_argument(
        "--request-interval-seconds", type=float, default=MINIMUM_REQUEST_INTERVAL_SECONDS
    )
    args = parser.parse_args(argv)
    try:
        if not args.live:
            print_offline_plan(build_offline_screen_plan(args.candidate_model_id, ROOT))
            return 0
        if not args.confirm_live or os.environ.get("RUN_LIVE_SCREEN") != "1":
            require_live_gates(
                live_requested=True,
                live_confirmed=args.confirm_live,
                environ=os.environ,
            )
        load_dotenv(ROOT / ".env", override=False)
        assessment = execute_live_screen(
            candidate_model_id=args.candidate_model_id,
            live_requested=True,
            live_confirmed=args.confirm_live,
            output_root=args.output_root,
            catalogue_root=args.catalogue_root,
            request_interval_seconds=args.request_interval_seconds,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_safe_assessment(assessment)
    return 0 if assessment.verdict == ScreenVerdict.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
