"""Safely screen one fixed free OpenRouter endpoint with one generation attempt."""

# The executable-path bootstrap must precede local ``src`` imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import generation_for_repetition, load_models, load_scripts
from src.conversation_runner import payload_hash
from src.payloads import build_target_messages
from src.provider_client import OpenRouterProvider
from src.schemas import ContextCondition, ObservationStatus, ProviderResult
from src.storage import atomic_write_json

SCREEN_VERSION = "technical-endpoint-screen-v1"
SCREEN_LABEL = "TECHNICAL ENDPOINT SCREEN - NOT RESEARCH DATA"
SCREEN_NAMESPACE = (
    "technical-endpoint-screen-v1_nvidia-nemotron-super"
)
TARGET_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b:free"
SCRIPT_ID = "monitoring_fixed_belief_v1"
MINIMUM_CONTEXT_LENGTH = 16_384
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "raw" / "screens"


class ScreeningPreflightError(RuntimeError):
    """Raised when a screen cannot safely make its one generation attempt."""


def _screen_inputs() -> tuple[Any, Any, tuple[Any, ...]]:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    script = next(item for item in scripts if item.script_id == SCRIPT_ID)
    models = load_models(ROOT / "config" / "models.yaml")
    generation = generation_for_repetition(models, 1).model_copy(
        update={"max_retries": 0}
    )
    messages = build_target_messages(
        condition=ContextCondition.NO_PRELOADED_CONTEXT,
        prefix=None,
        completed_exchanges=(),
        current_user_message=script.turns[0],
    )
    return script, generation, messages


def build_offline_plan() -> dict[str, Any]:
    """Describe the fixed screen without constructing a network provider."""

    script, generation, messages = _screen_inputs()
    return {
        "label": SCREEN_LABEL,
        "screen_version": SCREEN_VERSION,
        "network_called": False,
        "requested_model_id": TARGET_MODEL_ID,
        "script_id": script.script_id,
        "turn_number": 1,
        "context_condition": ContextCondition.NO_PRELOADED_CONTEXT.value,
        "message_count": len(messages),
        "request_parameters": generation.request_parameters(),
        "maximum_generation_attempts": 1,
        "max_retries": generation.max_retries,
        "fallback_enabled": False,
    }


def validate_catalogue_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless the exact endpoint is free and protocol-compatible."""

    model_id = entry.get("id")
    if model_id != TARGET_MODEL_ID:
        raise ScreeningPreflightError(
            f"Exact NVIDIA screening slug required; received {model_id!r}"
        )
    if model_id in {"openrouter/free", "openrouter/auto"} or "latest" in str(model_id):
        raise ScreeningPreflightError("Routers, aliases and fallback endpoints are forbidden")

    pricing = entry.get("pricing")
    if not isinstance(pricing, Mapping):
        raise ScreeningPreflightError("Catalogue entry has no inspectable pricing")
    try:
        prompt_price = Decimal(str(pricing.get("prompt")))
        completion_price = Decimal(str(pricing.get("completion")))
    except (InvalidOperation, ValueError) as error:
        raise ScreeningPreflightError("Catalogue pricing is not numeric") from error
    if prompt_price != 0 or completion_price != 0:
        raise ScreeningPreflightError("Paid prompt or completion pricing is prohibited")

    architecture = entry.get("architecture")
    if not isinstance(architecture, Mapping):
        raise ScreeningPreflightError("Catalogue entry has no inspectable architecture")
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []
    if "text" not in input_modalities or "text" not in output_modalities:
        raise ScreeningPreflightError("Endpoint must accept text and return text")

    supported = entry.get("supported_parameters") or []
    if "seed" not in supported:
        raise ScreeningPreflightError("Endpoint does not advertise seed support")
    context_length = entry.get("context_length")
    if not isinstance(context_length, int) or context_length < MINIMUM_CONTEXT_LENGTH:
        raise ScreeningPreflightError(
            f"Endpoint context must be at least {MINIMUM_CONTEXT_LENGTH} tokens"
        )
    return {
        "exact_slug_exists": True,
        "prompt_price": str(prompt_price),
        "completion_price": str(completion_price),
        "text_input": True,
        "text_output": True,
        "seed_supported": True,
        "context_length": context_length,
    }


def require_live_gate(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    if values.get("RUN_LIVE_PILOT") != "1":
        raise ScreeningPreflightError("Live screen blocked: RUN_LIVE_PILOT must be 1")
    api_key = values.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ScreeningPreflightError("Live screen blocked: API key is unavailable")
    return api_key


def _record_path(output_root: str | Path, suffix: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        Path(output_root)
        / SCREEN_NAMESPACE
        / f"{timestamp}-{uuid.uuid4().hex}-{suffix}.json"
    )


def _store_preflight_failure(
    output_root: str | Path, error: Exception, api_key: str
) -> Path:
    message = str(error).replace(api_key, "[REDACTED]")[:500]
    destination = _record_path(output_root, "preflight-failure")
    return atomic_write_json(
        destination,
        {
            "label": SCREEN_LABEL,
            "screen_version": SCREEN_VERSION,
            "namespace": SCREEN_NAMESPACE,
            "status": "preflight_failure",
            "timestamp": datetime.now(UTC).isoformat(),
            "requested_model_id": TARGET_MODEL_ID,
            "generation_attempts": 0,
            "error_type": type(error).__name__,
            "error_message": message,
        },
    )


def execute_live_screen(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    live_requested: bool = False,
    live_confirmed: bool = False,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
) -> tuple[dict[str, Any], Path]:
    """Catalogue-check and make at most one exact generation attempt."""

    if not live_requested:
        raise ScreeningPreflightError("Live screen blocked: pass --live")
    if not live_confirmed:
        raise ScreeningPreflightError("Live screen blocked: pass --confirm-live")
    api_key = require_live_gate(environ)
    script, generation, messages = _screen_inputs()
    provider = provider_factory(api_key=api_key)
    provider.set_request_attempt_budget(1)
    provider.set_retry_rate_limits(False)

    try:
        entry = provider.get_exact_model_catalogue_entry(
            TARGET_MODEL_ID, timeout_seconds=min(20, generation.timeout_seconds)
        )
        catalogue = validate_catalogue_entry(entry)
    except (OSError, RuntimeError, ValueError) as error:
        path = _store_preflight_failure(output_root, error, api_key)
        raise ScreeningPreflightError(
            f"Catalogue preflight failed; zero generation requests; record={path}"
        ) from error

    parameters = generation.request_parameters()
    digest = payload_hash(
        model_id=TARGET_MODEL_ID,
        messages=messages,
        parameters=parameters,
    )
    timestamp = datetime.now(UTC)
    result: ProviderResult = provider.generate(
        model_id=TARGET_MODEL_ID,
        messages=messages,
        generation=generation,
    )
    if provider.request_attempt_count != 1:
        raise RuntimeError("Endpoint screen violated its one-attempt generation cap")

    record = {
        "label": SCREEN_LABEL,
        "screen_version": SCREEN_VERSION,
        "namespace": SCREEN_NAMESPACE,
        "status": "success"
        if result.status == ObservationStatus.RESPONSE
        else "technical_failure",
        "timestamp": timestamp.isoformat(),
        "script_id": script.script_id,
        "turn_number": 1,
        "context_condition": ContextCondition.NO_PRELOADED_CONTEXT.value,
        "requested_model_id": TARGET_MODEL_ID,
        "request_parameters": parameters,
        "request_stream": False,
        "request_payload_hash": digest,
        "generation_attempts": provider.request_attempt_count,
        "fallback_enabled": False,
        "catalogue_verification": catalogue,
        "result": result.model_dump(mode="json"),
    }
    path = atomic_write_json(_record_path(output_root, "result"), record)
    return record, path


def _print_offline_plan(plan: Mapping[str, Any]) -> None:
    print(SCREEN_LABEL)
    print("OFFLINE PREFLIGHT PLAN - NO NETWORK CALLS")
    print(f"Requested model: {plan['requested_model_id']}")
    print("One first-turn, no-context generation attempt; retries=0; fallback=false")


def _print_live_summary(record: Mapping[str, Any], path: Path) -> None:
    result = record["result"]
    usage = result.get("usage") or {}
    print(SCREEN_LABEL)
    print("Catalogue verification: exact=true; free=true; text->text=true; seed=true")
    print(f"Context length: {record['catalogue_verification']['context_length']}")
    print(f"Requested model: {record['requested_model_id']}")
    print(f"Resolved model: {result.get('resolved_model_id') or 'not returned'}")
    print(f"Provider: {result.get('provider_name') or 'not returned'}")
    print(f"Status: {record['status']}")
    print(f"HTTP status: {result.get('http_status') or 'not returned'}")
    print(f"Error type: {result.get('error_type') or 'none'}")
    print(f"Latency ms: {result['latency_ms']}")
    print(f"Finish reason: {result.get('finish_reason') or 'not returned'}")
    print(
        "Usage: "
        f"prompt={usage.get('prompt_tokens')}; "
        f"completion={usage.get('completion_tokens')}; total={usage.get('total_tokens')}"
    )
    print(f"Generation attempts: {record['generation_attempts']}")
    print(f"Record: {path.resolve()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline by default; screens one fixed free endpoint when fully gated."
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    arguments = parser.parse_args(argv)

    if not arguments.live:
        _print_offline_plan(build_offline_plan())
        return 0
    load_dotenv(ROOT / ".env", override=False)
    try:
        record, path = execute_live_screen(
            output_root=arguments.output_root,
            live_requested=True,
            live_confirmed=arguments.confirm_live,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    _print_live_summary(record, path)
    return 0 if record["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
