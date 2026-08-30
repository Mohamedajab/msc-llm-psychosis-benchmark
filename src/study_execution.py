"""Shared guarded execution and no-content summaries for technical pilots and Study V2."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from src.config_loader import configuration_bundle_hash, generation_for_model
from src.conversation_runner import ConversationRunner, create_run_header
from src.schemas import (
    ConversationRecord,
    HistoryPrefix,
    ManifestRow,
    ModelsConfig,
    RunHeader,
    ScriptConfig,
)
from src.storage import RawRunStore


def result_http_attempts(result: Any) -> int:
    """Return persisted POST attempts while remaining compatible with legacy records."""

    if result.http_attempts is not None:
        return result.http_attempts
    if result.error_type == "request_budget_exhausted":
        return 0
    return result.retry_count + 1


def stored_http_attempts(store: RawRunStore, run_ids: Iterable[str]) -> int:
    attempts = 0
    for run_id in run_ids:
        if not (store.run_directory(run_id) / "run.json").is_file():
            continue
        record = store.load(run_id)
        attempts += sum(result_http_attempts(event.result) for event in record.turns)
        attempts += sum(result_http_attempts(event.result) for event in record.errors)
    return attempts


def resume_or_new_header(store: RawRunStore, candidate: RunHeader) -> RunHeader:
    path = store.run_directory(candidate.run_id) / "run.json"
    if not path.exists():
        return candidate
    existing = RunHeader.model_validate_json(path.read_text(encoding="utf-8"))
    if existing.model_dump(exclude={"created_at"}) != candidate.model_dump(exclude={"created_at"}):
        raise RuntimeError(f"Resume blocked: immutable metadata changed for {candidate.run_id}")
    return existing


def execute_manifest_rows(
    *,
    rows: list[ManifestRow],
    scripts: list[ScriptConfig],
    histories: list[HistoryPrefix],
    models: ModelsConfig,
    provider: Any,
    store: RawRunStore,
    data_status: str,
    maximum_http_attempts: int,
    max_new_conversations: int | None = None,
    stop_after_execution_order: int | None = None,
) -> list[ConversationRecord]:
    """Execute rows in order without overwriting turns or exceeding a POST budget."""

    if maximum_http_attempts < 1:
        raise ValueError("maximum_http_attempts must be positive")
    by_script = {script.script_id: script for script in scripts}
    by_history = {history.history_id: history for history in histories}
    configuration_hash = configuration_bundle_hash(scripts, histories, models)
    ordered = sorted(rows, key=lambda row: row.execution_order)
    selected = [
        row
        for row in ordered
        if stop_after_execution_order is None or row.execution_order <= stop_after_execution_order
    ]
    provider.set_request_attempt_budget(maximum_http_attempts)
    records: list[ConversationRecord] = []
    new_conversations = 0
    for row in selected:
        if provider.request_attempt_count >= maximum_http_attempts:
            break
        script = by_script[row.script_id]
        prefix = by_history[script.history_id]
        generation = generation_for_model(models, row.model_slot, row.repetition)
        candidate = create_run_header(
            study_version=row.study_version,
            run_id=row.run_id,
            data_status=data_status,  # type: ignore[arg-type]
            script=script,
            condition=row.context_condition,
            model_slot=row.model_slot,
            model_id=row.requested_model_id,
            repetition=row.repetition,
            generation=generation,
            configuration_version=models.version,
            configuration_hash=configuration_hash,
        )
        existed = (store.run_directory(row.run_id) / "run.json").is_file()
        header = resume_or_new_header(store, candidate)
        if existed and (store.run_directory(row.run_id) / "turn-06-success.json").is_file():
            records.append(store.load(row.run_id))
            continue
        if not existed:
            if max_new_conversations is not None and new_conversations >= max_new_conversations:
                break
            new_conversations += 1
        before_errors = len(store.error_events(row.run_id)) if existed else 0
        record = ConversationRunner(provider, store).run_or_resume(
            header=header, script=script, prefix=prefix
        )
        records.append(record)
        new_errors = record.errors[before_errors:]
        if any(event.result.error_type == "http_429" for event in new_errors):
            break
    return records


def build_execution_summary(
    *,
    planned_rows: list[ManifestRow],
    store: RawRunStore,
    maximum_total_attempts: int | None = None,
) -> dict[str, Any]:
    """Summarise stored evidence without exposing request or response content."""

    records = [
        store.load(row.run_id)
        for row in sorted(planned_rows, key=lambda item: item.execution_order)
        if (store.run_directory(row.run_id) / "run.json").is_file()
    ]
    record_by_id = {record.header.run_id: record for record in records}
    attempts = stored_http_attempts(store, [row.run_id for row in planned_rows])
    successes = sum(len(record.turns) for record in records)
    errors = [event for record in records for event in record.errors]
    finish_reasons = Counter(
        event.result.finish_reason or "unreported" for record in records for event in record.turns
    )
    providers = Counter(
        (event.result.provider_name or "unreported") for record in records for event in record.turns
    )
    models = Counter(
        (event.result.resolved_model_id or "unreported")
        for record in records
        for event in record.turns
    )
    requested_models = Counter(row.requested_model_id for row in planned_rows)
    mismatch_count = sum(event.result.error_type == "resolved_model_mismatch" for event in errors)
    missing = len(planned_rows) * 6 - successes
    closed_by_truncation = {
        record.header.run_id
        for record in records
        if any(
            event.result.truncated
            or (event.result.finish_reason or "").strip().casefold() == "length"
            for event in record.turns
        )
    }
    unfillable_after_truncation = sum(
        6 - len(record_by_id[run_id].turns) for run_id in closed_by_truncation
    )
    fillable_missing = missing - unfillable_after_truncation
    next_order = next(
        (
            row.execution_order
            for row in sorted(planned_rows, key=lambda item: item.execution_order)
            if row.run_id in record_by_id
            if len(record_by_id[row.run_id].turns) < 6
            if row.run_id not in closed_by_truncation
        ),
        None,
    )
    if next_order is None:
        next_order = next(
            (
                row.execution_order
                for row in sorted(planned_rows, key=lambda item: item.execution_order)
                if row.run_id not in record_by_id
            ),
            None,
        )
    remaining = None
    sufficient = None
    if maximum_total_attempts is not None:
        remaining = max(0, maximum_total_attempts - attempts)
        sufficient = remaining >= fillable_missing
    return {
        "planned_conversations": len(planned_rows),
        "completed_conversations": sum(len(record.turns) == 6 for record in records),
        "partial_conversations": sum(0 < len(record.turns) < 6 for record in records),
        "failed_conversations": sum(not record.turns and bool(record.errors) for record in records),
        "successful_response_slots": successes,
        "missing_response_slots": missing,
        "fillable_missing_response_slots": fillable_missing,
        "unfillable_after_truncation_slots": unfillable_after_truncation,
        "closed_by_truncation_conversations": len(closed_by_truncation),
        "technical_errors": len(errors),
        "http_attempts_used": attempts,
        "error_types": dict(Counter(event.result.error_type or "unknown" for event in errors)),
        "finish_reasons": dict(finish_reasons),
        "truncation_count": sum(
            event.result.truncated for record in records for event in record.turns
        ),
        "requested_models": dict(requested_models),
        "resolved_models": dict(models),
        "resolved_providers": dict(providers),
        "provider_mismatches": mismatch_count,
        "remaining_attempt_allowance": remaining,
        "remaining_allowance_sufficient": sufficient,
        "missing_slots_can_be_filled": bool(fillable_missing and sufficient),
        "next_execution_order": next_order,
        "resume_would_perform_useful_work": bool(fillable_missing and next_order is not None),
        "can_resume_safely": (
            mismatch_count == 0 and fillable_missing > 0 and next_order is not None
        ),
        "output_directory": str(store.root.resolve()),
    }


def print_execution_summary(label: str, summary: dict[str, Any]) -> None:
    """Print safe aggregate metadata only."""

    print(label)
    print(
        "Conversations: "
        f"completed={summary['completed_conversations']}/"
        f"{summary['planned_conversations']}; partial={summary['partial_conversations']}; "
        f"failed={summary['failed_conversations']}"
    )
    print(
        "Response slots: "
        f"successful={summary['successful_response_slots']}; "
        f"missing={summary['missing_response_slots']}; errors={summary['technical_errors']}"
    )
    print(f"HTTP attempts used: {summary['http_attempts_used']}")
    print(f"Error types: {summary['error_types'] or {}}")
    print(f"Finish reasons: {summary['finish_reasons'] or {}}")
    print(f"Truncated responses: {summary['truncation_count']}")
    print(
        "Trajectories closed by truncation: "
        f"{summary['closed_by_truncation_conversations']}; "
        f"unfillable downstream slots={summary['unfillable_after_truncation_slots']}"
    )
    print(f"Requested models: {summary['requested_models'] or {}}")
    print(f"Resolved models: {summary['resolved_models'] or {}}")
    print(f"Resolved providers: {summary['resolved_providers'] or {}}")
    print(f"Provider/model mismatches: {summary['provider_mismatches']}")
    if summary["remaining_attempt_allowance"] is not None:
        print(f"Remaining attempt allowance: {summary['remaining_attempt_allowance']}")
        if summary["missing_response_slots"]:
            print(
                "Remaining allowance sufficient to fill missing slots: "
                f"{'yes' if summary['missing_slots_can_be_filled'] else 'no'}"
            )
        else:
            print("Remaining allowance sufficient to fill missing slots: not applicable")
    print(f"Next execution order: {summary['next_execution_order'] or 'complete'}")
    print(
        "Resume would perform useful work: "
        f"{'yes' if summary['resume_would_perform_useful_work'] else 'no'}"
    )
    print(f"Safe resume available: {'yes' if summary['can_resume_safely'] else 'no'}")
    print(f"Output directory: {summary['output_directory']}")
