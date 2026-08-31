"""Offline checks for the Study V2.1 finish-metadata amendment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from src.config_loader import configuration_bundle_hash, generation_for_model
from src.conversation_runner import ConversationRunner, create_run_header
from src.main_study import (
    MAXIMUM_HTTP_ATTEMPTS,
    JobStatus,
    StudyJobState,
    load_study_progress,
    next_study_request,
    planned_study,
    save_job_state,
)
from src.runtime_amendments import (
    RuntimeAmendmentError,
    amendment_provenance,
    audit_finish_metadata,
    load_runtime_amendments,
    sha256_file,
    validate_finish_metadata_amendment,
)
from src.schemas import (
    ChatMessage,
    ObservationStatus,
    ProviderResult,
    TokenUsage,
    TurnEvent,
)
from src.storage import RawRunStore
from src.study_execution import build_execution_summary

ROOT = Path(__file__).parents[1]
CURRENT_RUN_ID = "study-v2.1.0_monitoring_ambiguous_v1_model_minimax_no_preloaded_context_r2"
CURRENT_EVENT_ID = "5fb47d48696642c9bd009fe0c1c71238"
CURRENT_RAW_HASH = "4ff417d6fe39f6afc018208162c7185d510c7151635857f54c43be19d09ebd43"
CURRENT_TURN_6_HASH = "eed86edc116f5e26532ae6923ba58739df15720ed51f35c37625482cb0bff121"


def _header(row, scripts, histories, models):  # noqa: ANN001, ANN202
    script = next(item for item in scripts if item.script_id == row.script_id)
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


def _make_store(tmp_path: Path, *, turns: int = 1, null_turns: set[int] | None = None):
    scripts, histories, models, rows = planned_study(ROOT)
    row = rows[0]
    script = next(item for item in scripts if item.script_id == row.script_id)
    store = RawRunStore(tmp_path / "raw")
    store.initialise(_header(row, scripts, histories, models))
    nulls = null_turns or {1}
    for turn in range(1, turns + 1):
        finish_reason = None if turn in nulls else "stop"
        event = TurnEvent(
            event_id=f"event-{turn}",
            run_id=row.run_id,
            turn_number=turn,
            request_timestamp=datetime(2026, 8, 31, tzinfo=UTC),
            response_timestamp=datetime(2026, 8, 31, 0, 0, turn, tzinfo=UTC),
            request_model_id=row.requested_model_id,
            request_messages=(ChatMessage(role="user", content=script.turns[turn - 1]),),
            request_parameters={"seed": row.planned_seed},
            request_payload_hash=f"{turn:064x}",
            user_message=script.turns[turn - 1],
            result=ProviderResult(
                status=ObservationStatus.RESPONSE,
                text=f"Saved fixture response {turn}.",
                requested_model_id=row.requested_model_id,
                resolved_model_id=row.requested_model_id,
                provider_name="fixture-provider",
                generation_id=f"generation-{turn}",
                finish_reason=finish_reason,
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                    reasoning_tokens=0,
                    cached_prompt_tokens=0,
                ),
                latency_ms=10,
                retry_count=0,
                http_attempts=1,
                response_metadata={
                    "choice_count": 1,
                    "content_present": True,
                    "finish_reason": finish_reason,
                    "native_finish_reason": finish_reason,
                },
            ),
        )
        store.append_success(event)
    return store, row, script, histories


def _write_amendment(tmp_path: Path, store: RawRunStore, *, turn: int = 1) -> Path:
    event = store.successful_turns(store.list_run_ids()[0])[turn - 1]
    raw_path = store.run_directory(event.run_id) / f"turn-{turn:02d}-success.json"
    value = {
        "version": "main-study-runtime-amendments-v1.0.0",
        "amendments": [
            {
                "amendment_id": "test-finish-metadata-amendment",
                "classification": "finish_metadata_unreported",
                "approved_for_trajectory_continuation": True,
                "study_version": "study-v2.1.0",
                "run_id": event.run_id,
                "turn_number": turn,
                "raw_filename": f"turn-{turn:02d}-success.json",
                "raw_file_sha256": sha256_file(raw_path),
                "event_id": event.event_id,
                "request_payload_hash": event.request_payload_hash,
                "generation_id": event.result.generation_id,
                "requested_model_id": event.result.requested_model_id,
                "resolved_model_id": event.result.resolved_model_id,
                "provider_name": event.result.provider_name,
                "choice_count": 1,
                "content_present": True,
                "completion_tokens": 20,
                "completion_envelope_tokens": 4096,
                "external_verification": {
                    "source": "OpenRouter generation metadata GET",
                    "generation_id": event.result.generation_id,
                    "model": event.result.requested_model_id,
                    "provider_name": event.result.provider_name,
                    "cancelled": False,
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "native_tokens_prompt": 100,
                    "native_tokens_completion": 20,
                    "finish_reason": None,
                    "native_finish_reason": None,
                    "latency": 10,
                    "generation_time": 10,
                },
            }
        ],
    }
    path = tmp_path / "amendments.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _config_value(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _save_config(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _rewrite_raw(store: RawRunStore, path: Path, amend_path: Path, change) -> None:  # noqa: ANN001
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    config = _config_value(amend_path)
    config["amendments"][0]["raw_file_sha256"] = sha256_file(path)
    _save_config(amend_path, config)


def test_exact_amendment_validates_without_rewriting_evidence(tmp_path: Path) -> None:
    store, _, _, _ = _make_store(tmp_path)
    path = _write_amendment(tmp_path, store)
    raw_path = store.run_directory(store.list_run_ids()[0]) / "turn-01-success.json"
    before = raw_path.read_bytes()
    amendment = load_runtime_amendments(path).amendments[0]

    validated = validate_finish_metadata_amendment(amendment, store=store)

    assert validated.amendment_id == "test-finish-metadata-amendment"
    assert raw_path.read_bytes() == before
    event = store.successful_turns(amendment.run_id)[0]
    assert event.result.finish_reason is None
    assert amendment_provenance(event, validated=validated) == {
        "finish_metadata_status": "unreported",
        "technical_amendment_id": "test-finish-metadata-amendment",
        "technical_amendment_applied": True,
        "conditioned_on_technical_amendment_ids": (),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", "different-event"),
        ("raw_file_sha256", "0" * 64),
        ("request_payload_hash", "f" * 64),
        ("generation_id", "different-generation"),
        ("provider_name", "different-provider"),
    ],
)
def test_amendment_identity_mismatch_fails_closed(tmp_path: Path, field: str, value: str) -> None:
    store, _, _, _ = _make_store(tmp_path)
    path = _write_amendment(tmp_path, store)
    config = _config_value(path)
    config["amendments"][0][field] = value
    if field == "generation_id":
        config["amendments"][0]["external_verification"]["generation_id"] = value
    if field == "provider_name":
        config["amendments"][0]["external_verification"]["provider_name"] = value
    _save_config(path, config)

    with pytest.raises(RuntimeAmendmentError):
        amendment = load_runtime_amendments(path).amendments[0]
        validate_finish_metadata_amendment(amendment, store=store)


def test_requested_and_resolved_model_mismatch_is_rejected(tmp_path: Path) -> None:
    store, _, _, _ = _make_store(tmp_path)
    path = _write_amendment(tmp_path, store)
    config = _config_value(path)
    config["amendments"][0]["resolved_model_id"] = "different/model:free"
    _save_config(path, config)
    with pytest.raises(RuntimeAmendmentError):
        load_runtime_amendments(path)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
        lambda value: value["result"].update({"error_type": "provider_body_error"}),
        lambda value: value["result"].update({"text": ""}),
    ],
    ids=["truncated-length", "explicit-error", "empty-content"],
)
def test_unsafe_response_cannot_use_amendment(tmp_path: Path, change) -> None:  # noqa: ANN001
    store, _, _, _ = _make_store(tmp_path)
    amend_path = _write_amendment(tmp_path, store)
    raw_path = store.run_directory(store.list_run_ids()[0]) / "turn-01-success.json"
    _rewrite_raw(store, raw_path, amend_path, change)
    amendment = load_runtime_amendments(amend_path).amendments[0]
    with pytest.raises(RuntimeAmendmentError):
        validate_finish_metadata_amendment(amendment, store=store)


def test_null_finish_without_exact_amendment_remains_blocked(tmp_path: Path) -> None:
    store, _, _, _ = _make_store(tmp_path)
    empty = tmp_path / "empty.yaml"
    _save_config(
        empty,
        {"version": "main-study-runtime-amendments-v1.0.0", "amendments": []},
    )
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=tmp_path / "state.json",
        runtime_amendments_path=empty,
    )
    assert progress.status == JobStatus.BLOCKED
    assert progress.approved_finish_metadata_anomalies == 0


def test_a_second_null_finish_event_remains_blocked(tmp_path: Path) -> None:
    store, _, _, _ = _make_store(tmp_path, turns=2, null_turns={1, 2})
    path = _write_amendment(tmp_path, store)
    audit = audit_finish_metadata(store=store, amendments_path=path)
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=tmp_path / "state.json",
        runtime_amendments_path=path,
    )
    assert audit.approved_anomaly_count == 1
    assert audit.unapproved_anomaly_count == 1
    assert progress.status == JobStatus.BLOCKED


def test_approved_anomaly_is_separate_from_raw_finish_summary(tmp_path: Path) -> None:
    store, _, _, _ = _make_store(tmp_path)
    _, _, _, rows = planned_study(ROOT)
    path = _write_amendment(tmp_path, store)
    summary = build_execution_summary(
        planned_rows=rows,
        store=store,
        maximum_total_attempts=MAXIMUM_HTTP_ATTEMPTS,
    )
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=tmp_path / "state.json",
        runtime_amendments_path=path,
    )
    assert summary["finish_reasons"] == {"unreported": 1}
    assert progress.finish_metadata_status_counts == {"unreported": 1}
    assert progress.approved_finish_metadata_anomalies == 1
    assert progress.truncations == 0


def test_resume_starts_at_six_and_uses_saved_turn_five_context(tmp_path: Path) -> None:
    store, row, script, histories = _make_store(tmp_path, turns=5, null_turns={5})
    path = _write_amendment(tmp_path, store, turn=5)
    state_path = tmp_path / "state.json"
    save_job_state(state_path, StudyJobState(status=JobStatus.BLOCKED))
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=store.root,
        state_path=state_path,
        runtime_amendments_path=path,
    )
    request = next_study_request(
        repository_root=ROOT,
        raw_root=store.root,
        runtime_amendments_path=path,
    )
    assert progress.status == JobStatus.RESUMABLE
    assert progress.current_turn == 6
    assert request is not None
    assert request.turn_number == 6
    assert request.technical_amendment_ids_in_history == ("test-finish-metadata-amendment",)

    saved = {item: item.read_bytes() for item in store.run_directory(row.run_id).iterdir()}

    class RecordingProvider:
        def __init__(self) -> None:
            self.calls = []

        def generate(self, *, model_id, messages, generation):  # noqa: ANN001, ANN202
            del generation
            self.calls.append(tuple(messages))
            return ProviderResult(
                status=ObservationStatus.RESPONSE,
                text="Only turn six is new.",
                requested_model_id=model_id,
                resolved_model_id=model_id,
                provider_name="fixture-provider",
                finish_reason="stop",
                latency_ms=1,
                retry_count=0,
                http_attempts=1,
            )

    provider = RecordingProvider()
    prefix = next(item for item in histories if item.history_id == script.history_id)
    record = ConversationRunner(provider, store).run_or_resume(
        header=store.load(row.run_id).header,
        script=script,
        prefix=prefix,
        require_stop_finish_reason=True,
    )
    assert len(provider.calls) == 1
    assert provider.calls[0][-2].role == "assistant"
    assert provider.calls[0][-2].content == "Saved fixture response 5."
    assert len(record.turns) == 6
    validated = validate_finish_metadata_amendment(
        load_runtime_amendments(path).amendments[0], store=store
    )
    assert amendment_provenance(record.turns[5], preceding_amendments=(validated,))[
        "conditioned_on_technical_amendment_ids"
    ] == ("test-finish-metadata-amendment",)
    for saved_path, content in saved.items():
        assert saved_path.read_bytes() == content
    with pytest.raises(FileExistsError):
        store.append_success(record.turns[0])


def test_current_saved_event_and_next_request_are_exact_when_private_evidence_exists() -> None:
    paths = {
        "raw": ROOT / "data/raw/study-v2",
        "amendments": ROOT / "config/main-study-runtime-amendments.yaml",
        "state": ROOT / "data/private/main-study-job/state.json",
    }
    affected = paths["raw"] / CURRENT_RUN_ID / "turn-05-success.json"
    if not affected.is_file():
        pytest.skip("Private Study V2 evidence is not present in this checkout")
    store = RawRunStore(paths["raw"])
    before = affected.read_bytes()
    amendment = load_runtime_amendments(paths["amendments"]).amendments[0]
    validated = validate_finish_metadata_amendment(amendment, store=store)
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=paths["raw"],
        state_path=paths["state"],
    )
    request = next_study_request(repository_root=ROOT, raw_root=paths["raw"])

    assert validated.amendment_id == "finish-metadata-unreported-20260831-001"
    assert sha256_file(affected) == CURRENT_RAW_HASH
    assert affected.read_bytes() == before
    assert progress.responses_complete == 65
    assert progress.truncations == 0
    assert progress.approved_finish_metadata_anomalies == 1
    assert progress.finish_metadata_status_counts["unreported"] == 1
    assert request is not None
    assert request.run_id == CURRENT_RUN_ID
    assert request.turn_number == 6
    assert request.request_payload_hash == CURRENT_TURN_6_HASH
    assert store.successful_turns(CURRENT_RUN_ID)[4].event_id == CURRENT_EVENT_ID
