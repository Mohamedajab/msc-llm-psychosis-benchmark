"""Bounded benign calibration of reasoning and completion-budget semantics."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.config_loader import canonical_hash
from src.provider_client import OpenRouterProvider, qualify_catalogue_entry
from src.schemas import (
    ChatMessage,
    GenerationConfig,
    ObservationStatus,
    ProviderResult,
    ProviderRoutingPolicy,
    ReasoningPolicyConfig,
    StrictModel,
)
from src.storage import atomic_write_json

CALIBRATION_VERSION = "technical-generation-calibration-v1.0.0"
CALIBRATION_LABEL = "TECHNICAL GENERATION CALIBRATION - NOT RESEARCH DATA"
EXACT_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b:free"
MAX_GENERATION_REQUESTS = 6
MINIMUM_REQUEST_INTERVAL_SECONDS = 5.0
MINIMUM_CONTEXT_TOKENS = 16_384
STIMULUS_VERSION = "benign-event-planning-v1"

BENIGN_MESSAGES = (
    ChatMessage(
        role="system",
        content=(
            "Respond naturally and directly as a conversational assistant. Be concise while "
            "still giving a complete response. Avoid unnecessary detail."
        ),
    ),
    ChatMessage(
        role="user",
        content=(
            "A fictional community centre is planning a Saturday event for 80 guests. It has "
            "one hall, two smaller rooms, six volunteers, a modest equipment budget, and fixed "
            "quiet hours after 18:00. The event needs welcome, food, two workshops, a short "
            "performance, accessible breaks, setup, and cleanup."
        ),
    ),
    ChatMessage(
        role="assistant",
        content=("I can help organise those constraints into a practical schedule and allocation."),
    ),
    ChatMessage(
        role="user",
        content=(
            "Propose a workable plan, note the main trade-offs, and identify what the organiser "
            "should confirm before publishing it."
        ),
    ),
)


class CalibrationVerdict(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class CalibrationRecord(StrictModel):
    record_version: str = CALIBRATION_VERSION
    record_type: str = CALIBRATION_LABEL
    event_id: str
    condition: str
    timestamp: datetime
    stimulus_version: str = STIMULUS_VERSION
    stimulus_structure_hash: str
    requested_model_id: str = EXACT_MODEL_ID
    catalogue_checked_at: datetime
    catalogue_safe_metadata: dict[str, Any]
    generation: GenerationConfig
    request_payload_hash: str
    result: ProviderResult


class CalibrationSummary(StrictModel):
    calibration_version: str = CALIBRATION_VERSION
    verdict: CalibrationVerdict
    generation_requests: int = Field(ge=0, le=MAX_GENERATION_REQUESTS)
    records: tuple[dict[str, Any], ...] = ()
    network_requests_reported: int


def stimulus_structure_hash() -> str:
    return canonical_hash(
        [{"role": message.role, "characters": len(message.content)} for message in BENIGN_MESSAGES]
    )


def _generation(
    condition: str,
    *,
    maximum: int,
    reasoning_requested: str,
) -> GenerationConfig:
    reasoning = None
    if reasoning_requested == "DISABLED":
        reasoning = ReasoningPolicyConfig(
            version="calibration-reasoning-v1",
            reasoning_control_capability="SUPPORTED",
            reasoning_control_requested="DISABLED",
            exclude_reasoning_trace=True,
        )
    return GenerationConfig(
        version=f"calibration-{condition}",
        temperature=0.2,
        max_tokens=maximum,
        completion_limit_parameter="max_tokens",
        top_p=1.0,
        seed=20260814,
        timeout_seconds=120,
        max_retries=0,
        visible_response_instruction=None,
        reasoning_policy=reasoning,
    )


def calibration_conditions(
    records: Sequence[CalibrationRecord],
) -> list[tuple[str, GenerationConfig]]:
    """Return the next minimal adaptive condition, never more than six total."""

    by_condition = {record.condition: record for record in records}
    if "native_1024" not in by_condition:
        return [
            ("native_1024", _generation("native-1024", maximum=1024, reasoning_requested="NONE"))
        ]
    if "disabled_1024" not in by_condition:
        return [
            (
                "disabled_1024",
                _generation("disabled-1024", maximum=1024, reasoning_requested="DISABLED"),
            )
        ]
    native = by_condition["native_1024"].result
    disabled = by_condition["disabled_1024"].result
    if native.finish_reason == "length" and disabled.finish_reason == "length":
        if "disabled_2048" not in by_condition:
            return [
                (
                    "disabled_2048",
                    _generation("disabled-2048", maximum=2048, reasoning_requested="DISABLED"),
                )
            ]
        if by_condition["disabled_2048"].result.finish_reason == "length" and (
            "disabled_4096" not in by_condition
        ):
            return [
                (
                    "disabled_4096",
                    _generation("disabled-4096", maximum=4096, reasoning_requested="DISABLED"),
                )
            ]
    if native.finish_reason == "length" and disabled.finish_reason == "stop":
        if "native_1024_repeat" not in by_condition:
            return [
                (
                    "native_1024_repeat",
                    _generation("native-1024-repeat", maximum=1024, reasoning_requested="NONE"),
                )
            ]
        if "disabled_1024_repeat" not in by_condition:
            return [
                (
                    "disabled_1024_repeat",
                    _generation(
                        "disabled-1024-repeat", maximum=1024, reasoning_requested="DISABLED"
                    ),
                )
            ]
        native_repeat = by_condition["native_1024_repeat"].result
        disabled_repeat = by_condition["disabled_1024_repeat"].result
        if (
            native_repeat.finish_reason == "length"
            and disabled_repeat.finish_reason == "stop"
            and "native_2048" not in by_condition
        ):
            return [
                (
                    "native_2048",
                    _generation("native-2048", maximum=2048, reasoning_requested="NONE"),
                )
            ]
        if (
            "native_2048" in by_condition
            and by_condition["native_2048"].result.finish_reason == "length"
            and "native_4096" not in by_condition
        ):
            return [
                (
                    "native_4096",
                    _generation("native-4096", maximum=4096, reasoning_requested="NONE"),
                )
            ]
    return []


def _catalogue_safe_metadata(entry: Mapping[str, Any]) -> dict[str, Any]:
    qualified = qualify_catalogue_entry(
        EXACT_MODEL_ID, entry, minimum_context_tokens=MINIMUM_CONTEXT_TOKENS
    )
    supported = tuple(str(value) for value in entry.get("supported_parameters") or ())
    reasoning = entry.get("reasoning")
    if "reasoning" not in supported or not isinstance(reasoning, Mapping):
        raise RuntimeError("Exact endpoint does not expose verifiable reasoning control metadata")
    if reasoning.get("mandatory") is not False:
        raise RuntimeError("Exact endpoint does not verify optional reasoning")
    return {
        **qualified,
        "reasoning_parameter_advertised": True,
        "reasoning_mandatory": False,
        "reasoning_default_enabled": reasoning.get("default_enabled"),
        "reasoning_supported_efforts": list(reasoning.get("supported_efforts") or ()),
        "reasoning_supports_max_tokens": reasoning.get("supports_max_tokens"),
        "catalogue_entry_hash": canonical_hash(entry),
    }


def _load_records(root: str | Path) -> list[CalibrationRecord]:
    source = Path(root)
    if not source.exists():
        return []
    records = [
        CalibrationRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(source.glob("*.json"))
    ]
    conditions = [record.condition for record in records]
    if len(conditions) != len(set(conditions)):
        raise RuntimeError("Calibration evidence contains duplicate conditions")
    if any(record.requested_model_id != EXACT_MODEL_ID for record in records):
        raise RuntimeError("Calibration evidence contains a different model identity")
    return records


def _result_safe(record: CalibrationRecord) -> dict[str, Any]:
    usage = record.result.usage
    return {
        "condition": record.condition,
        "requested_model": record.result.requested_model_id,
        "resolved_model": record.result.resolved_model_id,
        "provider": record.result.provider_name,
        "http_status": record.result.http_status,
        "status": record.result.status.value,
        "finish_reason": record.result.finish_reason,
        "truncated": record.result.truncated,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "reasoning_tokens": usage.reasoning_tokens if usage else None,
        "visible_completion_tokens": usage.visible_completion_tokens if usage else None,
        "visible_characters": record.result.visible_character_count,
        "visible_words": record.result.visible_word_count,
        "visible_sentences": record.result.visible_sentence_count,
        "latency_ms": record.result.latency_ms,
        "zero_price_confirmed": (
            record.catalogue_safe_metadata.get("prompt_price") == "0"
            and record.catalogue_safe_metadata.get("completion_price") == "0"
        ),
    }


def summarise_calibration(records: Sequence[CalibrationRecord]) -> CalibrationSummary:
    safe = tuple(_result_safe(record) for record in records)
    by_condition = {record.condition: record for record in records}
    verdict = CalibrationVerdict.NOT_RUN
    if records:
        verdict = CalibrationVerdict.INCONCLUSIVE
    if {"native_1024", "disabled_1024"} <= set(by_condition):
        native = by_condition["native_1024"].result
        disabled = by_condition["disabled_1024"].result
        usage_a = native.usage
        usage_b = disabled.usage
        if (
            native.finish_reason == "length"
            and disabled.finish_reason == "stop"
            and usage_a is not None
            and usage_b is not None
            and usage_a.reasoning_tokens is not None
            and usage_b.reasoning_tokens is not None
            and usage_a.reasoning_tokens > usage_b.reasoning_tokens
        ):
            verdict = CalibrationVerdict.SUPPORTED
        elif (
            usage_a is not None
            and usage_b is not None
            and usage_a.reasoning_tokens == 0
            and usage_b.reasoning_tokens == 0
            and native.finish_reason == "length"
        ):
            verdict = CalibrationVerdict.NOT_SUPPORTED
    return CalibrationSummary(
        verdict=verdict,
        generation_requests=len(records),
        records=safe,
        network_requests_reported=len(records),
    )


def load_calibration_summary(output_root: str | Path) -> CalibrationSummary:
    """Recompute the safe summary from private records without network access."""

    return summarise_calibration(_load_records(output_root))


def execute_calibration(
    *,
    provider: OpenRouterProvider,
    output_root: str | Path,
) -> CalibrationSummary:
    """Run the predetermined adaptive diagnostic under a six-POST persisted cap."""

    root = Path(output_root)
    records = _load_records(root)
    if len(records) >= MAX_GENERATION_REQUESTS:
        return summarise_calibration(records)
    provider.set_request_attempt_budget(MAX_GENERATION_REQUESTS - len(records))
    provider.set_retry_rate_limits(False)
    provider.set_minimum_request_interval(MINIMUM_REQUEST_INTERVAL_SECONDS)
    provider.set_provider_routing(
        ProviderRoutingPolicy(
            version="generation-calibration-routing-v1",
            allow_fallbacks=False,
            require_parameters=True,
            pinned_providers={},
            minimum_context_tokens=MINIMUM_CONTEXT_TOKENS,
        )
    )
    while len(records) < MAX_GENERATION_REQUESTS:
        next_conditions = calibration_conditions(records)
        if not next_conditions:
            break
        condition, generation = next_conditions[0]
        entry = provider.get_exact_model_catalogue_entry(EXACT_MODEL_ID, timeout_seconds=20)
        safe_catalogue = _catalogue_safe_metadata(entry)
        checked_at = datetime.now(UTC)
        result = provider.generate(
            model_id=EXACT_MODEL_ID,
            messages=BENIGN_MESSAGES,
            generation=generation,
        )
        record = CalibrationRecord(
            event_id=uuid.uuid4().hex,
            condition=condition,
            timestamp=datetime.now(UTC),
            stimulus_structure_hash=stimulus_structure_hash(),
            catalogue_checked_at=checked_at,
            catalogue_safe_metadata=safe_catalogue,
            generation=generation,
            request_payload_hash=hashlib.sha256(
                json.dumps(
                    {
                        "model": EXACT_MODEL_ID,
                        "messages": [message.model_dump() for message in BENIGN_MESSAGES],
                        "parameters": generation.request_parameters(),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            result=result,
        )
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_write_json(
            root / f"{timestamp}-{condition}-{record.event_id}.json",
            record.model_dump(mode="json"),
        )
        records.append(record)
        if result.status != ObservationStatus.RESPONSE:
            break
    return summarise_calibration(records)


def offline_calibration_plan() -> dict[str, Any]:
    return {
        "calibration_version": CALIBRATION_VERSION,
        "model_id": EXACT_MODEL_ID,
        "stimulus_version": STIMULUS_VERSION,
        "maximum_generation_requests": MAX_GENERATION_REQUESTS,
        "minimum_request_interval_seconds": MINIMUM_REQUEST_INTERVAL_SECONDS,
        "network_requests": 0,
        "status": CalibrationVerdict.NOT_RUN.value,
    }
