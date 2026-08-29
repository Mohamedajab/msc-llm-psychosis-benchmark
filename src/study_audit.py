"""Honest reconciliation and technical audits for real Study V2 evidence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from src.schemas import ManifestRow
from src.storage import RawRunStore


class StudyEvidenceError(ValueError):
    """Raw material is mixed, unexpected, or incompatible with Study V2."""


def audit_study_evidence(rows: list[ManifestRow], raw_root: str | Path) -> dict[str, Any]:
    store = RawRunStore(raw_root)
    expected = {row.run_id: row for row in rows}
    unexpected = sorted(set(store.list_run_ids()) - set(expected))
    if unexpected:
        raise StudyEvidenceError(f"Unexpected run in Study V2 namespace: {unexpected[0]}")
    records = [store.load(run_id) for run_id in sorted(set(store.list_run_ids()) & set(expected))]
    for record in records:
        if record.header.data_status != "main_study":
            raise StudyEvidenceError(
                f"Non-main-study record in Study V2 namespace: {record.header.run_id}"
            )
        row = expected[record.header.run_id]
        if (
            record.header.study_version != row.study_version
            or record.header.requested_model_id != row.requested_model_id
            or record.header.model_slot != row.model_slot
        ):
            raise StudyEvidenceError(f"Manifest/raw mismatch: {record.header.run_id}")
    errors = [event for record in records for event in record.errors]
    turns = [event for record in records for event in record.turns]
    providers = Counter(event.result.provider_name or "unreported" for event in turns)
    requested_provider_pairs = Counter(
        (
            event.result.requested_model_id,
            event.result.provider_name or "unreported",
        )
        for event in turns
    )
    return {
        "availability": "available" if records else "unavailable",
        "reason": "" if records else "No real Study V2 raw records exist",
        "planned_conversations": len(rows),
        "stored_conversations": len(records),
        "completed_conversations": sum(len(record.turns) == 6 for record in records),
        "successful_responses": len(turns),
        "missing_responses": len(rows) * 6 - len(turns),
        "technical_errors": len(errors),
        "error_types": dict(Counter(event.result.error_type or "unknown" for event in errors)),
        "finish_reasons": dict(
            Counter(event.result.finish_reason or "unreported" for event in turns)
        ),
        "truncated_responses": sum(event.result.truncated for event in turns),
        "non_truncated_responses": sum(not event.result.truncated for event in turns),
        "provider_distribution": dict(providers),
        "model_provider_distribution": {
            f"{model}|{provider}": count
            for (model, provider), count in requested_provider_pairs.items()
        },
        "resolved_model_mismatches": sum(
            event.result.error_type == "resolved_model_mismatch" for event in errors
        ),
        "prompt_tokens": sum(
            event.result.usage.prompt_tokens or 0
            for event in turns
            if event.result.usage is not None
        ),
        "completion_tokens": sum(
            event.result.usage.completion_tokens or 0
            for event in turns
            if event.result.usage is not None
        ),
        "latency_ms_total": sum(event.result.latency_ms for event in turns),
    }
