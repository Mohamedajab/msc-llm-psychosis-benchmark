"""Offline tests for persisted main-study progress and recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.main_study as main_study
from src.config_loader import configuration_bundle_hash, generation_for_model
from src.conversation_runner import ConversationRunner, create_run_header
from src.main_study import (
    MAXIMUM_HTTP_ATTEMPTS,
    JobStatus,
    MainStudyError,
    StudyJobState,
    StudyPreflight,
    StudyProgress,
    load_job_state,
    load_study_progress,
    next_study_request,
    planned_study,
    release_worker,
    request_safe_stop,
    reserve_worker,
    retry_wait_seconds,
    run_main_study_preflight,
    run_study_worker,
    save_job_state,
)
from src.provider_client import DeterministicFixtureProvider, TargetProvider
from src.schemas import ObservationStatus, ProviderResult
from src.storage import RawRunStore
from src.study_execution import execute_manifest_rows

ROOT = Path(__file__).parents[1]


class FixtureProvider(DeterministicFixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_attempt_count = 0
        self.maximum = 0

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        if self.request_attempt_count >= self.maximum:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=kwargs["model_id"],
                latency_ms=0,
                retry_count=0,
                http_attempts=0,
                error_type="request_budget_exhausted",
            )
        self.request_attempt_count += 1
        return super().generate(**kwargs).model_copy(update={"http_attempts": 1})


class FailAfterTwo(TargetProvider):
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model_id, messages, generation):  # noqa: ANN001
        del messages, generation
        self.calls += 1
        if self.calls == 3:
            return ProviderResult(
                status=ObservationStatus.RATE_LIMITED,
                requested_model_id=model_id,
                provider_name="fixture",
                latency_ms=1,
                retry_count=0,
                http_attempts=1,
                http_status=429,
                error_type="http_429",
            )
        return ProviderResult(
            status=ObservationStatus.RESPONSE,
            text=f"saved-{self.calls}",
            requested_model_id=model_id,
            resolved_model_id=model_id,
            provider_name="fixture",
            finish_reason="stop",
            latency_ms=1,
            retry_count=0,
            http_attempts=1,
        )


class EmbeddedUpstreamErrorAfterTwo(TargetProvider):
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model_id, messages, generation):  # noqa: ANN001
        del messages, generation
        self.calls += 1
        if self.calls == 3:
            return _technical_error(
                "provider_body_error",
                message=repr(
                    {
                        "message": "Upstream error from Nvidia: Service temporarily overloaded",
                        "code": 502,
                    }
                ),
                http_status=200,
            ).model_copy(update={"requested_model_id": model_id})
        return ProviderResult(
            status=ObservationStatus.RESPONSE,
            text=f"saved-{self.calls}",
            requested_model_id=model_id,
            resolved_model_id=model_id,
            provider_name="fixture",
            finish_reason="stop",
            latency_ms=1,
            retry_count=0,
            http_attempts=1,
        )


class HardStopProvider(FixtureProvider):
    def __init__(self, error_type: str) -> None:
        super().__init__()
        self.error_type = error_type

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        self.request_attempt_count += 1
        if self.error_type in {"truncated", "content_filter"}:
            return ProviderResult(
                status=ObservationStatus.RESPONSE,
                text="Incomplete reply",
                requested_model_id=kwargs["model_id"],
                resolved_model_id=kwargs["model_id"],
                provider_name="fixture",
                finish_reason=("length" if self.error_type == "truncated" else "content_filter"),
                latency_ms=1,
                retry_count=0,
                http_attempts=1,
            )
        return ProviderResult(
            status=ObservationStatus.PROVIDER_ERROR,
            requested_model_id=kwargs["model_id"],
            resolved_model_id="different/model:free",
            provider_name="fixture",
            latency_ms=1,
            retry_count=0,
            http_attempts=1,
            error_type="resolved_model_mismatch",
        )


def _header(row, scripts, histories, models):  # noqa: ANN001, ANN202
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


def _progress(status: JobStatus, responses: int = 0) -> StudyProgress:
    return StudyProgress(
        status=status,
        conversations_complete=72 if responses == 432 else 0,
        responses_complete=responses,
        percent_complete=(responses / 432) * 100,
    )


def _ready_preflight() -> StudyPreflight:
    return StudyPreflight(
        ready=True,
        checks={"all": True},
        blockers=(),
        pilot_v6="PASS",
        final_pair_source="ORIGINAL_PAIR_V6",
        active_bundle="PASS",
        governance="PASS",
        main_study="READY",
    )


def _technical_error(
    error_type: str,
    *,
    message: str | None = None,
    http_status: int | None = None,
) -> ProviderResult:
    return ProviderResult(
        status=ObservationStatus.PROVIDER_ERROR,
        requested_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        provider_name="openrouter",
        latency_ms=1,
        retry_count=0,
        http_attempts=1,
        http_status=http_status,
        error_type=error_type,
        error_message=message,
    )


def test_progress_starts_at_zero_and_survives_state_reload(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    state_path = tmp_path / "job" / "state.json"
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=raw,
        state_path=state_path,
    )
    assert progress.status == JobStatus.NOT_STARTED
    assert progress.conversations_complete == 0
    assert progress.responses_complete == 0
    assert progress.responses_planned == 432
    assert progress.current_execution_order is None
    assert progress.current_turn is None
    assert progress.current_model_slot is None

    state = StudyJobState(
        status=JobStatus.STOPPED,
        started_at=datetime(2026, 8, 30, tzinfo=UTC),
        automatic_resumes=2,
        message="Stopped safely.",
    )
    save_job_state(state_path, state)
    assert load_job_state(state_path) == state
    reloaded = load_study_progress(
        repository_root=ROOT,
        raw_root=raw,
        state_path=state_path,
        now=datetime(2026, 8, 30, 1, tzinfo=UTC),
    )
    assert reloaded.status == JobStatus.STOPPED
    assert reloaded.automatic_resumes == 2
    assert reloaded.elapsed_seconds == 3600


def test_partial_progress_and_eta_are_derived_from_raw_evidence(tmp_path: Path) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    row = rows[0]
    script = next(value for value in scripts if value.script_id == row.script_id)
    prefix = next(value for value in histories if value.history_id == script.history_id)
    provider = FixtureProvider()
    provider.set_request_attempt_budget(10)
    store = RawRunStore(tmp_path / "raw")
    ConversationRunner(provider, store).run_or_resume(
        header=_header(row, scripts, histories, models),
        script=script,
        prefix=prefix,
        should_stop=lambda: provider.request_attempt_count >= 3,
    )
    now = datetime.now(UTC)
    state_path = tmp_path / "job" / "state.json"
    save_job_state(
        state_path,
        StudyJobState(status=JobStatus.RUNNING, started_at=now - timedelta(minutes=2)),
    )
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=state_path,
        now=now,
    )
    assert progress.responses_complete == 3
    assert progress.conversations_complete == 0
    assert progress.current_execution_order == row.execution_order
    assert progress.current_turn == 4
    assert progress.estimated_remaining_seconds is not None


def test_complete_progress_reports_432_responses(tmp_path: Path) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    store = RawRunStore(tmp_path / "raw")
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=FixtureProvider(),
        store=store,
        data_status="main_study",
        maximum_http_attempts=500,
    )
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=tmp_path / "state.json",
    )
    assert progress.status == JobStatus.COMPLETE
    assert progress.conversations_complete == 72
    assert progress.responses_complete == 432
    assert progress.percent_complete == 100
    assert set(progress.response_counts_by_model.values()) == {216}


def test_resume_keeps_successes_and_reconstructs_failed_turn_history(tmp_path: Path) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    row = rows[0]
    script = next(value for value in scripts if value.script_id == row.script_id)
    prefix = next(value for value in histories if value.history_id == script.history_id)
    store = RawRunStore(tmp_path / "raw")
    header = _header(row, scripts, histories, models)
    failed = ConversationRunner(FailAfterTwo(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    assert len(failed.turns) == 2
    assert len(failed.errors) == 1
    failed_messages = failed.errors[0].request_messages
    saved = {
        path: path.read_bytes() for path in store.run_directory(row.run_id).glob("*-success.json")
    }

    resumed = ConversationRunner(DeterministicFixtureProvider(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    assert len(resumed.turns) == 6
    assert resumed.turns[2].request_messages == failed_messages
    assert all(path.read_bytes() == content for path, content in saved.items())


def test_embedded_upstream_error_makes_blocked_study_safely_resumable(tmp_path: Path) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    row = rows[0]
    script = next(value for value in scripts if value.script_id == row.script_id)
    prefix = next(value for value in histories if value.history_id == script.history_id)
    store = RawRunStore(tmp_path / "raw")
    header = _header(row, scripts, histories, models)
    failed = ConversationRunner(EmbeddedUpstreamErrorAfterTwo(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    assert len(failed.turns) == 2
    assert len(failed.errors) == 1
    saved = {path: path.read_bytes() for path in store.run_directory(row.run_id).iterdir()}
    state_path = tmp_path / "job" / "state.json"
    save_job_state(
        state_path,
        StudyJobState(
            status=JobStatus.BLOCKED,
            message="Collection stopped after non-retryable error: provider_body_error.",
        ),
    )

    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=state_path,
    )
    request = next_study_request(repository_root=ROOT, raw_root=store.root)
    assert progress.status == JobStatus.RESUMABLE
    assert progress.recoverable is True
    assert progress.resume_reason == "upstream_http_502"
    assert progress.upstream_error_code == 502
    assert progress.current_turn == 3
    assert request is not None
    assert request.request_payload_hash == failed.errors[0].request_payload_hash

    resumed = ConversationRunner(DeterministicFixtureProvider(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    assert len(resumed.turns) == 6
    assert len(resumed.errors) == 1
    assert resumed.turns[2].request_payload_hash == failed.errors[0].request_payload_hash
    for path, content in saved.items():
        assert path.read_bytes() == content
    with pytest.raises(FileExistsError):
        store.append_success(resumed.turns[0])


def test_main_study_attempt_ceiling_remains_576() -> None:
    assert MAXIMUM_HTTP_ATTEMPTS == 576


@pytest.mark.parametrize("error_type", ["truncated", "content_filter", "resolved_model_mismatch"])
def test_integrity_errors_stop_before_another_conversation(tmp_path: Path, error_type: str) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    provider = HardStopProvider(error_type)
    store = RawRunStore(tmp_path / "raw")
    execute_manifest_rows(
        rows=rows[:2],
        scripts=scripts,
        histories=histories,
        models=models,
        provider=provider,
        store=store,
        data_status="main_study",
        maximum_http_attempts=10,
        stop_on_error=True,
        require_stop_finish_reason=True,
    )
    assert provider.request_attempt_count == 1
    assert store.list_run_ids() == [rows[0].run_id]
    record = store.load(rows[0].run_id)
    if error_type == "resolved_model_mismatch":
        assert record.errors[0].result.error_type == "resolved_model_mismatch"
    else:
        assert record.turns[0].result.finish_reason == error_type.replace("truncated", "length")


def test_preflight_blocks_hard_stop_but_not_recoverable_provider_error(tmp_path: Path) -> None:
    scripts, histories, models, rows = planned_study(ROOT)
    row = rows[0]
    store = RawRunStore(tmp_path / "raw")
    execute_manifest_rows(
        rows=[row],
        scripts=scripts,
        histories=histories,
        models=models,
        provider=HardStopProvider("truncated"),
        store=store,
        data_status="main_study",
        maximum_http_attempts=2,
        stop_on_error=True,
        require_stop_finish_reason=True,
    )
    preflight = run_main_study_preflight(
        repository_root=ROOT,
        raw_root=store.root,
        job_root=tmp_path / "job",
        pilot_v6_root=ROOT / "data/private/technical-pilot-v6.0.0",
        active_bundle_root=ROOT / "protocol/study-v2.1.0",
        governance_path=ROOT / "config/main-study-governance.yaml",
        environ={"OPENROUTER_API_KEY": "test-only"},
    )
    assert preflight.ready is False
    assert "stored_study_hard_block" in preflight.blockers


def test_malformed_evidence_fails_closed(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "unexpected"
    raw.mkdir(parents=True)
    (raw / "run.json").write_text("not json", encoding="utf-8")
    with pytest.raises((MainStudyError, ValueError)):
        load_study_progress(
            repository_root=ROOT,
            raw_root=raw.parent,
            state_path=tmp_path / "state.json",
        )


def test_duplicate_worker_reservation_is_prevented(tmp_path: Path) -> None:
    token = reserve_worker(tmp_path)
    try:
        with pytest.raises(MainStudyError, match="already running"):
            reserve_worker(tmp_path)
    finally:
        release_worker(tmp_path, token)


def test_safe_stop_is_persisted_and_worker_stops_before_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    job_root = tmp_path / "job"
    monkeypatch.setattr(main_study, "run_main_study_preflight", lambda **_: _ready_preflight())

    def progress(**kwargs):  # noqa: ANN003, ANN202
        del kwargs
        request_safe_stop(job_root)
        return _progress(JobStatus.RUNNING)

    monkeypatch.setattr(main_study, "load_study_progress", progress)

    def execute(**kwargs):  # noqa: ANN003, ANN202
        nonlocal calls
        del kwargs
        calls += 1
        return {}

    token = reserve_worker(job_root)
    result = run_study_worker(
        repository_root=ROOT,
        job_root=job_root,
        raw_root=tmp_path / "raw",
        pilot_v6_root=tmp_path / "pilot",
        active_bundle_root=tmp_path / "bundle",
        governance_path=tmp_path / "governance.yaml",
        lock_token=token,
        environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test"},
        execute_batch=execute,
    )
    assert result == 0
    assert calls == 0
    assert load_job_state(job_root / "state.json").status == JobStatus.STOPPED


def test_retry_wait_is_simple_and_bounded() -> None:
    assert [retry_wait_seconds(value) for value in (1, 2, 3, 4, 5)] == [30, 60, 120, 120, 120]


def test_worker_recovers_from_multiple_transient_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batches = 0
    sleeps: list[float] = []

    monkeypatch.setattr(main_study, "run_main_study_preflight", lambda **_: _ready_preflight())

    def progress(**kwargs):  # noqa: ANN003, ANN202
        del kwargs
        return _progress(JobStatus.COMPLETE, 432) if batches == 3 else _progress(JobStatus.RUNNING)

    def errors(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        return [
            SimpleNamespace(timestamp=value, result=_technical_error("http_429", http_status=429))
            for value in range(batches)
        ]

    def execute(**kwargs):  # noqa: ANN003, ANN202
        nonlocal batches
        del kwargs
        batches += 1
        return {}

    monkeypatch.setattr(main_study, "load_study_progress", progress)
    monkeypatch.setattr(main_study, "_stored_errors", errors)
    token = reserve_worker(tmp_path / "job")
    result = run_study_worker(
        repository_root=ROOT,
        job_root=tmp_path / "job",
        raw_root=tmp_path / "raw",
        pilot_v6_root=tmp_path / "pilot",
        active_bundle_root=tmp_path / "bundle",
        governance_path=tmp_path / "governance.yaml",
        lock_token=token,
        environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test"},
        execute_batch=execute,
        sleep=sleeps.append,
    )
    assert result == 0
    assert batches == 3
    assert sleeps == [30, 60]
    state = load_job_state(tmp_path / "job" / "state.json")
    assert state.status == JobStatus.COMPLETE
    assert state.automatic_resumes == 2


def test_worker_recovers_from_embedded_upstream_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batches = 0
    sleeps: list[float] = []
    message = repr(
        {
            "message": "Upstream error from Nvidia: Service temporarily overloaded",
            "code": 502,
        }
    )
    monkeypatch.setattr(main_study, "run_main_study_preflight", lambda **_: _ready_preflight())

    def progress(**kwargs):  # noqa: ANN003, ANN202
        del kwargs
        return _progress(JobStatus.COMPLETE, 432) if batches == 2 else _progress(JobStatus.RUNNING)

    def errors(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        return [
            SimpleNamespace(
                timestamp=1,
                result=_technical_error("provider_body_error", message=message, http_status=200),
            )
        ][:batches]

    def execute(**kwargs):  # noqa: ANN003, ANN202
        nonlocal batches
        del kwargs
        batches += 1
        return {}

    monkeypatch.setattr(main_study, "load_study_progress", progress)
    monkeypatch.setattr(main_study, "_stored_errors", errors)
    token = reserve_worker(tmp_path / "job")
    result = run_study_worker(
        repository_root=ROOT,
        job_root=tmp_path / "job",
        raw_root=tmp_path / "raw",
        pilot_v6_root=tmp_path / "pilot",
        active_bundle_root=tmp_path / "bundle",
        governance_path=tmp_path / "governance.yaml",
        lock_token=token,
        environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test"},
        execute_batch=execute,
        sleep=sleeps.append,
    )
    assert result == 0
    assert batches == 2
    assert sleeps == [30]
    state = load_job_state(tmp_path / "job" / "state.json")
    assert state.status == JobStatus.COMPLETE
    assert state.automatic_resumes == 1


def test_worker_blocks_when_recovery_limit_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batches = 0
    monkeypatch.setattr(main_study, "run_main_study_preflight", lambda **_: _ready_preflight())
    monkeypatch.setattr(
        main_study,
        "load_study_progress",
        lambda **_: _progress(JobStatus.RUNNING),
    )

    def errors(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        return [
            SimpleNamespace(timestamp=value, result=_technical_error("ReadTimeout"))
            for value in range(batches)
        ]

    def execute(**kwargs):  # noqa: ANN003, ANN202
        nonlocal batches
        del kwargs
        batches += 1
        return {}

    monkeypatch.setattr(main_study, "_stored_errors", errors)
    token = reserve_worker(tmp_path / "job")
    result = run_study_worker(
        repository_root=ROOT,
        job_root=tmp_path / "job",
        raw_root=tmp_path / "raw",
        pilot_v6_root=tmp_path / "pilot",
        active_bundle_root=tmp_path / "bundle",
        governance_path=tmp_path / "governance.yaml",
        lock_token=token,
        environ={"RUN_LIVE_STUDY": "1", "OPENROUTER_API_KEY": "test"},
        maximum_auto_resumes=2,
        execute_batch=execute,
        sleep=lambda _: None,
    )
    assert result == 1
    assert batches == 3
    state = load_job_state(tmp_path / "job" / "state.json")
    assert state.status == JobStatus.BLOCKED
    assert "automatic-resume limit" in state.message


def test_pilot_v6_pass_is_recomputed_without_changing_evidence() -> None:
    assessment = main_study.assess_pilot_v6(
        pilot_output_root=ROOT / "data/private/technical-pilot-v6.0.0",
        repository_root=ROOT,
        persist=False,
    )
    assert assessment.verdict == main_study.PilotV6Verdict.PASS
    assert assessment.source_evidence_hash == (
        "1c3d8f75e1de85ea6c05972de69304703c9c5b91d7a73ea0fe9c23ac12e08b4e"
    )
