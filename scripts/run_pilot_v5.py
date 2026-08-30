"""Offline-by-default Pilot V5 for generation-v3 endpoint qualification."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import (
    configuration_bundle_hash,
    generation_for_repetition,
    load_histories,
    load_models,
    load_scripts,
    resolve_model_ids,
)
from src.conversation_runner import ConversationRunner, create_run_header
from src.pilot_qualification import assess_pilot_v5
from src.provider_client import DeterministicFixtureProvider, OpenRouterProvider
from src.schemas import ContextCondition, ManifestRow, RunStatus
from src.storage import RawRunStore, atomic_write_json
from src.study_execution import (
    build_execution_summary,
    execute_manifest_rows,
    print_execution_summary,
    stored_http_attempts,
)

PILOT_VERSION = "technical-pilot-v5.0.0"
PILOT_NAMESPACE = "technical-pilot-v5"
DEFAULT_SCRIPT_ID = "monitoring_fixed_belief_v1"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "raw" / "runs"
ARCHIVED_MODELS_PATH = ROOT / "config" / "archive" / "models-study-v2-generation-v3-nemotron.yaml"
PLANNED_CONVERSATIONS = 4
PLANNED_RESPONSE_SLOTS = 24
FAILURE_ATTEMPT_ALLOWANCE = 8
MAX_HTTP_ATTEMPTS = 32
MINIMUM_REQUEST_INTERVAL_SECONDS = 5.0
PILOT_RANDOM_SEED = 20260814
PLANNED_AT = datetime(2026, 8, 29, tzinfo=UTC)


class PilotV5PreflightError(RuntimeError):
    """A Pilot V5 protocol or live-safety invariant was not satisfied."""


def _configuration() -> tuple[Any, Any, Any, list[Any], list[Any]]:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ARCHIVED_MODELS_PATH)
    if models.generation.version != "generation-v3" or models.generation.max_tokens != 1024:
        raise PilotV5PreflightError("Pilot V5 requires frozen generation-v3 at 1024 tokens")
    script = next((item for item in scripts if item.script_id == DEFAULT_SCRIPT_ID), None)
    if script is None or script.presentation_level.value != "fixed_belief":
        raise PilotV5PreflightError("Pilot V5 requires the frozen fixed-belief scenario")
    prefix = next((item for item in histories if item.history_id == script.history_id), None)
    if prefix is None:
        raise PilotV5PreflightError("Pilot V5 frozen history is unavailable")
    model_ids = resolve_model_ids(models)
    if set(model_ids) != {"model_minimax", "model_nemotron"}:
        raise PilotV5PreflightError("Pilot V5 requires the two exact Study V2 model slots")
    return script, prefix, models, scripts, histories


def pilot_rows() -> list[ManifestRow]:
    script, _, models, _, _ = _configuration()
    model_ids = resolve_model_ids(models)
    cells = [(slot, condition) for slot in model_ids for condition in ContextCondition]
    random.Random(PILOT_RANDOM_SEED).shuffle(cells)
    rows = [
        ManifestRow(
            study_version=PILOT_VERSION,
            run_id=(f"{PILOT_NAMESPACE}_{script.script_id}_{slot}_{condition.value}_r1"),
            script_id=script.script_id,
            theme=script.theme,
            presentation_level=script.presentation_level,
            model_slot=slot,
            requested_model_id=model_ids[slot],
            context_condition=condition,
            repetition=1,
            generation_config_version=models.generation.version,
            planned_seed=models.repetition_seeds[1],
            execution_order=order,
            status=RunStatus.PLANNED,
        )
        for order, (slot, condition) in enumerate(cells, start=1)
    ]
    if len(rows) != PLANNED_CONVERSATIONS or len(rows) * 6 != PLANNED_RESPONSE_SLOTS:
        raise PilotV5PreflightError("Pilot V5 shape is not 4 conversations / 24 slots")
    return rows


def build_offline_plan() -> dict[str, Any]:
    script, prefix, models, scripts, histories = _configuration()
    rows = pilot_rows()
    generation = generation_for_repetition(models, 1)
    configuration_hash = configuration_bundle_hash(scripts, histories, models)
    with tempfile.TemporaryDirectory(prefix="pilot-v5-offline-") as temporary:
        provider = DeterministicFixtureProvider()
        runner = ConversationRunner(provider, RawRunStore(temporary))
        runs = []
        for row in rows:
            header = create_run_header(
                study_version=PILOT_VERSION,
                run_id=row.run_id,
                data_status="technical_pilot",
                script=script,
                condition=row.context_condition,
                model_slot=row.model_slot,
                model_id=row.requested_model_id,
                repetition=1,
                generation=generation,
                configuration_version=models.version,
                configuration_hash=configuration_hash,
            ).model_copy(update={"created_at": PLANNED_AT})
            payloads = runner.dry_run(header=header, script=script, prefix=prefix)
            runs.append(
                {
                    "execution_order": row.execution_order,
                    "run_id": row.run_id,
                    "model_slot": row.model_slot,
                    "requested_model_id": row.requested_model_id,
                    "context_condition": row.context_condition.value,
                    "payload_count": len(payloads),
                }
            )
        if provider.calls:
            raise PilotV5PreflightError("Offline Pilot V5 unexpectedly called a provider")
    return {
        "pilot_version": PILOT_VERSION,
        "generation_version": models.generation.version,
        "max_tokens": models.generation.max_tokens,
        "status": "offline_preflight",
        "network_called": False,
        "planned_conversations": PLANNED_CONVERSATIONS,
        "planned_response_slots": PLANNED_RESPONSE_SLOTS,
        "failure_attempt_allowance": FAILURE_ATTEMPT_ALLOWANCE,
        "maximum_http_attempts": MAX_HTTP_ATTEMPTS,
        "minimum_request_interval_seconds": MINIMUM_REQUEST_INTERVAL_SECONDS,
        "configuration_hash": configuration_hash,
        "runs": runs,
    }


def require_live_gate(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    if values.get("RUN_LIVE_PILOT") != "1":
        raise PilotV5PreflightError("Live Pilot V5 requires RUN_LIVE_PILOT=1")
    key = values.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise PilotV5PreflightError("Live Pilot V5 requires an API key; no calls were made")
    return key


def _store_preflight_failure(
    output_root: Path, model_ids: dict[str, str], error: Exception, key: str
) -> Path:
    timestamp = datetime.now(UTC)
    return atomic_write_json(
        output_root
        / f"{PILOT_NAMESPACE}-preflight-failures"
        / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json",
        {
            "pilot_version": PILOT_VERSION,
            "record_type": "TECHNICAL PILOT PREFLIGHT - NOT RESEARCH DATA",
            "timestamp": timestamp.isoformat(),
            "requested_models": model_ids,
            "generation_requests_made": 0,
            "error_type": type(error).__name__,
            "error_message": str(error).replace(key, "[REDACTED]")[:500],
        },
    )


def _qualified_summary(store: RawRunStore, rows: list[ManifestRow]) -> dict[str, Any]:
    summary = build_execution_summary(
        planned_rows=rows, store=store, maximum_total_attempts=MAX_HTTP_ATTEMPTS
    )
    qualification = assess_pilot_v5(output_root=store.root, persist=True)
    summary["pilot_v5_qualification"] = qualification.verdict.value
    summary["qualification_failed_criteria"] = list(qualification.failed_criteria)
    summary["qualification_can_still_pass"] = qualification.verdict.value in {
        "PASS",
        "INCOMPLETE",
    }
    summary["resume_would_perform_useful_work"] = (
        summary["missing_response_slots"] > 0 and summary["next_execution_order"] is not None
    )
    return summary


def execute_live_pilot_v5(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    live_requested: bool = False,
    live_confirmed: bool = False,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
    request_interval_seconds: float = MINIMUM_REQUEST_INTERVAL_SECONDS,
) -> dict[str, Any]:
    if not live_requested or not live_confirmed:
        raise PilotV5PreflightError("Live Pilot V5 requires --live and --confirm-live")
    if request_interval_seconds < MINIMUM_REQUEST_INTERVAL_SECONDS:
        raise PilotV5PreflightError("Pilot V5 pacing must be at least five seconds")
    key = require_live_gate(environ)
    _, _, models, scripts, histories = _configuration()
    rows = pilot_rows()
    model_ids = resolve_model_ids(models)
    store = RawRunStore(output_root)
    prior_attempts = stored_http_attempts(store, [row.run_id for row in rows])
    missing = PLANNED_RESPONSE_SLOTS - sum(
        len(store.successful_turns(row.run_id))
        if (store.run_directory(row.run_id) / "run.json").is_file()
        else 0
        for row in rows
    )
    remaining = MAX_HTTP_ATTEMPTS - prior_attempts
    if missing == 0:
        return _qualified_summary(store, rows)
    if remaining <= 0 or remaining < missing:
        raise PilotV5PreflightError(
            "Pilot V5 has insufficient remaining allowance to complete its missing slots"
        )
    provider = provider_factory(api_key=key)
    provider.set_retry_rate_limits(False)
    provider.set_minimum_request_interval(request_interval_seconds)
    provider.set_provider_routing(models.provider_routing)
    try:
        provider.validate_exact_models_strict(
            tuple(model_ids.values()),
            minimum_context_tokens=models.provider_routing.minimum_context_tokens,
            timeout_seconds=min(20, models.generation.timeout_seconds),
        )
    except (OSError, RuntimeError, ValueError) as error:
        path = _store_preflight_failure(output_root, model_ids, error, key)
        raise PilotV5PreflightError(
            f"Pilot V5 catalogue preflight failed before POST; record: {path}"
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
    return _qualified_summary(store, rows)


def _print_offline(plan: dict[str, Any]) -> None:
    print("PILOT V5 OFFLINE PREFLIGHT - NO NETWORK CALL OCCURRED")
    print(
        f"generation={plan['generation_version']}; max_tokens={plan['max_tokens']}; "
        f"{plan['planned_conversations']} conversations; "
        f"{plan['planned_response_slots']} planned successful responses; "
        f"maximum {plan['maximum_http_attempts']} HTTP attempts"
    )
    for run in plan["runs"]:
        print(
            f"{run['execution_order']}. {run['model_slot']} | "
            f"{run['context_condition']} | {run['requested_model_id']}"
        )
    print("Live execution requires --live --confirm-live, RUN_LIVE_PILOT=1 and the API key.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--request-interval-seconds", type=float, default=MINIMUM_REQUEST_INTERVAL_SECONDS
    )
    args = parser.parse_args(argv)
    try:
        if not args.live:
            _print_offline(build_offline_plan())
            return 0
        load_dotenv(ROOT / ".env", override=False)
        summary = execute_live_pilot_v5(
            output_root=args.output_root,
            live_requested=True,
            live_confirmed=args.confirm_live,
            request_interval_seconds=args.request_interval_seconds,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_execution_summary("TECHNICAL PILOT V5 - NOT RESEARCH RESULTS", summary)
    print(f"Pilot V5 qualification: {summary['pilot_v5_qualification']}")
    print(f"Qualification failures: {summary['qualification_failed_criteria']}")
    print(
        "Qualification can still become PASS: "
        f"{'yes' if summary['qualification_can_still_pass'] else 'no'}"
    )
    print(
        "Resume would perform useful work: "
        f"{'yes' if summary['resume_would_perform_useful_work'] else 'no'}"
    )
    return 0 if summary["pilot_v5_qualification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
