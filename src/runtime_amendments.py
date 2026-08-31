"""Validate narrowly scoped technical amendments to saved study evidence."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from src.payloads import assert_target_payload_clean
from src.schemas import (
    ChatMessage,
    ContextCondition,
    HistoryPrefix,
    ObservationStatus,
    RunHeader,
    StrictModel,
    TurnEvent,
)
from src.storage import RawRunStore

AMENDMENTS_VERSION = "main-study-runtime-amendments-v1.0.0"
FINISH_METADATA_UNREPORTED = "finish_metadata_unreported"


class RuntimeAmendmentError(ValueError):
    """A runtime amendment does not match the immutable raw evidence."""


class ExternalGenerationVerification(StrictModel):
    source: Literal["OpenRouter generation metadata GET"]
    generation_id: str
    model: str
    provider_name: str
    cancelled: Literal[False]
    tokens_prompt: int = Field(gt=0)
    tokens_completion: int = Field(gt=0)
    native_tokens_prompt: int = Field(gt=0)
    native_tokens_completion: int = Field(gt=0)
    finish_reason: None = None
    native_finish_reason: None = None
    latency: int = Field(ge=0)
    generation_time: int = Field(ge=0)


class FinishMetadataAmendment(StrictModel):
    amendment_id: str
    classification: Literal["finish_metadata_unreported"]
    approved_for_trajectory_continuation: Literal[True]
    study_version: str
    run_id: str
    turn_number: int = Field(ge=1, le=6)
    raw_filename: str
    raw_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str
    request_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_id: str
    requested_model_id: str
    resolved_model_id: str
    provider_name: str
    choice_count: Literal[1]
    content_present: Literal[True]
    completion_tokens: int = Field(gt=0)
    completion_envelope_tokens: int = Field(gt=0)
    external_verification: ExternalGenerationVerification

    @model_validator(mode="after")
    def require_consistent_identity(self) -> FinishMetadataAmendment:
        if self.requested_model_id != self.resolved_model_id:
            raise ValueError("An amendment cannot approve a resolved-model mismatch")
        if self.raw_filename != f"turn-{self.turn_number:02d}-success.json":
            raise ValueError("Amendment filename does not match its turn number")
        external = self.external_verification
        if external.generation_id != self.generation_id:
            raise ValueError("External generation ID does not match the amendment")
        if external.provider_name != self.provider_name:
            raise ValueError("External provider does not match the amendment")
        if external.tokens_completion != self.completion_tokens:
            raise ValueError("External completion usage does not match the amendment")
        return self


class RuntimeAmendments(StrictModel):
    version: Literal["main-study-runtime-amendments-v1.0.0"]
    amendments: tuple[FinishMetadataAmendment, ...]

    @model_validator(mode="after")
    def require_unique_observations(self) -> RuntimeAmendments:
        keys = [(item.run_id, item.turn_number) for item in self.amendments]
        ids = [item.amendment_id for item in self.amendments]
        if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
            raise ValueError("Runtime amendments must identify unique observations")
        return self


class ValidatedFinishMetadataAmendment(StrictModel):
    amendment_id: str
    run_id: str
    turn_number: int
    classification: Literal["finish_metadata_unreported"]
    raw_file_sha256: str


class FinishMetadataAudit(StrictModel):
    status_counts: dict[str, int]
    approved_anomaly_count: int
    unapproved_anomaly_count: int
    amendment_ids: tuple[str, ...]
    validation_errors: tuple[str, ...] = ()

    @property
    def hard_blocked(self) -> bool:
        return bool(self.unapproved_anomaly_count or self.validation_errors)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime_target_messages(
    *,
    condition: ContextCondition,
    prefix: HistoryPrefix | None,
    completed_exchanges: Sequence[tuple[str, str]],
    current_user_message: str,
    visible_response_instruction: str | None = None,
) -> tuple[ChatMessage, ...]:
    """Build an exact request while checking only study-authored text for cue leakage."""

    if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT and prefix is None:
        raise ValueError("The standardised context condition requires its frozen prefix")
    messages: list[ChatMessage] = []
    controlled: list[ChatMessage] = []

    def add(message: ChatMessage, *, study_controlled: bool) -> None:
        messages.append(message)
        if study_controlled:
            controlled.append(message)

    if visible_response_instruction:
        add(
            ChatMessage(role="system", content=visible_response_instruction),
            study_controlled=True,
        )
    if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT:
        for message in prefix.messages:  # type: ignore[union-attr]
            add(message, study_controlled=True)
    for user_message, assistant_response in completed_exchanges:
        add(ChatMessage(role="user", content=user_message), study_controlled=True)
        add(ChatMessage(role="assistant", content=assistant_response), study_controlled=False)
    add(ChatMessage(role="user", content=current_user_message), study_controlled=True)

    assert_target_payload_clean(controlled)
    return tuple(messages)


@contextmanager
def use_runtime_target_message_builder() -> Iterator[None]:
    """Apply the runtime builder to the frozen conversation runner for one collection pass."""

    import src.conversation_runner as conversation_runner

    original = conversation_runner.build_target_messages
    conversation_runner.build_target_messages = build_runtime_target_messages
    try:
        yield
    finally:
        conversation_runner.build_target_messages = original


def load_runtime_amendments(path: str | Path) -> RuntimeAmendments:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        return RuntimeAmendments.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as error:
        raise RuntimeAmendmentError("Runtime amendment configuration is invalid") from error


def finish_metadata_status(event: TurnEvent) -> str:
    reason = event.result.finish_reason
    if reason is None or not reason.strip():
        return "unreported"
    normalised = reason.strip().casefold()
    if normalised == "stop":
        return "reported_stop"
    if normalised == "length":
        return "reported_length"
    return "reported_other"


def _event_path(store: RawRunStore, amendment: FinishMetadataAmendment) -> Path:
    return store.run_directory(amendment.run_id) / amendment.raw_filename


def validate_finish_metadata_amendment(
    amendment: FinishMetadataAmendment,
    *,
    store: RawRunStore,
) -> ValidatedFinishMetadataAmendment:
    path = _event_path(store, amendment)
    header_path = store.run_directory(amendment.run_id) / "run.json"
    try:
        if sha256_file(path) != amendment.raw_file_sha256:
            raise RuntimeAmendmentError("Raw evidence hash does not match the amendment")
        event = TurnEvent.model_validate_json(path.read_text(encoding="utf-8"))
        header = RunHeader.model_validate_json(header_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        if isinstance(error, RuntimeAmendmentError):
            raise
        raise RuntimeAmendmentError("Amended raw evidence is missing or malformed") from error

    result = event.result
    metadata = result.response_metadata
    usage = result.usage
    checks = {
        "study version": header.study_version == amendment.study_version,
        "run ID": event.run_id == amendment.run_id == header.run_id,
        "turn number": event.turn_number == amendment.turn_number,
        "event ID": event.event_id == amendment.event_id,
        "request payload hash": event.request_payload_hash == amendment.request_payload_hash,
        "generation ID": result.generation_id == amendment.generation_id,
        "requested model": (
            event.request_model_id
            == result.requested_model_id
            == amendment.requested_model_id
            == header.requested_model_id
        ),
        "resolved model": result.resolved_model_id == amendment.resolved_model_id,
        "requested/resolved identity": (result.requested_model_id == result.resolved_model_id),
        "provider": result.provider_name == amendment.provider_name,
        "response status": result.status == ObservationStatus.RESPONSE,
        "non-empty content": bool((result.text or "").strip()),
        "choice count": metadata.get("choice_count") == amendment.choice_count == 1,
        "content presence": metadata.get("content_present") is True,
        "result finish reason": result.finish_reason is None,
        "metadata finish reason": metadata.get("finish_reason") is None,
        "native finish reason": metadata.get("native_finish_reason") is None,
        "not truncated": result.truncated is False,
        "completion usage present": usage is not None and usage.completion_tokens is not None,
        "completion usage exact": (
            usage is not None and usage.completion_tokens == amendment.completion_tokens
        ),
        "completion usage positive": (
            usage is not None
            and usage.completion_tokens is not None
            and usage.completion_tokens > 0
        ),
        "completion below envelope": (
            usage is not None
            and usage.completion_tokens is not None
            and usage.completion_tokens < amendment.completion_envelope_tokens
            and amendment.completion_envelope_tokens
            == header.generation_config.completion_envelope_tokens
        ),
        "no stored error": result.error_type is None and result.error_message is None,
        "external generation ID": (
            amendment.external_verification.generation_id == result.generation_id
        ),
        "external provider": (
            amendment.external_verification.provider_name == result.provider_name
        ),
        "external prompt usage": (
            usage is not None
            and usage.prompt_tokens == amendment.external_verification.tokens_prompt
            and amendment.external_verification.native_tokens_prompt
            == amendment.external_verification.tokens_prompt
        ),
        "external completion usage": (
            usage is not None
            and usage.completion_tokens == amendment.external_verification.tokens_completion
            and amendment.external_verification.native_tokens_completion
            == amendment.external_verification.tokens_completion
        ),
        "external finish metadata": (
            amendment.external_verification.finish_reason is None
            and amendment.external_verification.native_finish_reason is None
        ),
        "external not cancelled": amendment.external_verification.cancelled is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeAmendmentError(
            "Runtime amendment does not match immutable evidence: " + ", ".join(failed)
        )
    return ValidatedFinishMetadataAmendment(
        amendment_id=amendment.amendment_id,
        run_id=amendment.run_id,
        turn_number=amendment.turn_number,
        classification=amendment.classification,
        raw_file_sha256=amendment.raw_file_sha256,
    )


def audit_finish_metadata(
    *,
    store: RawRunStore,
    amendments_path: str | Path,
) -> FinishMetadataAudit:
    config = load_runtime_amendments(amendments_path)
    configured = {(item.run_id, item.turn_number): item for item in config.amendments}
    statuses: Counter[str] = Counter()
    approved: list[str] = []
    unapproved = 0
    errors: list[str] = []

    for run_id in store.list_run_ids():
        for event in store.successful_turns(run_id):
            status = finish_metadata_status(event)
            statuses[status] += 1
            amendment = configured.get((run_id, event.turn_number))
            if amendment is not None:
                try:
                    validated = validate_finish_metadata_amendment(amendment, store=store)
                except RuntimeAmendmentError as error:
                    errors.append(str(error))
                else:
                    approved.append(validated.amendment_id)
                continue
            if status != "reported_stop":
                unapproved += 1

    return FinishMetadataAudit(
        status_counts=dict(statuses),
        approved_anomaly_count=len(approved),
        unapproved_anomaly_count=unapproved,
        amendment_ids=tuple(approved),
        validation_errors=tuple(errors),
    )


def amendment_provenance(
    event: TurnEvent,
    *,
    validated: ValidatedFinishMetadataAmendment | None = None,
    preceding_amendments: tuple[ValidatedFinishMetadataAmendment, ...] = (),
) -> dict[str, str | bool | None | tuple[str, ...]]:
    """Return content-free fields for a later derived response table."""

    return {
        "finish_metadata_status": finish_metadata_status(event),
        "technical_amendment_id": validated.amendment_id if validated else None,
        "technical_amendment_applied": validated is not None,
        "conditioned_on_technical_amendment_ids": tuple(
            item.amendment_id
            for item in preceding_amendments
            if item.run_id == event.run_id and item.turn_number < event.turn_number
        ),
    }
