"""Strict data contracts for the controlled multi-turn benchmark."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "2.0.0"


class StrictModel(BaseModel):
    """Reject undeclared fields so protocol drift fails early."""

    model_config = ConfigDict(extra="forbid")


class PresentationLevel(StrEnum):
    CONTROL = "control"
    AMBIGUOUS = "ambiguous"
    FIXED_BELIEF = "fixed_belief"


class Theme(StrEnum):
    MONITORING = "monitoring"
    PERSONAL_MESSAGES = "personal_messages"
    AI_RELATIONSHIP = "ai_relationship"


class ContextCondition(StrEnum):
    NO_PRELOADED_CONTEXT = "no_preloaded_context"
    STANDARDISED_PRELOADED_CONTEXT = "standardised_preloaded_context"


class RunStatus(StrEnum):
    PLANNED = "planned"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class ObservationStatus(StrEnum):
    RESPONSE = "response"
    TRANSPORT_ERROR = "transport_error"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"
    MISSING = "missing"


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ScriptConfig(StrictModel):
    schema_version: str
    script_id: str = Field(pattern=r"^[a-z0-9_]+$")
    script_version: str
    theme: Theme
    presentation_level: PresentationLevel
    title: str = Field(min_length=1)
    history_id: str = Field(min_length=1)
    turns: tuple[str, ...]
    content_boundaries: tuple[str, ...] = ()

    @field_validator("turns")
    @classmethod
    def require_six_nonblank_turns(cls, turns: tuple[str, ...]) -> tuple[str, ...]:
        if len(turns) != 6:
            raise ValueError("Every frozen script must contain exactly six user turns")
        if any(not turn.strip() for turn in turns):
            raise ValueError("Script turns cannot be blank")
        return turns


class HistoryPrefix(StrictModel):
    history_id: str = Field(min_length=1)
    version: str
    theme: Theme
    messages: tuple[ChatMessage, ...]

    @field_validator("messages")
    @classmethod
    def require_balanced_exchange(
        cls, messages: tuple[ChatMessage, ...]
    ) -> tuple[ChatMessage, ...]:
        if not messages or len(messages) % 2:
            raise ValueError("A prefix must contain complete user/assistant exchanges")
        expected = ["user" if index % 2 == 0 else "assistant" for index in range(len(messages))]
        if [message.role for message in messages] != expected:
            raise ValueError("Prefix roles must alternate user then assistant")
        return messages


class ModelSlot(StrictModel):
    default_model_id: str
    exact_slug_required: bool = True

    @field_validator("default_model_id")
    @classmethod
    def reject_router_aliases(cls, value: str) -> str:
        if value in {"openrouter/free", "openrouter/auto"} or "latest" in value:
            raise ValueError(
                "A concrete model slug is required; routers and latest aliases are forbidden"
            )
        if not value.endswith(":free"):
            raise ValueError("Target-model IDs must be exact free endpoints ending in :free")
        return value


class GenerationConfig(StrictModel):
    version: str
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1, le=4096)
    top_p: float = Field(gt=0, le=1)
    seed: int | None = None
    timeout_seconds: float = Field(gt=0, le=120)
    max_retries: int = Field(ge=0, le=5)

    def request_parameters(self) -> dict[str, int | float]:
        parameters: dict[str, int | float] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        if self.seed is not None:
            parameters["seed"] = self.seed
        return parameters


class ModelsConfig(StrictModel):
    version: str
    provider: Literal["openrouter"]
    catalogue_checked_at_utc: datetime
    catalogue_endpoint: str
    model_slots: dict[str, ModelSlot]
    generation: GenerationConfig
    repetition_seeds: dict[int, int]
    notes: tuple[str, ...] = ()

    @field_validator("model_slots")
    @classmethod
    def require_named_distinct_slots(cls, value: dict[str, ModelSlot]) -> dict[str, ModelSlot]:
        if not value:
            raise ValueError("At least one target-model slot is required")
        if any(not name.startswith("model_") for name in value):
            raise ValueError("Target-model slot names must begin with model_")
        defaults = [slot.default_model_id for slot in value.values()]
        if len(set(defaults)) != len(defaults):
            raise ValueError("Target-model slots must use distinct default model IDs")
        return value

    @field_validator("repetition_seeds")
    @classmethod
    def require_distinct_repetition_seeds(cls, value: dict[int, int]) -> dict[int, int]:
        if set(value) != {1, 2}:
            raise ValueError("Seeds must be prespecified for repetitions 1 and 2")
        if value[1] == value[2]:
            raise ValueError("Repetitions 1 and 2 must use different seeds")
        return value


class ManifestRow(StrictModel):
    schema_version: str = SCHEMA_VERSION
    study_version: str
    run_id: str
    script_id: str
    theme: Theme
    presentation_level: PresentationLevel
    model_slot: str = Field(pattern=r"^model_[a-z0-9_]+$")
    requested_model_id: str
    context_condition: ContextCondition
    repetition: int = Field(ge=1, le=2)
    generation_config_version: str
    planned_seed: int | None
    execution_order: int = Field(ge=1)
    status: RunStatus = RunStatus.PLANNED
    error_type: str = ""
    error_message: str = ""


class RunHeader(StrictModel):
    schema_version: str = SCHEMA_VERSION
    study_version: str
    run_id: str
    data_status: Literal["demo_fixture", "technical_pilot", "planned_study"]
    script_id: str
    script_version: str
    theme: Theme
    presentation_level: PresentationLevel
    context_condition: ContextCondition
    history_id: str | None
    model_slot: str
    requested_model_id: str
    provider: str
    provider_endpoint: str | None = None
    repetition: int = Field(ge=1)
    generation_config: GenerationConfig
    configuration_version: str
    configuration_hash: str
    created_at: datetime


class TokenUsage(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(StrictModel):
    status: ObservationStatus
    text: str | None = None
    requested_model_id: str
    resolved_model_id: str | None = None
    provider_name: str | None = None
    generation_id: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float = Field(ge=0)
    retry_count: int = Field(ge=0)
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def response_requires_text(self) -> ProviderResult:
        if self.status == ObservationStatus.RESPONSE and not (self.text or "").strip():
            raise ValueError("A successful response observation requires nonblank text")
        return self


class TurnEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    event_type: Literal["turn_success"] = "turn_success"
    event_id: str
    run_id: str
    turn_number: int = Field(ge=1, le=6)
    request_timestamp: datetime
    response_timestamp: datetime
    request_model_id: str
    request_messages: tuple[ChatMessage, ...]
    request_parameters: dict[str, int | float]
    request_stream: Literal[False] = False
    request_payload_hash: str
    user_message: str
    result: ProviderResult


class ErrorEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    event_type: Literal["turn_error"] = "turn_error"
    event_id: str
    run_id: str
    turn_number: int = Field(ge=1, le=6)
    timestamp: datetime
    request_model_id: str
    request_messages: tuple[ChatMessage, ...]
    request_parameters: dict[str, int | float]
    request_stream: Literal[False] = False
    request_payload_hash: str
    result: ProviderResult


class ConversationRecord(StrictModel):
    header: RunHeader
    turns: tuple[TurnEvent, ...]
    errors: tuple[ErrorEvent, ...] = ()
    status: RunStatus
    completed_at: datetime | None = None


class RubricAxis(StrictModel):
    id: Literal["A1", "A2", "A3", "B1", "B2", "B3", "C1"]
    name: str
    role: Literal["primary", "exploratory"]
    direction: Literal["risk", "protective"]
    definition: str
    anchors: dict[int, str]

    @field_validator("anchors")
    @classmethod
    def require_three_anchors(cls, anchors: dict[int, str]) -> dict[int, str]:
        if set(anchors) != {0, 1, 2}:
            raise ValueError("Every rubric axis requires anchors 0, 1, and 2")
        return anchors


class RubricConfig(StrictModel):
    version: str
    name: str
    status: str
    source_note: str
    scale: dict[str, Any]
    primary_axes: tuple[str, ...]
    safety_thresholds: dict[str, int]
    axes: tuple[RubricAxis, ...]

    @model_validator(mode="after")
    def require_exact_axes(self) -> RubricConfig:
        if [axis.id for axis in self.axes] != ["A1", "A2", "A3", "B1", "B2", "B3", "C1"]:
            raise ValueError("Rubric must contain the seven frozen axes in order")
        return self


class AxisScores(StrictModel):
    A1: int | None = Field(default=None, ge=0, le=2)
    A2: int | None = Field(default=None, ge=0, le=2)
    A3: int | None = Field(default=None, ge=0, le=2)
    B1: int | None = Field(default=None, ge=0, le=2)
    B2: int | None = Field(default=None, ge=0, le=2)
    B3: int | None = Field(default=None, ge=0, le=2)
    C1: int | None = Field(default=None, ge=0, le=2)

    def complete(self) -> bool:
        return all(value is not None for value in self.model_dump().values())


class AnnotationEvent(StrictModel):
    schema_version: str = SCHEMA_VERSION
    annotation_id: str
    blinded_item_id: str
    rating_round: Literal["initial", "rerating"] = "initial"
    annotator_id: str
    scores: AxisScores
    notes: str = ""
    uncertain_adjudication_needed: bool = False
    source_response_hash: str
    saved_at: datetime


class BlindedAnnotationItem(StrictModel):
    blinded_item_id: str
    rating_round: Literal["initial", "rerating"] = "initial"
    turn_number: int = Field(ge=1, le=6)
    conversation_context: tuple[ChatMessage, ...]
    response_to_score: str
    source_response_hash: str


class BlindingMapEntry(StrictModel):
    blinded_item_id: str
    run_id: str
    turn_number: int
    rating_round: Literal["initial", "rerating"]
