"""Persisted progress and local preflight checks for Main Study V2."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.active_study import build_final_manifest
from src.config_loader import (
    configuration_bundle_hash,
    generation_for_model,
    load_histories,
    load_scripts,
)
from src.conversation_runner import create_run_header, payload_hash
from src.main_study_readiness import evaluate_main_study_readiness
from src.pilot_v6 import (
    FINAL_PAIR_SOURCE,
    MINIMAX_MODEL_ID,
    NEMOTRON_MODEL_ID,
    PilotV6Verdict,
    assess_pilot_v6,
    build_original_pair_models_config,
)
from src.provider_errors import classify_error_type, classify_provider_result
from src.runtime_amendments import (
    audit_finish_metadata,
    build_runtime_target_messages,
    load_runtime_amendments,
    use_runtime_target_message_builder,
)
from src.schemas import ErrorEvent, ManifestRow, ModelsConfig, RunHeader, StrictModel
from src.storage import RawRunStore, atomic_write_json
from src.study_audit import audit_study_evidence
from src.study_execution import build_execution_summary, resume_or_new_header

PLANNED_CONVERSATIONS = 72
PLANNED_RESPONSES = 432
MAXIMUM_HTTP_ATTEMPTS = 576
DEFAULT_INITIAL_RETRY_WAIT_SECONDS = 30
DEFAULT_MAXIMUM_RETRY_WAIT_SECONDS = 120
DEFAULT_MAXIMUM_AUTO_RESUMES = 5
REQUEST_INTERVAL_SECONDS = 5.0


class JobStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PREFLIGHT_READY = "PREFLIGHT_READY"
    RUNNING = "RUNNING"
    WAITING_TO_RETRY = "WAITING_TO_RETRY"
    RESUMING = "RESUMING"
    RESUMABLE = "RESUMABLE"
    STOPPED = "STOPPED"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


class MainStudyError(RuntimeError):
    """The main-study job state or stored evidence is unsafe to use."""


class StudyJobState(StrictModel):
    version: str = "main-study-job-v1.0.0"
    status: JobStatus = JobStatus.NOT_STARTED
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    worker_pid: int | None = None
    automatic_resumes: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    worker_error_count: int = Field(default=0, ge=0)
    next_retry_at: datetime | None = None
    last_error_type: str | None = None
    recoverable: bool = False
    resume_reason: str | None = None
    upstream_error_code: int | None = None
    upstream_error_message: str | None = None
    message: str = ""
    current_execution_order: int | None = None
    current_turn: int | None = None
    current_model_slot: str | None = None


class StudyProgress(StrictModel):
    status: JobStatus
    conversations_complete: int
    conversations_planned: int = PLANNED_CONVERSATIONS
    responses_complete: int
    responses_planned: int = PLANNED_RESPONSES
    percent_complete: float
    current_execution_order: int | None = None
    current_turn: int | None = None
    current_model_slot: str | None = None
    current_model_id: str | None = None
    technical_errors: int = 0
    automatic_resumes: int = 0
    truncations: int = 0
    approved_finish_metadata_anomalies: int = 0
    finish_metadata_status_counts: dict[str, int] = Field(default_factory=dict)
    technical_amendment_ids: tuple[str, ...] = ()
    http_attempts: int = 0
    elapsed_seconds: float = 0
    estimated_remaining_seconds: float | None = None
    next_retry_at: datetime | None = None
    last_error_type: str | None = None
    recoverable: bool = False
    resume_reason: str | None = None
    upstream_error_code: int | None = None
    upstream_error_message: str | None = None
    response_counts_by_model: dict[str, int] = Field(default_factory=dict)
    message: str = ""


class StudyPreflight(StrictModel):
    ready: bool
    checks: dict[str, bool]
    blockers: tuple[str, ...]
    pilot_v6: str
    final_pair_source: str
    active_bundle: str
    governance: str
    main_study: str
    network_requests: int = 0


class NextStudyRequest(StrictModel):
    run_id: str
    execution_order: int
    turn_number: int
    model_slot: str
    requested_model_id: str
    request_payload_hash: str
    latest_error: ErrorEvent | None = None
    technical_amendment_ids_in_history: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_paths(repository_root: str | Path) -> dict[str, Path]:
    root = Path(repository_root)
    return {
        "raw_root": root / "data" / "raw" / "study-v2",
        "job_root": root / "data" / "private" / "main-study-job",
        "pilot_v6_root": root / "data" / "private" / "technical-pilot-v6.0.0",
        "active_bundle_root": root / "protocol" / "study-v2.1.0",
        "governance_path": root / "config" / "main-study-governance.yaml",
        "runtime_amendments_path": root / "config" / "main-study-runtime-amendments.yaml",
    }


def planned_study(
    repository_root: str | Path,
) -> tuple[list[Any], list[Any], ModelsConfig, list[ManifestRow]]:
    root = Path(repository_root)
    scripts = load_scripts(root / "config" / "scenarios")
    histories = load_histories(root / "config" / "histories")
    models = build_original_pair_models_config(repository_root=root)
    rows = build_final_manifest(repository_root=root, models=models)
    return scripts, histories, models, rows


def load_job_state(path: str | Path) -> StudyJobState:
    source = Path(path)
    if not source.is_file():
        return StudyJobState()
    try:
        return StudyJobState.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MainStudyError("Main-study job state is malformed") from error


def save_job_state(path: str | Path, state: StudyJobState) -> Path:
    return atomic_write_json(Path(path), state.model_dump(mode="json"), overwrite=True)


def _expected_header(
    row: ManifestRow,
    *,
    scripts: list[Any],
    histories: list[Any],
    models: ModelsConfig,
) -> RunHeader:
    script = next(script for script in scripts if script.script_id == row.script_id)
    return create_run_header(
        study_version=row.study_version,
        run_id=row.run_id,
        data_status="main_study",
        script=script,
        condition=row.context_condition,
        model_slot=row.model_slot,
        model_id=row.requested_model_id,
        repetition=row.repetition,
        generation=generation_for_model(models, row.model_slot, row.repetition),
        configuration_version=models.version,
        configuration_hash=configuration_bundle_hash(scripts, histories, models),
    )


def validate_saved_study(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
) -> dict[str, Any]:
    scripts, histories, models, rows = planned_study(repository_root)
    report = audit_study_evidence(rows, raw_root)
    store = RawRunStore(raw_root)
    expected = {row.run_id: row for row in rows}
    event_ids: set[str] = set()
    for run_id in store.list_run_ids():
        row = expected[run_id]
        candidate = _expected_header(
            row,
            scripts=scripts,
            histories=histories,
            models=models,
        )
        resume_or_new_header(store, candidate)
        record = store.load(run_id)
        for event in (*record.turns, *record.errors):
            if event.event_id in event_ids:
                raise MainStudyError("Duplicate event identifier in main-study evidence")
            event_ids.add(event.event_id)
    return report


def reconstruct_request_hash(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    run_id: str,
    turn_number: int,
) -> str:
    """Rebuild one target request from frozen inputs and preceding successes."""

    scripts, histories, models, rows = planned_study(repository_root)
    row = next((item for item in rows if item.run_id == run_id), None)
    if row is None or not 1 <= turn_number <= 6:
        raise MainStudyError("Requested resume cell is not in the frozen manifest")
    script = next(item for item in scripts if item.script_id == row.script_id)
    prefix = next(item for item in histories if item.history_id == script.history_id)
    store = RawRunStore(raw_root)
    successes = store.successful_turns(run_id)
    preceding = [event for event in successes if event.turn_number < turn_number]
    if [event.turn_number for event in preceding] != list(range(1, turn_number)):
        raise MainStudyError("Cannot reconstruct a request from non-contiguous history")
    messages = build_runtime_target_messages(
        condition=row.context_condition,
        prefix=prefix,
        completed_exchanges=[(event.user_message, event.result.text or "") for event in preceding],
        current_user_message=script.turns[turn_number - 1],
        visible_response_instruction=generation_for_model(
            models, row.model_slot, row.repetition
        ).visible_response_instruction,
    )
    generation = generation_for_model(models, row.model_slot, row.repetition)
    return payload_hash(
        model_id=row.requested_model_id,
        messages=messages,
        parameters=generation.request_parameters(),
    )


def next_study_request(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    runtime_amendments_path: str | Path | None = None,
) -> NextStudyRequest | None:
    """Return safe metadata for the first missing response in execution order."""

    _, _, _, rows = planned_study(repository_root)
    store = RawRunStore(raw_root)
    amendments_path = (
        runtime_amendments_path or default_paths(repository_root)["runtime_amendments_path"]
    )
    finish_audit = audit_finish_metadata(store=store, amendments_path=amendments_path)
    if finish_audit.validation_errors:
        raise MainStudyError("Stored evidence does not match its runtime technical amendment")
    summary = build_execution_summary(
        planned_rows=rows,
        store=store,
        maximum_total_attempts=MAXIMUM_HTTP_ATTEMPTS,
    )
    execution_order = summary["next_execution_order"]
    if execution_order is None:
        return None
    row = next(item for item in rows if item.execution_order == execution_order)
    run_directory = store.run_directory(row.run_id)
    turn_number = 1
    latest_error = None
    if (run_directory / "run.json").is_file():
        turn_number = len(store.successful_turns(row.run_id)) + 1
        relevant = [
            event for event in store.error_events(row.run_id) if event.turn_number == turn_number
        ]
        if relevant:
            latest_error = max(relevant, key=lambda event: event.timestamp)
    digest = reconstruct_request_hash(
        repository_root=repository_root,
        raw_root=raw_root,
        run_id=row.run_id,
        turn_number=turn_number,
    )
    if latest_error is not None and latest_error.request_payload_hash != digest:
        raise MainStudyError("Stored failed request does not match the reconstructed request")
    configured = load_runtime_amendments(amendments_path)
    amendment_ids_in_history = tuple(
        item.amendment_id
        for item in configured.amendments
        if item.run_id == row.run_id
        and item.turn_number < turn_number
        and item.amendment_id in finish_audit.amendment_ids
    )
    return NextStudyRequest(
        run_id=row.run_id,
        execution_order=execution_order,
        turn_number=turn_number,
        model_slot=row.model_slot,
        requested_model_id=row.requested_model_id,
        request_payload_hash=digest,
        latest_error=latest_error,
        technical_amendment_ids_in_history=amendment_ids_in_history,
    )


def _model_response_counts(rows: list[ManifestRow], store: RawRunStore) -> dict[str, int]:
    counts: Counter[str] = Counter()
    row_by_id = {row.run_id: row for row in rows}
    for run_id in store.list_run_ids():
        record = store.load(run_id)
        counts[row_by_id[run_id].requested_model_id] += len(record.turns)
    return dict(counts)


def _eta_seconds(store: RawRunStore, rows: list[ManifestRow], remaining: int) -> float | None:
    events = []
    for row in rows:
        if (store.run_directory(row.run_id) / "run.json").is_file():
            events.extend(store.successful_turns(row.run_id))
    if len(events) < 3:
        return None
    recent = sorted(events, key=lambda event: event.response_timestamp)[-30:]
    mean_seconds = sum(event.result.latency_ms for event in recent) / len(recent) / 1000
    return remaining * max(mean_seconds, REQUEST_INTERVAL_SECONDS)


def load_study_progress(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    state_path: str | Path,
    runtime_amendments_path: str | Path | None = None,
    now: datetime | None = None,
) -> StudyProgress:
    _, _, _, rows = planned_study(repository_root)
    validate_saved_study(repository_root=repository_root, raw_root=raw_root)
    store = RawRunStore(raw_root)
    amendments_path = (
        runtime_amendments_path or default_paths(repository_root)["runtime_amendments_path"]
    )
    finish_audit = audit_finish_metadata(store=store, amendments_path=amendments_path)
    state = load_job_state(state_path)
    summary = build_execution_summary(
        planned_rows=rows,
        store=store,
        maximum_total_attempts=MAXIMUM_HTTP_ATTEMPTS,
    )
    next_request = next_study_request(
        repository_root=repository_root,
        raw_root=raw_root,
        runtime_amendments_path=amendments_path,
    )
    classification = (
        classify_provider_result(next_request.latest_error.result)
        if next_request is not None and next_request.latest_error is not None
        else None
    )
    status = state.status
    worker_state_is_stale = status in {
        JobStatus.RUNNING,
        JobStatus.RESUMING,
        JobStatus.WAITING_TO_RETRY,
    } and not worker_is_active(Path(state_path).parent)
    if summary["truncation_count"] or summary["provider_mismatches"] or finish_audit.hard_blocked:
        status = JobStatus.BLOCKED
    elif summary["successful_response_slots"] == PLANNED_RESPONSES:
        status = JobStatus.COMPLETE
    elif (
        status in {JobStatus.BLOCKED, JobStatus.STOPPED}
        and classification is not None
        and classification.retryable
        and summary["http_attempts_used"] < MAXIMUM_HTTP_ATTEMPTS
    ):
        status = JobStatus.RESUMABLE
    elif (
        worker_state_is_stale
        and next_request is not None
        and summary["http_attempts_used"] < MAXIMUM_HTTP_ATTEMPTS
    ):
        status = JobStatus.RESUMABLE
    elif (
        status in {JobStatus.BLOCKED, JobStatus.STOPPED}
        and next_request is not None
        and next_request.technical_amendment_ids_in_history
        and summary["http_attempts_used"] < MAXIMUM_HTTP_ATTEMPTS
    ):
        status = JobStatus.RESUMABLE

    current_order = state.current_execution_order
    current_turn = state.current_turn
    current_slot = state.current_model_slot
    if status == JobStatus.NOT_STARTED:
        current_order = None
        current_turn = None
        current_slot = None
    elif current_order is None or status not in {JobStatus.RUNNING, JobStatus.RESUMING}:
        current_order = next_request.execution_order if next_request is not None else None
        if current_order is not None:
            row = next(row for row in rows if row.execution_order == current_order)
            current_slot = row.model_slot
            current_turn = next_request.turn_number
        else:
            current_turn = None
            current_slot = None
    model_id = None
    if current_slot is not None:
        model_id = next(row.requested_model_id for row in rows if row.model_slot == current_slot)

    reference = now or utc_now()
    elapsed = 0.0
    if state.started_at is not None:
        end = state.finished_at or reference
        elapsed = max(0.0, (end - state.started_at).total_seconds())
    complete = summary["successful_response_slots"]
    return StudyProgress(
        status=status,
        conversations_complete=summary["completed_conversations"],
        responses_complete=complete,
        percent_complete=(complete / PLANNED_RESPONSES) * 100,
        current_execution_order=current_order,
        current_turn=current_turn,
        current_model_slot=current_slot,
        current_model_id=model_id,
        technical_errors=summary["technical_errors"] + state.worker_error_count,
        automatic_resumes=state.automatic_resumes,
        truncations=summary["truncation_count"],
        approved_finish_metadata_anomalies=finish_audit.approved_anomaly_count,
        finish_metadata_status_counts=finish_audit.status_counts,
        technical_amendment_ids=finish_audit.amendment_ids,
        http_attempts=summary["http_attempts_used"],
        elapsed_seconds=elapsed,
        estimated_remaining_seconds=_eta_seconds(store, rows, PLANNED_RESPONSES - complete),
        next_retry_at=state.next_retry_at,
        last_error_type=(
            classification.reason_code if classification is not None else state.last_error_type
        ),
        recoverable=status == JobStatus.RESUMABLE,
        resume_reason=(
            classification.reason_code
            if classification is not None
            else (
                "approved_finish_metadata_amendment"
                if status == JobStatus.RESUMABLE
                and next_request is not None
                and next_request.technical_amendment_ids_in_history
                else "worker_not_running"
                if status == JobStatus.RESUMABLE and worker_state_is_stale
                else None
            )
        ),
        upstream_error_code=(
            classification.upstream_error_code if classification is not None else None
        ),
        upstream_error_message=(
            classification.upstream_error_message if classification is not None else None
        ),
        response_counts_by_model=_model_response_counts(rows, store),
        message=(
            "Stored evidence does not match its runtime technical amendment."
            if finish_audit.validation_errors
            else state.message
        ),
    )


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_worker_lock(job_root: str | Path) -> dict[str, Any] | None:
    path = Path(job_root) / "worker.lock"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("token"), str) or not isinstance(value.get("pid"), int):
            raise ValueError
        return value
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise MainStudyError("Main-study worker lock is malformed") from error


def worker_is_active(job_root: str | Path, *, ignore_pid: int | None = None) -> bool:
    value = read_worker_lock(job_root)
    if value is None:
        return False
    pid = value["pid"]
    if ignore_pid is not None and pid == ignore_pid:
        return False
    if pid > 0:
        return _process_running(pid)
    created = datetime.fromisoformat(value["created_at"])
    return utc_now() - created < timedelta(minutes=2)


def reserve_worker(job_root: str | Path) -> str:
    root = Path(job_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "worker.lock"
    if lock_path.exists():
        if worker_is_active(root):
            raise MainStudyError("A main-study worker is already running")
        lock_path.unlink()
    token = uuid.uuid4().hex
    atomic_write_json(
        lock_path,
        {"token": token, "pid": 0, "created_at": utc_now().isoformat()},
    )
    return token


def claim_worker(job_root: str | Path, token: str, pid: int) -> None:
    root = Path(job_root)
    value = read_worker_lock(root)
    if value is None or value["token"] != token:
        raise MainStudyError("Main-study worker reservation is missing or stale")
    value["pid"] = pid
    atomic_write_json(root / "worker.lock", value, overwrite=True)


def release_worker(job_root: str | Path, token: str) -> None:
    root = Path(job_root)
    value = read_worker_lock(root)
    if value is not None and value["token"] == token:
        (root / "worker.lock").unlink(missing_ok=True)


def request_safe_stop(job_root: str | Path) -> None:
    root = Path(job_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "stop.requested"
    if not path.exists():
        atomic_write_json(path, {"requested_at": utc_now().isoformat()})


def stop_requested(job_root: str | Path) -> bool:
    return (Path(job_root) / "stop.requested").is_file()


def clear_stop_request(job_root: str | Path) -> None:
    (Path(job_root) / "stop.requested").unlink(missing_ok=True)


def retry_wait_seconds(
    failure_number: int,
    *,
    initial_seconds: int = DEFAULT_INITIAL_RETRY_WAIT_SECONDS,
    maximum_seconds: int = DEFAULT_MAXIMUM_RETRY_WAIT_SECONDS,
) -> int:
    if failure_number < 1 or initial_seconds < 1 or maximum_seconds < initial_seconds:
        raise ValueError("Invalid automatic-resume timing")
    return min(maximum_seconds, initial_seconds * (2 ** (failure_number - 1)))


def _stored_errors(rows: list[ManifestRow], raw_root: str | Path) -> list[Any]:
    store = RawRunStore(raw_root)
    errors = []
    for row in rows:
        if (store.run_directory(row.run_id) / "run.json").is_file():
            errors.extend(store.error_events(row.run_id))
    return sorted(errors, key=lambda event: event.timestamp)


def _finish_state(
    state_path: Path,
    state: StudyJobState,
    *,
    status: JobStatus,
    message: str,
    now: Callable[[], datetime],
) -> None:
    finished = now()
    save_job_state(
        state_path,
        state.model_copy(
            update={
                "status": status,
                "updated_at": finished,
                "finished_at": finished,
                "next_retry_at": None,
                "message": message,
                "current_execution_order": None,
                "current_turn": None,
                "current_model_slot": None,
            }
        ),
    )


def run_study_worker(
    *,
    repository_root: str | Path,
    job_root: str | Path,
    raw_root: str | Path,
    pilot_v6_root: str | Path,
    active_bundle_root: str | Path,
    governance_path: str | Path,
    lock_token: str,
    environ: Mapping[str, str] | None = None,
    maximum_auto_resumes: int = DEFAULT_MAXIMUM_AUTO_RESUMES,
    initial_retry_wait_seconds: int = DEFAULT_INITIAL_RETRY_WAIT_SECONDS,
    maximum_retry_wait_seconds: int = DEFAULT_MAXIMUM_RETRY_WAIT_SECONDS,
    execute_batch: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> int:
    """Run the frozen study, resuming only missing turns after transient errors."""

    if maximum_auto_resumes < 0:
        raise ValueError("maximum_auto_resumes cannot be negative")
    root = Path(repository_root)
    job_directory = Path(job_root)
    state_path = job_directory / "state.json"
    claim_worker(job_directory, lock_token, os.getpid())
    try:
        clear_stop_request(job_directory)
        preflight = run_main_study_preflight(
            repository_root=root,
            raw_root=raw_root,
            job_root=job_directory,
            pilot_v6_root=pilot_v6_root,
            active_bundle_root=active_bundle_root,
            governance_path=governance_path,
            environ=dict(os.environ if environ is None else environ),
            ignore_worker_pid=os.getpid(),
        )
        previous = load_job_state(state_path)
        started = previous.started_at or now()
        if not preflight.ready:
            _finish_state(
                state_path,
                previous.model_copy(update={"started_at": started}),
                status=JobStatus.BLOCKED,
                message="Preflight is blocked: " + ", ".join(preflight.blockers),
                now=now,
            )
            return 1

        state = previous.model_copy(
            update={
                "status": JobStatus.RUNNING,
                "started_at": started,
                "updated_at": now(),
                "finished_at": None,
                "worker_pid": os.getpid(),
                "next_retry_at": None,
                "recoverable": False,
                "resume_reason": None,
                "message": "Main-study collection is running.",
            }
        )
        save_job_state(state_path, state)
        _, _, _, rows = planned_study(root)
        order_by_run = {row.run_id: row for row in rows}

        if execute_batch is None:
            from scripts.run_study import execute_live_study

            execute_batch = execute_live_study

        while True:
            progress_before = load_study_progress(
                repository_root=root,
                raw_root=raw_root,
                state_path=state_path,
                now=now(),
            )
            if progress_before.status == JobStatus.COMPLETE:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.COMPLETE,
                    message="All 72 conversations and 432 responses are saved.",
                    now=now,
                )
                return 0
            if progress_before.status == JobStatus.BLOCKED:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.BLOCKED,
                    message="Stored evidence contains a hard-stop condition.",
                    now=now,
                )
                return 1
            if stop_requested(job_directory):
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.STOPPED,
                    message="Stopped safely between requests. The study can resume from disk.",
                    now=now,
                )
                return 0
            remaining_attempts = MAXIMUM_HTTP_ATTEMPTS - progress_before.http_attempts
            if remaining_attempts <= 0:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.BLOCKED,
                    message="The main-study HTTP-attempt limit has been reached.",
                    now=now,
                )
                return 1

            errors_before = _stored_errors(rows, raw_root)
            responses_before = progress_before.responses_complete

            def on_turn_start(header: RunHeader, turn_number: int) -> None:
                nonlocal state
                row = order_by_run[header.run_id]
                state = state.model_copy(
                    update={
                        "status": JobStatus.RUNNING,
                        "updated_at": now(),
                        "current_execution_order": row.execution_order,
                        "current_turn": turn_number,
                        "current_model_slot": row.model_slot,
                        "message": "Requesting the next missing response.",
                    }
                )
                save_job_state(state_path, state)

            try:
                with use_runtime_target_message_builder():
                    execute_batch(
                        maximum_http_attempts=remaining_attempts,
                        live_requested=True,
                        live_confirmed=True,
                        protocol_confirmed=True,
                        output_root=Path(raw_root),
                        request_interval_seconds=REQUEST_INTERVAL_SECONDS,
                        environ=dict(os.environ if environ is None else environ),
                        pilot_output_root=Path(pilot_v6_root),
                        active_bundle_root=Path(active_bundle_root),
                        final_artifact_root=root,
                        governance_path=Path(governance_path),
                        on_turn_start=on_turn_start,
                        should_stop=lambda: stop_requested(job_directory),
                        stop_on_error=True,
                    )
            except (OSError, RuntimeError, ValueError) as error:
                message = str(error)
                error_type = (
                    "catalogue_preflight_error"
                    if "Catalogue qualification failed before POST" in message
                    else type(error).__name__
                )
                state = state.model_copy(
                    update={
                        "worker_error_count": state.worker_error_count + 1,
                        "last_error_type": error_type,
                    }
                )
                new_classification = classify_error_type(error_type)
            else:
                new_errors = _stored_errors(rows, raw_root)[len(errors_before) :]
                new_classification = (
                    classify_provider_result(new_errors[-1].result) if new_errors else None
                )

            progress_after = load_study_progress(
                repository_root=root,
                raw_root=raw_root,
                state_path=state_path,
                now=now(),
            )
            if stop_requested(job_directory):
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.STOPPED,
                    message="Stopped safely between requests. The study can resume from disk.",
                    now=now,
                )
                return 0
            if progress_after.status == JobStatus.COMPLETE:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.COMPLETE,
                    message="All 72 conversations and 432 responses are saved.",
                    now=now,
                )
                return 0
            if progress_after.status == JobStatus.BLOCKED:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.BLOCKED,
                    message=(
                        "Stored evidence contains a truncation, model mismatch, "
                        "or incomplete finish reason. It was not retried."
                    ),
                    now=now,
                )
                return 1

            if new_classification is None:
                if progress_after.responses_complete <= responses_before:
                    _finish_state(
                        state_path,
                        state,
                        status=JobStatus.BLOCKED,
                        message="A collection pass ended without saving a response.",
                        now=now,
                    )
                    return 1
                state = load_job_state(state_path)
                continue
            if not new_classification.retryable:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.BLOCKED,
                    message=(
                        "Collection stopped after non-retryable error: "
                        f"{new_classification.reason_code}."
                    ),
                    now=now,
                )
                return 1

            made_progress = progress_after.responses_complete > responses_before
            failures = 1 if made_progress else state.consecutive_failures + 1
            if failures > maximum_auto_resumes:
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.BLOCKED,
                    message="The automatic-resume limit was reached.",
                    now=now,
                )
                return 1
            wait_seconds = retry_wait_seconds(
                failures,
                initial_seconds=initial_retry_wait_seconds,
                maximum_seconds=maximum_retry_wait_seconds,
            )
            retry_at = now() + timedelta(seconds=wait_seconds)
            state = state.model_copy(
                update={
                    "status": JobStatus.WAITING_TO_RETRY,
                    "updated_at": now(),
                    "consecutive_failures": failures,
                    "next_retry_at": retry_at,
                    "last_error_type": new_classification.reason_code,
                    "recoverable": True,
                    "resume_reason": new_classification.reason_code,
                    "upstream_error_code": new_classification.upstream_error_code,
                    "upstream_error_message": new_classification.upstream_error_message,
                    "message": f"Temporary API error. Resuming in about {wait_seconds} seconds.",
                }
            )
            save_job_state(state_path, state)
            sleep(wait_seconds)
            if stop_requested(job_directory):
                _finish_state(
                    state_path,
                    state,
                    status=JobStatus.STOPPED,
                    message="Stopped safely while waiting to retry.",
                    now=now,
                )
                return 0
            state = state.model_copy(
                update={
                    "status": JobStatus.RESUMING,
                    "updated_at": now(),
                    "automatic_resumes": state.automatic_resumes + 1,
                    "next_retry_at": None,
                    "recoverable": False,
                    "message": "Resuming from the first missing response.",
                }
            )
            save_job_state(state_path, state)
    finally:
        release_worker(job_directory, lock_token)


def run_main_study_preflight(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    job_root: str | Path,
    pilot_v6_root: str | Path,
    active_bundle_root: str | Path,
    governance_path: str | Path,
    environ: dict[str, str] | None = None,
    ignore_worker_pid: int | None = None,
) -> StudyPreflight:
    root = Path(repository_root)
    checks: dict[str, bool] = {}
    blockers: list[str] = []
    values = os.environ if environ is None else environ
    try:
        _, _, models, rows = planned_study(root)
        ids = {slot: item.default_model_id for slot, item in models.model_slots.items()}
        checks["expected_model_pair"] = ids == {
            "model_minimax": MINIMAX_MODEL_ID,
            "model_nemotron": NEMOTRON_MODEL_ID,
        }
        checks["manifest_72_conversations"] = len(rows) == PLANNED_CONVERSATIONS
        checks["manifest_432_responses"] = len(rows) * 6 == PLANNED_RESPONSES
    except (OSError, RuntimeError, ValueError):
        checks["expected_model_pair"] = False
        checks["manifest_72_conversations"] = False
        checks["manifest_432_responses"] = False
        blockers.append("frozen_study_definition_invalid")

    try:
        pilot = assess_pilot_v6(
            pilot_output_root=pilot_v6_root,
            repository_root=root,
            persist=False,
        )
        checks["pilot_v6_pass"] = (
            pilot.verdict == PilotV6Verdict.PASS and pilot.final_pair_source == FINAL_PAIR_SOURCE
        )
    except (OSError, RuntimeError, ValueError):
        pilot = None
        checks["pilot_v6_pass"] = False
    if not checks["pilot_v6_pass"]:
        blockers.append("pilot_v6_not_pass")

    def writable_parent(path: Path) -> bool:
        candidate = path
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return candidate.is_dir() and os.access(candidate, os.W_OK)

    checks["storage_available"] = all(
        writable_parent(path) for path in (Path(raw_root), Path(job_root))
    )
    if not checks["storage_available"]:
        blockers.append("storage_not_writable")

    try:
        load_job_state(Path(job_root) / "state.json")
        validate_saved_study(repository_root=root, raw_root=raw_root)
        checks["saved_state_readable"] = True
    except (OSError, RuntimeError, ValueError):
        checks["saved_state_readable"] = False
        blockers.append("saved_study_state_invalid")

    try:
        checks["no_active_worker"] = not worker_is_active(job_root, ignore_pid=ignore_worker_pid)
    except (OSError, RuntimeError, ValueError):
        checks["no_active_worker"] = False
    if not checks["no_active_worker"]:
        blockers.append("main_study_worker_already_running")

    checks["api_key_present"] = bool(values.get("OPENROUTER_API_KEY", "").strip())
    if not checks["api_key_present"]:
        blockers.append("api_key_not_available")

    bundle = Path(active_bundle_root)
    readiness = evaluate_main_study_readiness(
        repository_root=root,
        governance_path=governance_path,
        pilot_output_root=pilot_v6_root,
        active_bundle_root=bundle if bundle.is_dir() else None,
        final_artifact_root=root,
    )
    blockers.extend(readiness.blockers)
    checks["active_bundle_verified"] = readiness.active_bundle == "PASS"
    checks["governance_complete"] = readiness.governance == "PASS"
    checks["main_study_ready"] = readiness.main_study == "READY"

    try:
        progress = load_study_progress(
            repository_root=root,
            raw_root=raw_root,
            state_path=Path(job_root) / "state.json",
        )
        if progress.status == JobStatus.COMPLETE:
            blockers.append("main_study_already_complete")
        elif progress.status == JobStatus.BLOCKED:
            blockers.append("stored_study_hard_block")
    except (OSError, RuntimeError, ValueError):
        pass

    unique = tuple(dict.fromkeys(blockers))
    return StudyPreflight(
        ready=not unique and all(checks.values()),
        checks=checks,
        blockers=unique,
        pilot_v6=pilot.verdict.value if pilot is not None else "UNAVAILABLE",
        final_pair_source=(pilot.final_pair_source if pilot is not None else "NONE"),
        active_bundle=readiness.active_bundle,
        governance=readiness.governance,
        main_study=readiness.main_study,
    )


def launch_study_worker(
    *,
    repository_root: str | Path,
    job_root: str | Path,
    raw_root: str | Path,
    pilot_v6_root: str | Path,
    active_bundle_root: str | Path,
    governance_path: str | Path,
    environ: dict[str, str] | None = None,
) -> int:
    root = Path(repository_root)
    token = reserve_worker(job_root)
    values = dict(os.environ if environ is None else environ)
    values["RUN_LIVE_STUDY"] = "1"
    command = [
        sys.executable,
        str(root / "scripts" / "run_study_worker.py"),
        "--live",
        "--confirm-live",
        "--confirm-protocol-frozen",
        "--lock-token",
        token,
        "--job-root",
        str(job_root),
        "--output-root",
        str(raw_root),
        "--pilot-output-root",
        str(pilot_v6_root),
        "--active-bundle-root",
        str(active_bundle_root),
        "--governance",
        str(governance_path),
    ]
    log_path = Path(job_root) / "worker.log"
    log_handle = log_path.open("a", encoding="utf-8")
    try:
        options: dict[str, Any] = {
            "cwd": root,
            "env": values,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(command, **options)
    except Exception:
        release_worker(job_root, token)
        raise
    finally:
        log_handle.close()
    return process.pid


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "calculating..."
    total_minutes = max(0, round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"
