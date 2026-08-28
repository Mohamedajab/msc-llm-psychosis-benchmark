"""Plan or explicitly execute the maximum 36-attempt OpenRouter technical pilot.

Normal invocation is an offline dry-run that prints the configuration-driven
plan. Generation requires ``--live``, ``--confirm-live``, ``RUN_LIVE_PILOT=1``,
and ``OPENROUTER_API_KEY``. Before generation, every exact configured ``:free``
slug is checked together; no substitute model is ever selected.
"""

# The executable-path bootstrap must precede local ``src`` imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
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
from src.provider_client import DeterministicFixtureProvider, OpenRouterProvider
from src.schemas import ContextCondition, RunHeader
from src.storage import RawRunStore, atomic_write_json

PILOT_VERSION = "technical-pilot-v1.0.0"
DEFAULT_SCRIPT_ID = "monitoring_fixed_belief_v1"
PILOT_RANDOM_SEED = 20260814
PILOT_PLANNED_TIME = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
DEFAULT_LIVE_OUTPUT_ROOT = ROOT / "data" / "raw" / "runs"
MAX_CONVERSATIONS = 6
MAX_GENERATION_CALLS = 36


class PilotPreflightError(RuntimeError):
    """Raised before generation when the bounded pilot contract is not met."""


def _configuration(script_id: str) -> tuple[Any, Any, Any, list[Any], list[Any]]:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    try:
        script = next(item for item in scripts if item.script_id == script_id)
    except StopIteration as error:
        raise PilotPreflightError(f"Unknown frozen script ID: {script_id}") from error
    if script.presentation_level.value != "fixed_belief":
        raise PilotPreflightError(
            "The technical pilot is restricted to one frozen fixed-belief script"
        )
    prefix = next((item for item in histories if item.history_id == script.history_id), None)
    if prefix is None:
        raise PilotPreflightError(
            f"Frozen prefix {script.history_id!r} was not found for {script_id}"
        )
    return script, prefix, models, scripts, histories


def _validated_model_ids(models: Any) -> dict[str, str]:
    model_ids = resolve_model_ids(models)
    if len(model_ids) > MAX_CONVERSATIONS // len(ContextCondition):
        raise PilotPreflightError(
            "Pilot configuration exceeds the persistent six-conversation cap"
        )
    for slot, model_id in model_ids.items():
        if not model_id.endswith(":free"):
            raise PilotPreflightError(
                f"{slot} must use one exact :free OpenRouter slug; received {model_id!r}"
            )
        if model_id in {"openrouter/free", "openrouter/auto"} or "latest" in model_id:
            raise PilotPreflightError(f"{slot} is not an exact stable model slug: {model_id!r}")
    return model_ids


def _ordered_cells(model_slots: Any) -> list[tuple[str, ContextCondition]]:
    cells = [
        (slot, condition)
        for slot in model_slots
        for condition in (
            ContextCondition.NO_PRELOADED_CONTEXT,
            ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
        )
    ]
    random.Random(PILOT_RANDOM_SEED).shuffle(cells)
    return cells


def _run_id(script_id: str, slot: str, condition: ContextCondition) -> str:
    return f"technical-pilot-v1_{script_id}_{slot}_{condition.value}_r1"


def _assert_pilot_shape(entries: list[dict[str, Any]], model_count: int) -> None:
    expected_conversations = model_count * len(ContextCondition)
    expected_calls = expected_conversations * 6
    calls = sum(len(entry["payloads"]) for entry in entries)
    if len(entries) != expected_conversations or calls != expected_calls:
        raise PilotPreflightError(
            "Internal pilot plan error: model/context cells or six-turn payloads are incomplete"
        )
    if expected_conversations > MAX_CONVERSATIONS or expected_calls > MAX_GENERATION_CALLS:
        raise PilotPreflightError("Pilot plan exceeds its persistent request cap")
    if len({entry["run_id"] for entry in entries}) != expected_conversations:
        raise PilotPreflightError("Internal pilot plan error: run IDs are not unique")
    cells = {(entry["model_slot"], entry["context_condition"]) for entry in entries}
    if len(cells) != expected_conversations:
        raise PilotPreflightError("Internal pilot plan error: model/context cells are incomplete")


def build_pilot_plan(
    *,
    script_id: str = DEFAULT_SCRIPT_ID,
    destination: str | Path | None = None,
) -> dict[str, Any]:
    """Build all exact payloads offline; this function cannot call OpenRouter."""

    script, prefix, models, scripts, histories = _configuration(script_id)
    model_ids = _validated_model_ids(models)
    pilot_generation = generation_for_repetition(models, 1)
    configuration_hash = configuration_bundle_hash(scripts, histories, models)
    entries: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="msc-pilot-dry-run-") as temporary:
        no_call_provider = DeterministicFixtureProvider()
        runner = ConversationRunner(no_call_provider, RawRunStore(Path(temporary) / "unused-store"))
        for execution_order, (slot, condition) in enumerate(
            _ordered_cells(model_ids), start=1
        ):
            header = create_run_header(
                study_version=PILOT_VERSION,
                run_id=_run_id(script_id, slot, condition),
                data_status="technical_pilot",
                script=script,
                condition=condition,
                model_slot=slot,
                model_id=model_ids[slot],
                repetition=1,
                generation=pilot_generation,
                configuration_version=models.version,
                configuration_hash=configuration_hash,
            ).model_copy(update={"created_at": PILOT_PLANNED_TIME})
            payloads = runner.dry_run(header=header, script=script, prefix=prefix)
            entries.append(
                {
                    "execution_order": execution_order,
                    "run_id": header.run_id,
                    "script_id": script.script_id,
                    "model_slot": slot,
                    "requested_model_id": model_ids[slot],
                    "context_condition": condition.value,
                    "repetition": 1,
                    "payloads": payloads,
                }
            )
        if no_call_provider.calls:
            raise PilotPreflightError("Dry-run unexpectedly invoked a provider")

    _assert_pilot_shape(entries, len(model_ids))
    plan = {
        "pilot_version": PILOT_VERSION,
        "status": "offline_dry_run_preflight",
        "data_status": "technical_pilot",
        "network_called": False,
        "live_execution_enabled": False,
        "script_id": script_id,
        "execution_seed": PILOT_RANDOM_SEED,
        "conversation_count": len(entries),
        "maximum_generation_calls": MAX_GENERATION_CALLS,
        "maximum_http_generation_attempts_including_retries": MAX_GENERATION_CALLS,
        "configured_models": model_ids,
        "configuration_hash": configuration_hash,
        "live_requirements": [
            "--live command-line flag",
            "--confirm-live final confirmation flag",
            "RUN_LIVE_PILOT=1 environment variable",
            "OPENROUTER_API_KEY environment variable",
            "successful exact-slug catalogue preflight for every configured model",
        ],
        "runs": entries,
    }
    if destination is not None:
        output = Path(destination)
        if output.exists():
            try:
                existing = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise FileExistsError(
                    f"Plan output exists and was not overwritten: {output}"
                ) from error
            if existing != plan:
                raise FileExistsError(f"Plan output exists with different content: {output}")
        else:
            atomic_write_json(output, plan)
    return plan


def require_live_gate(environ: Mapping[str, str] | None = None) -> str:
    """Return the key only when the two independent live gates are satisfied."""

    values = os.environ if environ is None else environ
    if values.get("RUN_LIVE_PILOT") != "1":
        raise PilotPreflightError(
            "Live pilot blocked: set RUN_LIVE_PILOT=1 as well as passing --live"
        )
    api_key = values.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise PilotPreflightError(
            "Live pilot blocked: OPENROUTER_API_KEY is not set; no calls were made"
        )
    return api_key


def _resume_or_new_header(store: RawRunStore, candidate: RunHeader) -> RunHeader:
    path = store.run_directory(candidate.run_id) / "run.json"
    if not path.exists():
        return candidate
    existing = RunHeader.model_validate_json(path.read_text(encoding="utf-8"))
    if existing.model_dump(exclude={"created_at"}) != candidate.model_dump(exclude={"created_at"}):
        raise PilotPreflightError(
            f"Resume blocked: immutable metadata changed for {candidate.run_id}"
        )
    return existing


def execute_live_pilot(
    *,
    output_root: str | Path = DEFAULT_LIVE_OUTPUT_ROOT,
    script_id: str = DEFAULT_SCRIPT_ID,
    live_requested: bool = False,
    live_confirmed: bool = False,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
) -> list[Any]:
    """Run/resume the bounded pilot after gates and catalogue checks pass."""

    if not live_requested:
        raise PilotPreflightError(
            "Live pilot blocked: an explicit --live-equivalent request is required"
        )
    if not live_confirmed:
        raise PilotPreflightError(
            "Live pilot blocked: a final --confirm-live-equivalent confirmation is required"
        )
    api_key = require_live_gate(environ)
    script, prefix, models, scripts, histories = _configuration(script_id)
    model_ids = _validated_model_ids(models)
    pilot_generation = generation_for_repetition(models, 1)
    configuration_hash = configuration_bundle_hash(scripts, histories, models)

    provider = provider_factory(api_key=api_key)
    store = RawRunStore(output_root)
    records: list[Any] = []
    cells = _ordered_cells(model_ids)
    if len(cells) > MAX_CONVERSATIONS:
        raise PilotPreflightError("Pilot cell count exceeds the six-conversation cap")
    run_ids = [_run_id(script_id, slot, condition) for slot, condition in cells]
    prior_attempts = _stored_generation_attempts(store, run_ids)
    incomplete = [
        run_id
        for run_id in run_ids
        if not (store.run_directory(run_id) / "turn-06-success.json").is_file()
    ]
    if incomplete and prior_attempts >= MAX_GENERATION_CALLS:
        raise PilotPreflightError(
            "Live pilot blocked: the persistent 36-attempt generation cap is exhausted"
        )
    set_budget = getattr(provider, "set_request_attempt_budget", None)
    if incomplete and callable(set_budget):
        set_budget(MAX_GENERATION_CALLS - prior_attempts)
    # One catalogue response must contain every exact slug before generation.
    try:
        provider.validate_exact_models(
            tuple(model_ids.values()),
            timeout_seconds=min(20, models.generation.timeout_seconds),
        )
    except (OSError, RuntimeError, ValueError) as error:
        _store_preflight_failure(output_root, model_ids, error, api_key)
        raise PilotPreflightError(
            "Live pilot stopped before generation because exact-model preflight failed; "
            "a technical failure record was stored"
        ) from error
    for slot, condition in cells:
        candidate = create_run_header(
            study_version=PILOT_VERSION,
            run_id=_run_id(script_id, slot, condition),
            data_status="technical_pilot",
            script=script,
            condition=condition,
            model_slot=slot,
            model_id=model_ids[slot],
            repetition=1,
            generation=pilot_generation,
            configuration_version=models.version,
            configuration_hash=configuration_hash,
        )
        header = _resume_or_new_header(store, candidate)
        record = ConversationRunner(provider, store).run_or_resume(
            header=header, script=script, prefix=prefix
        )
        records.append(record)
    if len(records) != len(cells):
        raise PilotPreflightError("Pilot execution exceeded or missed the run cap")
    return records


def _stored_generation_attempts(store: RawRunStore, run_ids: list[str]) -> int:
    """Count persisted POST attempts, including retries, across resumptions."""

    attempts = 0
    for run_id in run_ids:
        if not (store.run_directory(run_id) / "run.json").is_file():
            continue
        record = store.load(run_id)
        attempts += sum(event.result.retry_count + 1 for event in record.turns)
        attempts += sum(event.result.retry_count + 1 for event in record.errors)
    return attempts


def _store_preflight_failure(
    output_root: str | Path,
    model_ids: Mapping[str, str],
    error: Exception,
    api_key: str,
) -> Path:
    """Persist a non-response technical failure without storing credentials."""

    timestamp = datetime.now(UTC)
    message = str(error).replace(api_key, "[REDACTED]")[:500]
    destination = (
        Path(output_root)
        / "technical-pilot-preflight-failures"
        / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json"
    )
    return atomic_write_json(
        destination,
        {
            "pilot_version": PILOT_VERSION,
            "status": "technical_failure",
            "stage": "exact_model_catalogue_preflight",
            "timestamp": timestamp.isoformat(),
            "requested_model_ids": dict(model_ids),
            "generation_requests_made": 0,
            "error_type": type(error).__name__,
            "error_message": message,
        },
    )


def _print_plan_summary(plan: dict[str, Any]) -> None:
    print("OFFLINE DRY-RUN / PREFLIGHT ONLY - NO NETWORK CALLS")
    print(
        f"{plan['conversation_count']} conversations; "
        f"maximum {plan['maximum_generation_calls']} generation calls"
    )
    for entry in plan["runs"]:
        print(
            f"{entry['execution_order']}. {entry['model_slot']} | "
            f"{entry['context_condition']} | {entry['requested_model_id']}"
        )
    print(
        "To execute, explicitly pass --live --confirm-live and set "
        "RUN_LIVE_PILOT=1 plus the API key."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline pilot preflight by default; live execution has four gates."
    )
    parser.add_argument("--live", action="store_true", help="Request live execution")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Final confirmation that generation requests may begin",
    )
    parser.add_argument("--script-id", default=DEFAULT_SCRIPT_ID)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_LIVE_OUTPUT_ROOT)
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="Optional path for the exact offline dry-run payload plan",
    )
    arguments = parser.parse_args(argv)

    try:
        if not arguments.live:
            plan = build_pilot_plan(
                script_id=arguments.script_id, destination=arguments.plan_output
            )
            _print_plan_summary(plan)
            return 0
        load_dotenv(ROOT / ".env", override=False)
        records = execute_live_pilot(
            output_root=arguments.output_root,
            script_id=arguments.script_id,
            live_requested=True,
            live_confirmed=arguments.confirm_live,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    completed = sum(len(record.turns) == 6 for record in records)
    print("TECHNICAL PILOT - NOT DISSERTATION RESULTS")
    print(f"Completed/resumed {completed}/{len(records)} conversations")
    print(arguments.output_root.resolve())
    return 0 if completed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
