"""Content-free generation-budget audit for immutable technical pilots."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from src.pilot_qualification import assess_pilot_v4, assess_pilot_v5
from src.schemas import StrictModel
from src.storage import RawRunStore

AUDIT_VERSION = "generation-budget-audit-v1.0.0"


class GenerationBudgetAudit(StrictModel):
    audit_version: str = AUDIT_VERSION
    record_type: str = "SAFE GENERATION-BUDGET AUDIT - TECHNICAL EVIDENCE ONLY"
    reasoning_contribution: str
    pilots: dict[str, dict[str, Any]]


def _median(values: Iterable[int | float | None]) -> int | float | None:
    reported = [value for value in values if value is not None]
    return statistics.median(reported) if reported else None


def _pilot_records(output_root: str | Path, prefix: str) -> list[Any]:
    store = RawRunStore(output_root)
    return [store.load(run_id) for run_id in store.list_run_ids() if run_id.startswith(prefix)]


def _audit_one(
    *,
    output_root: str | Path,
    prefix: str,
    assessor: Callable[..., Any],
) -> dict[str, Any]:
    assessment = assessor(output_root=output_root, persist=False)
    records = _pilot_records(output_root, prefix)
    groups: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    response_metadata_keys: dict[str, int] = defaultdict(int)
    successful = 0
    for record in records:
        for event in record.turns:
            successful += 1
            result = event.result
            for key in result.response_metadata:
                response_metadata_keys[key] += 1
            groups[
                (
                    record.header.requested_model_id,
                    result.resolved_model_id,
                    result.provider_name,
                    record.header.context_condition.value,
                    result.finish_reason,
                    result.truncated,
                    record.header.generation_config.version,
                    record.header.generation_config.max_tokens,
                    record.header.generation_config.completion_limit_parameter,
                    (
                        record.header.generation_config.reasoning_policy.reasoning_control_requested
                        if record.header.generation_config.reasoning_policy
                        else "NONE_LEGACY"
                    ),
                )
            ].append(result)
    rows: list[dict[str, Any]] = []
    for key, results in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        (
            requested,
            resolved,
            provider,
            context,
            finish_reason,
            truncated,
            generation_version,
            maximum,
            limit_parameter,
            reasoning_requested,
        ) = key
        usages = [result.usage for result in results]
        reasoning_values = [usage.reasoning_tokens if usage else None for usage in usages]
        visible_token_values = [
            usage.visible_completion_tokens if usage else None for usage in usages
        ]
        cached_values = [usage.cached_prompt_tokens if usage else None for usage in usages]
        rows.append(
            {
                "requested_model": requested,
                "resolved_model": resolved,
                "provider": provider,
                "context_condition": context,
                "finish_reason": finish_reason,
                "truncated": truncated,
                "response_count": len(results),
                "generation_version": generation_version,
                "max_completion_tokens": maximum,
                "completion_limit_parameter": limit_parameter,
                "reasoning_control_requested": reasoning_requested,
                "median_prompt_tokens": _median(
                    usage.prompt_tokens if usage else None for usage in usages
                ),
                "median_completion_tokens": _median(
                    usage.completion_tokens if usage else None for usage in usages
                ),
                "median_total_tokens": _median(
                    usage.total_tokens if usage else None for usage in usages
                ),
                "median_reasoning_tokens": _median(reasoning_values),
                "median_visible_completion_tokens": _median(visible_token_values),
                "median_cached_prompt_tokens": _median(cached_values),
                "reasoning_usage_reporting_status": (
                    "REPORTED_ALL"
                    if all(value is not None for value in reasoning_values)
                    else "REPORTED_PARTIAL"
                    if any(value is not None for value in reasoning_values)
                    else "NOT_REPORTED"
                ),
                "visible_token_reporting_status": (
                    "REPORTED_ALL"
                    if all(value is not None for value in visible_token_values)
                    else "REPORTED_PARTIAL"
                    if any(value is not None for value in visible_token_values)
                    else "NOT_REPORTED"
                ),
                "median_visible_characters": _median(
                    result.visible_character_count for result in results
                ),
                "median_visible_words": _median(result.visible_word_count for result in results),
                "median_visible_sentences": _median(
                    result.visible_sentence_count for result in results
                ),
                "median_latency_ms": _median(result.latency_ms for result in results),
                "http_statuses": {
                    str(status): sum(result.http_status == status for result in results)
                    for status in sorted(
                        {result.http_status for result in results if result.http_status is not None}
                    )
                },
            }
        )
    return {
        "pilot_version": assessment.pilot_version,
        "verdict": assessment.verdict.value,
        "source_evidence_hash": assessment.source_evidence_hash,
        "successful_response_slots": successful,
        "response_metadata_keys": dict(sorted(response_metadata_keys.items())),
        "rows": rows,
    }


def audit_generation_budget(output_root: str | Path) -> GenerationBudgetAudit:
    """Audit V4/V5 metadata without mutating their assessment namespaces."""

    v4 = _audit_one(
        output_root=output_root,
        prefix="technical-pilot-v4_",
        assessor=assess_pilot_v4,
    )
    v5 = _audit_one(
        output_root=output_root,
        prefix="technical-pilot-v5_",
        assessor=assess_pilot_v5,
    )
    reported = [
        row["reasoning_usage_reporting_status"] for pilot in (v4, v5) for row in pilot["rows"]
    ]
    conclusion = "INCONCLUSIVE" if not reported or "NOT_REPORTED" in reported else "REQUIRES_REVIEW"
    return GenerationBudgetAudit(
        reasoning_contribution=conclusion,
        pilots={"pilot_v4": v4, "pilot_v5": v5},
    )
