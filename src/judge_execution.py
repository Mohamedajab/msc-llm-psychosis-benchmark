"""Concurrent, resumable collection for the three supplementary LLM judges."""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.annotation import AnnotationStore, build_blinded_items
from src.config_loader import (
    canonical_hash,
    configuration_bundle_hash,
    load_histories,
    load_models,
    load_rubric,
    load_scripts,
)
from src.judge import (
    JUDGE_VERSION,
    JudgeOutput,
    JudgeRationales,
    build_blinded_judge_messages,
    judge_json_schema,
    parse_judge_output,
)
from src.schemas import AxisScores, BlindedAnnotationItem, ConversationRecord
from src.storage import RawRunStore, atomic_write_json, safe_filename

EXPECTED_ITEMS = 432
LEGACY_JUDGE_VERSION = "llm-judge-v1.0.0"
LEGACY_JUDGE_CONFIGURATION_HASH = (
    "136e5d46abda65b4e65574ab255c347d66ec0d09645c095df8767107f4f6bb8a"
)
LEGACY_DEEPSEEK_CONFIGURATIONS = frozenset(
    {
        (LEGACY_JUDGE_VERSION, LEGACY_JUDGE_CONFIGURATION_HASH),
        ("llm-judge-v1.0.1", "0edde5def66438de75714fece3163c7da9843d8b1483f800f5bd0edfacf3070d"),
    }
)
TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
PERMANENT_HTTP_CODES = frozenset({400, 401, 402, 403, 404, 405, 409, 422})
EXPECTED_JUDGES = {
    "deepseek-v4-pro": (
        "deepseek-v4-pro",
        "DeepSeek direct API",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
    ),
    "deepseek-v4-flash": (
        "deepseek-v4-flash",
        "DeepSeek direct API",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
    ),
    "glm-5.3-flash": (
        "z-ai/glm-5.3-flash",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
    ),
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class JudgeExecutionError(RuntimeError):
    """Raised when judge collection cannot proceed safely."""


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    judge_id: str
    display_name: str
    model_id: str
    api_provider: str
    base_url: str
    api_key_environment_variable: str
    concurrency: int = Field(ge=1, le=32)
    reasoning_mode: Literal["disabled", "none", "low"]
    max_tokens: int | None = Field(default=None, ge=256, le=8192)


class JudgeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    rubric_version: str
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=256, le=2048)
    request_timeout_seconds: int = Field(ge=10, le=600)
    maximum_attempts_per_item: int = Field(ge=1, le=10)
    retry_delays_seconds: tuple[float, ...]
    judges: tuple[JudgeSpec, ...]

    @model_validator(mode="after")
    def require_frozen_judges(self) -> JudgeConfiguration:
        if self.version != JUDGE_VERSION:
            raise ValueError(f"Judge configuration must use {JUDGE_VERSION}")
        if set(spec.judge_id for spec in self.judges) != set(EXPECTED_JUDGES):
            raise ValueError("Judge configuration must contain exactly the three frozen judges")
        if len({spec.judge_id for spec in self.judges}) != len(self.judges):
            raise ValueError("Judge IDs must be unique")
        for spec in self.judges:
            expected = EXPECTED_JUDGES[spec.judge_id]
            actual = (
                spec.model_id,
                spec.api_provider,
                spec.base_url.rstrip("/"),
                spec.api_key_environment_variable,
            )
            if actual != expected:
                raise ValueError(f"Frozen provider details do not match {spec.judge_id}")
        if self.temperature != 0:
            raise ValueError("Judge temperature must remain 0")
        if len(self.retry_delays_seconds) != self.maximum_attempts_per_item - 1:
            raise ValueError("Retry schedule must contain one delay per possible retry")
        if any(delay < 0 or delay > 60 for delay in self.retry_delays_seconds):
            raise ValueError("Judge retry delays must be between 0 and 60 seconds")
        return self


class JudgeUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_miss_input_tokens: int | None = Field(default=None, ge=0)
    reported_cost_usd: float | None = Field(default=None, ge=0)


class JudgeSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    judge_configuration_version: str
    judge_configuration_hash: str
    rubric_version: str
    rubric_hash: str
    blinded_item_id: str
    source_response_hash: str
    request_hash: str
    judge_id: str
    requested_model_id: str
    resolved_model_id: str
    api_provider: str
    resolved_provider: str | None = None
    scores: AxisScores
    rationale: JudgeRationales
    timestamp: datetime
    latency_ms: float = Field(ge=0)
    usage: JudgeUsage
    request_attempts: int = Field(ge=1)
    retry_count: int = Field(ge=0)
    finish_reason: Literal["stop"]
    response_status: Literal["SUCCESS"] = "SUCCESS"
    generation_id: str | None = None

    @model_validator(mode="after")
    def require_complete_exact_result(self) -> JudgeSuccess:
        if not self.scores.complete():
            raise ValueError("Successful judge result must contain all rubric scores")
        if self.resolved_model_id != self.requested_model_id:
            raise ValueError("Successful judge result contains a resolved-model mismatch")
        return self


class JudgeErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    event_id: str
    judge_configuration_version: str
    blinded_item_id: str
    source_response_hash: str
    request_hash: str
    judge_id: str
    requested_model_id: str
    api_provider: str
    timestamp: datetime
    attempt_number: int = Field(ge=1)
    retryable: bool
    error_type: str
    http_status: int | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0)
    response_status: Literal["RETRYABLE_ERROR", "PERMANENT_ERROR"]


class JudgeJobState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "NOT_STARTED",
        "RUNNING",
        "STOPPING",
        "STOPPED",
        "INCOMPLETE",
        "COMPLETE",
        "SMOKE_COMPLETE",
        "FAILED",
    ] = "NOT_STARTED"
    selected_judges: tuple[str, ...] = ()
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    in_flight: dict[str, int] = Field(default_factory=dict)
    retries: dict[str, int] = Field(default_factory=dict)
    concurrency: dict[str, int] = Field(default_factory=dict)
    message: str = "Judge collection has not started."
    worker_pid: int | None = None


class JudgeProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judge_id: str
    display_name: str
    completed: int
    planned: int = EXPECTED_ITEMS
    retries: int
    retryable_errors: int
    permanent_errors: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reported_cost_usd: float


class JudgePreflight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    checks: dict[str, bool]
    blockers: tuple[str, ...]
    item_count: int
    selected_judges: tuple[str, ...]
    network_requests: int = 0


class RequestFailure(Exception):
    def __init__(
        self,
        error_type: str,
        *,
        retryable: bool,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.retryable = retryable
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


def load_judge_configuration(path: str | Path) -> JudgeConfiguration:
    source = Path(path)
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
        return JudgeConfiguration.model_validate(value)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise JudgeExecutionError(f"Invalid judge configuration: {source}") from error


def judge_configuration_hash(configuration: JudgeConfiguration) -> str:
    return canonical_hash(configuration)


def default_judge_paths(repository_root: str | Path) -> dict[str, Path]:
    root = Path(repository_root)
    data_root = Path(os.getenv("BENCHMARK_DATA_DIR", str(root / "data")))
    return {
        "configuration": root / "config" / "llm-judges.yaml",
        "raw_study": data_root / "raw" / "study-v2",
        "annotation_log": data_root / "annotations" / "annotations.jsonl",
        "judge_root": data_root / "private" / "judges",
    }


def _load_study_records(raw_root: Path) -> list[ConversationRecord]:
    store = RawRunStore(raw_root)
    records = [store.load(run_id) for run_id in store.list_run_ids()]
    records = [record for record in records if record.header.data_status == "main_study"]
    if len(records) != 72 or sum(len(record.turns) for record in records) != EXPECTED_ITEMS:
        raise JudgeExecutionError("Judge collection requires 72 complete main-study conversations")
    return records


def load_blinded_judge_items(
    *, repository_root: str | Path, raw_root: str | Path
) -> tuple[list[BlindedAnnotationItem], str]:
    root = Path(repository_root)
    scripts = load_scripts(root / "config" / "scenarios")
    histories = load_histories(root / "config" / "histories")
    models = load_models(root / "config" / "models.yaml")
    bundle_hash = configuration_bundle_hash(scripts, histories, models)
    key = os.getenv("ANNOTATION_BLINDING_KEY") or f"local-prototype-{bundle_hash}"
    items, _ = build_blinded_items(_load_study_records(Path(raw_root)), blinding_key=key)
    unique_ids = {item.blinded_item_id for item in items}
    if len(items) != EXPECTED_ITEMS or len(unique_ids) != EXPECTED_ITEMS:
        raise JudgeExecutionError("Expected exactly 432 unique blinded main-study items")
    return items, bundle_hash


def select_judges(
    configuration: JudgeConfiguration, judge_ids: Sequence[str] | None = None
) -> tuple[JudgeSpec, ...]:
    requested = tuple(judge_ids or (spec.judge_id for spec in configuration.judges))
    if not requested or len(requested) != len(set(requested)):
        raise JudgeExecutionError("Selected judge IDs must be non-empty and unique")
    by_id = {spec.judge_id: spec for spec in configuration.judges}
    try:
        return tuple(by_id[judge_id] for judge_id in requested)
    except KeyError as error:
        raise JudgeExecutionError(f"Unknown judge ID: {error.args[0]}") from error


def _success_path(judge_root: Path, spec: JudgeSpec, item_id: str) -> Path:
    return judge_root / spec.judge_id / "successes" / f"{safe_filename(item_id)}.json"


def _error_directory(judge_root: Path, spec: JudgeSpec) -> Path:
    return judge_root / spec.judge_id / "errors"


def request_hash_for_item(
    *,
    item: BlindedAnnotationItem,
    rubric: Any,
    configuration: JudgeConfiguration,
    spec: JudgeSpec,
) -> tuple[str, tuple[Any, ...]]:
    messages = build_blinded_judge_messages(
        conversation_context=item.conversation_context,
        response_to_score=item.response_to_score,
        rubric=rubric,
    )
    payload = {
        "request_body": _request_body(
            spec=spec,
            configuration=configuration,
            messages=messages,
        ),
        "judge_configuration_hash": judge_configuration_hash(configuration),
        "rubric_hash": canonical_hash(rubric),
    }
    return canonical_hash(payload), messages


def load_successes(
    *,
    judge_root: str | Path,
    spec: JudgeSpec,
    configuration: JudgeConfiguration,
    items: Sequence[BlindedAnnotationItem] | None = None,
    rubric: Any | None = None,
) -> dict[str, JudgeSuccess]:
    root = Path(judge_root)
    expected_items = {item.blinded_item_id: item for item in items or ()}
    successes: dict[str, JudgeSuccess] = {}
    for path in sorted((root / spec.judge_id / "successes").glob("*.json")):
        try:
            result = JudgeSuccess.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise JudgeExecutionError(f"Malformed judge success: {path}") from error
        if result.blinded_item_id in successes:
            raise JudgeExecutionError("Duplicate judge success found for one blinded item")
        current_configuration = (
            result.judge_configuration_version == configuration.version
            and result.judge_configuration_hash == judge_configuration_hash(configuration)
        )
        legacy_deepseek_configuration = (
            spec.api_provider == "DeepSeek direct API"
            and (
                result.judge_configuration_version,
                result.judge_configuration_hash,
            )
            in LEGACY_DEEPSEEK_CONFIGURATIONS
        )
        if (
            not (current_configuration or legacy_deepseek_configuration)
            or result.judge_id != spec.judge_id
            or result.requested_model_id != spec.model_id
            or result.resolved_model_id != spec.model_id
            or result.rubric_version != configuration.rubric_version
        ):
            raise JudgeExecutionError(f"Judge success metadata mismatch: {path}")
        if expected_items:
            item = expected_items.get(result.blinded_item_id)
            if item is None or item.source_response_hash != result.source_response_hash:
                raise JudgeExecutionError(f"Judge success does not match blinded source: {path}")
            if rubric is not None:
                if legacy_deepseek_configuration:
                    messages = build_blinded_judge_messages(
                        conversation_context=item.conversation_context,
                        response_to_score=item.response_to_score,
                        rubric=rubric,
                    )
                    expected_hash = canonical_hash(
                        {
                            "request_body": _request_body(
                                spec=spec,
                                configuration=configuration,
                                messages=messages,
                            ),
                            "judge_configuration_hash": result.judge_configuration_hash,
                            "rubric_hash": canonical_hash(rubric),
                        }
                    )
                else:
                    expected_hash, _ = request_hash_for_item(
                        item=item,
                        rubric=rubric,
                        configuration=configuration,
                        spec=spec,
                    )
                if (
                    result.rubric_hash != canonical_hash(rubric)
                    or result.request_hash != expected_hash
                ):
                    raise JudgeExecutionError(f"Judge success request hash mismatch: {path}")
        successes[result.blinded_item_id] = result
    return successes


def load_errors(judge_root: str | Path, spec: JudgeSpec) -> list[JudgeErrorEvent]:
    events: list[JudgeErrorEvent] = []
    for path in sorted(_error_directory(Path(judge_root), spec).glob("*.json")):
        try:
            events.append(JudgeErrorEvent.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValidationError, ValueError) as error:
            raise JudgeExecutionError(f"Malformed judge error: {path}") from error
    return events


def save_success(judge_root: Path, spec: JudgeSpec, result: JudgeSuccess) -> Path:
    return atomic_write_json(
        _success_path(judge_root, spec, result.blinded_item_id), result.model_dump(mode="json")
    )


def save_error(judge_root: Path, spec: JudgeSpec, event: JudgeErrorEvent) -> Path:
    directory = _error_directory(judge_root, spec)
    name = (
        f"{safe_filename(event.blinded_item_id)}-attempt-{event.attempt_number:02d}-"
        f"{event.event_id}.json"
    )
    return atomic_write_json(directory / name, event.model_dump(mode="json"))


def load_job_state(judge_root: str | Path) -> JudgeJobState:
    path = Path(judge_root) / "job-state.json"
    if not path.is_file():
        return JudgeJobState()
    try:
        return JudgeJobState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as error:
        raise JudgeExecutionError("Judge job state is malformed") from error


def save_job_state(judge_root: str | Path, state: JudgeJobState) -> Path:
    return atomic_write_json(
        Path(judge_root) / "job-state.json", state.model_dump(mode="json"), overwrite=True
    )


def judge_progress(
    *, judge_root: str | Path, configuration: JudgeConfiguration
) -> tuple[JudgeProgress, ...]:
    rows: list[JudgeProgress] = []
    for spec in configuration.judges:
        successes = load_successes(
            judge_root=judge_root,
            spec=spec,
            configuration=configuration,
        )
        errors = load_errors(judge_root, spec)
        rows.append(
            JudgeProgress(
                judge_id=spec.judge_id,
                display_name=spec.display_name,
                completed=len(successes),
                retries=sum(max(0, result.retry_count) for result in successes.values()),
                retryable_errors=sum(event.retryable for event in errors),
                permanent_errors=sum(not event.retryable for event in errors),
                input_tokens=sum(result.usage.input_tokens or 0 for result in successes.values()),
                output_tokens=sum(result.usage.output_tokens or 0 for result in successes.values()),
                total_tokens=sum(result.usage.total_tokens or 0 for result in successes.values()),
                reported_cost_usd=sum(
                    result.usage.reported_cost_usd or 0 for result in successes.values()
                ),
            )
        )
    return tuple(rows)


def human_annotation_complete(*, annotation_path: str | Path, item_ids: set[str]) -> bool:
    events = AnnotationStore(annotation_path).latest_events()
    human_by_annotator: dict[str, set[str]] = {}
    for event in events:
        if event.annotation_method == "human" and event.scores.complete():
            human_by_annotator.setdefault(event.annotator_id, set()).add(event.blinded_item_id)
    return any(item_ids.issubset(ids) for ids in human_by_annotator.values())


def run_judge_preflight(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    judge_root: str | Path,
    configuration_path: str | Path,
    judge_ids: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    require_smoke_validation: bool = False,
) -> JudgePreflight:
    blockers: list[str] = []
    checks: dict[str, bool] = {}
    values = os.environ if environ is None else environ
    try:
        configuration = load_judge_configuration(configuration_path)
        specs = select_judges(configuration, judge_ids)
        checks["configuration_valid"] = True
    except (OSError, ValueError, JudgeExecutionError):
        return JudgePreflight(
            ready=False,
            checks={"configuration_valid": False},
            blockers=("judge_configuration_invalid",),
            item_count=0,
            selected_judges=tuple(judge_ids or ()),
        )
    rubric = load_rubric(Path(repository_root) / "config" / "rubric.yaml")
    checks["rubric_frozen"] = (
        rubric.version == configuration.rubric_version and rubric.status == "FROZEN"
    )
    if not checks["rubric_frozen"]:
        blockers.append("rubric_not_frozen")
    try:
        items, _ = load_blinded_judge_items(
            repository_root=repository_root,
            raw_root=raw_root,
        )
        checks["study_complete"] = len(items) == EXPECTED_ITEMS
    except (OSError, ValueError, JudgeExecutionError):
        items = []
        checks["study_complete"] = False
    if not checks["study_complete"]:
        blockers.append("main_study_not_complete")
    checks["api_keys_available"] = all(
        bool(values.get(spec.api_key_environment_variable, "").strip()) for spec in specs
    )
    if not checks["api_keys_available"]:
        blockers.append("judge_api_key_not_available")
    checks["no_active_worker"] = not worker_is_active(judge_root)
    if not checks["no_active_worker"]:
        blockers.append("judge_worker_already_running")
    smoke_counts: dict[str, int] = {}
    if items:
        try:
            for spec in specs:
                successes = load_successes(
                    judge_root=judge_root,
                    spec=spec,
                    configuration=configuration,
                    items=items,
                    rubric=rubric,
                )
                smoke_counts[spec.judge_id] = len(successes)
            checks["saved_results_valid"] = True
        except (OSError, ValueError, JudgeExecutionError):
            checks["saved_results_valid"] = False
            blockers.append("saved_judge_results_invalid")
    else:
        checks["saved_results_valid"] = False
    if require_smoke_validation:
        checks["smoke_validation_complete"] = all(
            smoke_counts.get(spec.judge_id, 0) >= 1 for spec in specs
        )
        if not checks["smoke_validation_complete"]:
            blockers.append("judge_smoke_validation_not_complete")
    return JudgePreflight(
        ready=all(checks.values()),
        checks=checks,
        blockers=tuple(dict.fromkeys(blockers)),
        item_count=len(items),
        selected_judges=tuple(spec.judge_id for spec in specs),
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0, (parsed - utc_now()).total_seconds())
        except (TypeError, ValueError):
            return None


def _usage_from_response(payload: Mapping[str, Any]) -> JudgeUsage:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return JudgeUsage()
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, Mapping) else {}
    cost = usage.get("cost")
    return JudgeUsage(
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        reasoning_tokens=details.get("reasoning_tokens"),
        cached_input_tokens=usage.get("prompt_cache_hit_tokens"),
        cache_miss_input_tokens=usage.get("prompt_cache_miss_tokens"),
        reported_cost_usd=cost if isinstance(cost, int | float) and cost >= 0 else None,
    )


def _request_body(
    *,
    spec: JudgeSpec,
    configuration: JudgeConfiguration,
    messages: Sequence[Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": spec.model_id,
        "messages": [message.model_dump(mode="json") for message in messages],
        "temperature": configuration.temperature,
        "max_tokens": spec.max_tokens or configuration.max_tokens,
        "stream": False,
    }
    if spec.api_provider == "DeepSeek direct API":
        body["response_format"] = {"type": "json_object"}
        body["thinking"] = {"type": "disabled"}
    else:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "llm_judge_rating",
                "strict": True,
                "schema": judge_json_schema(),
            },
        }
        body["reasoning"] = {
            "effort": spec.reasoning_mode,
            "exclude": True,
        }
        body["provider"] = {
            "allow_fallbacks": True,
            "require_parameters": True,
        }
    return body


async def _make_request(
    *,
    client: httpx.AsyncClient,
    spec: JudgeSpec,
    configuration: JudgeConfiguration,
    messages: Sequence[Any],
    api_key: str,
) -> tuple[JudgeOutput, dict[str, Any], float]:
    started = time.perf_counter()
    try:
        response = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=_request_body(spec=spec, configuration=configuration, messages=messages),
        )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
        raise RequestFailure(type(error).__name__, retryable=True) from error
    latency_ms = (time.perf_counter() - started) * 1000
    if response.status_code != 200:
        retryable = response.status_code in TRANSIENT_HTTP_CODES
        if response.status_code not in TRANSIENT_HTTP_CODES | PERMANENT_HTTP_CODES:
            retryable = response.status_code >= 500
        raise RequestFailure(
            f"http_{response.status_code}",
            retryable=retryable,
            http_status=response.status_code,
            retry_after_seconds=_retry_after_seconds(response),
        )
    try:
        payload = response.json()
        choices = payload.get("choices")
        choice = choices[0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise RequestFailure("malformed_provider_response", retryable=True) from error
    resolved_model = payload.get("model")
    if resolved_model != spec.model_id:
        raise RequestFailure("resolved_model_mismatch", retryable=False)
    if finish_reason != "stop":
        raise RequestFailure(f"finish_reason_{finish_reason or 'missing'}", retryable=True)
    if not isinstance(content, str) or not content.strip():
        raise RequestFailure("empty_judge_output", retryable=True)
    try:
        output = parse_judge_output(content)
    except ValueError as error:
        raise RequestFailure("malformed_judge_json", retryable=True) from error
    return output, payload, latency_ms


class AdaptiveLimiter:
    """A small adjustable request limiter for one judge queue."""

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.limit = maximum
        self.active = 0
        self.successes_since_change = 0
        self.condition = asyncio.Condition()

    async def acquire(self) -> None:
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1

    async def release(self, *, rate_limited: bool, success: bool) -> None:
        async with self.condition:
            self.active -= 1
            if rate_limited:
                self.limit = max(1, self.limit - 1)
                self.successes_since_change = 0
            elif success and self.limit < self.maximum:
                self.successes_since_change += 1
                if self.successes_since_change >= 20:
                    self.limit += 1
                    self.successes_since_change = 0
            self.condition.notify_all()


class RunMonitor:
    def __init__(self, judge_root: Path, specs: Sequence[JudgeSpec], *, smoke: bool) -> None:
        self.judge_root = judge_root
        self.lock = asyncio.Lock()
        now = utc_now()
        self.state = JudgeJobState(
            status="RUNNING",
            selected_judges=tuple(spec.judge_id for spec in specs),
            started_at=now,
            updated_at=now,
            in_flight={spec.judge_id: 0 for spec in specs},
            retries={spec.judge_id: 0 for spec in specs},
            concurrency={spec.judge_id: spec.concurrency for spec in specs},
            message="One-item validation is running." if smoke else "Judge collection is running.",
            worker_pid=os.getpid(),
        )
        save_job_state(judge_root, self.state)

    async def update(
        self,
        *,
        judge_id: str,
        in_flight_delta: int = 0,
        retry_delta: int = 0,
        concurrency: int | None = None,
    ) -> None:
        async with self.lock:
            values = self.state.model_dump()
            values["in_flight"][judge_id] += in_flight_delta
            values["retries"][judge_id] += retry_delta
            if concurrency is not None:
                values["concurrency"][judge_id] = concurrency
            values["updated_at"] = utc_now()
            self.state = JudgeJobState.model_validate(values)
            save_job_state(self.judge_root, self.state)

    def finish(self, status: str, message: str) -> None:
        now = utc_now()
        self.state = self.state.model_copy(
            update={
                "status": status,
                "updated_at": now,
                "finished_at": now,
                "in_flight": {judge_id: 0 for judge_id in self.state.in_flight},
                "message": message,
            }
        )
        save_job_state(self.judge_root, self.state)


def stop_requested(judge_root: str | Path) -> bool:
    return (Path(judge_root) / "stop.requested").is_file()


def request_safe_stop(judge_root: str | Path) -> None:
    path = Path(judge_root) / "stop.requested"
    if not path.exists():
        atomic_write_json(path, {"requested_at": utc_now().isoformat()})
    state = load_job_state(judge_root)
    if state.status == "RUNNING":
        save_job_state(
            judge_root,
            state.model_copy(
                update={
                    "status": "STOPPING",
                    "message": "Stopping after current requests finish.",
                    "updated_at": utc_now(),
                }
            ),
        )


def clear_stop_request(judge_root: str | Path) -> None:
    (Path(judge_root) / "stop.requested").unlink(missing_ok=True)


async def _judge_one_item(
    *,
    item: BlindedAnnotationItem,
    spec: JudgeSpec,
    configuration: JudgeConfiguration,
    rubric: Any,
    judge_root: Path,
    client: httpx.AsyncClient,
    api_key: str,
    limiter: AdaptiveLimiter,
    monitor: RunMonitor,
) -> bool:
    request_hash, messages = request_hash_for_item(
        item=item,
        rubric=rubric,
        configuration=configuration,
        spec=spec,
    )
    config_hash = judge_configuration_hash(configuration)
    for attempt in range(1, configuration.maximum_attempts_per_item + 1):
        if stop_requested(judge_root):
            return False
        await limiter.acquire()
        await monitor.update(
            judge_id=spec.judge_id,
            in_flight_delta=1,
            concurrency=limiter.limit,
        )
        failure: RequestFailure | None = None
        try:
            output, payload, latency_ms = await _make_request(
                client=client,
                spec=spec,
                configuration=configuration,
                messages=messages,
                api_key=api_key,
            )
        except RequestFailure as error:
            failure = error
        finally:
            await monitor.update(judge_id=spec.judge_id, in_flight_delta=-1)
        if failure is None:
            await limiter.release(rate_limited=False, success=True)
            success = JudgeSuccess(
                judge_configuration_version=configuration.version,
                judge_configuration_hash=config_hash,
                rubric_version=configuration.rubric_version,
                rubric_hash=canonical_hash(rubric),
                blinded_item_id=item.blinded_item_id,
                source_response_hash=item.source_response_hash,
                request_hash=request_hash,
                judge_id=spec.judge_id,
                requested_model_id=spec.model_id,
                resolved_model_id=payload["model"],
                api_provider=spec.api_provider,
                resolved_provider=payload.get("provider"),
                scores=output.scores,
                rationale=output.rationale.model_dump(),
                timestamp=utc_now(),
                latency_ms=latency_ms,
                usage=_usage_from_response(payload),
                request_attempts=attempt,
                retry_count=attempt - 1,
                finish_reason=payload["choices"][0]["finish_reason"],
                generation_id=payload.get("id"),
            )
            try:
                save_success(judge_root, spec, success)
            except FileExistsError as error:
                raise JudgeExecutionError(
                    f"Successful judgement already exists for {item.blinded_item_id}"
                ) from error
            return True
        rate_limited = failure.http_status == 429
        await limiter.release(rate_limited=rate_limited, success=False)
        save_error(
            judge_root,
            spec,
            JudgeErrorEvent(
                event_id=uuid.uuid4().hex,
                judge_configuration_version=configuration.version,
                blinded_item_id=item.blinded_item_id,
                source_response_hash=item.source_response_hash,
                request_hash=request_hash,
                judge_id=spec.judge_id,
                requested_model_id=spec.model_id,
                api_provider=spec.api_provider,
                timestamp=utc_now(),
                attempt_number=attempt,
                retryable=failure.retryable,
                error_type=failure.error_type,
                http_status=failure.http_status,
                retry_after_seconds=failure.retry_after_seconds,
                response_status=("RETRYABLE_ERROR" if failure.retryable else "PERMANENT_ERROR"),
            ),
        )
        if not failure.retryable or attempt >= configuration.maximum_attempts_per_item:
            return False
        await monitor.update(
            judge_id=spec.judge_id,
            retry_delta=1,
            concurrency=limiter.limit,
        )
        delay = configuration.retry_delays_seconds[attempt - 1]
        delay = max(delay, failure.retry_after_seconds or 0)
        delay += random.uniform(0, min(1.0, delay * 0.1))
        await asyncio.sleep(delay)
    return False


async def _run_judge_queue(
    *,
    spec: JudgeSpec,
    configuration: JudgeConfiguration,
    rubric: Any,
    items: Sequence[BlindedAnnotationItem],
    judge_root: Path,
    monitor: RunMonitor,
    smoke_one: bool,
) -> None:
    successes = load_successes(
        judge_root=judge_root,
        spec=spec,
        configuration=configuration,
        items=items,
        rubric=rubric,
    )
    pending = [item for item in items if item.blinded_item_id not in successes]
    if smoke_one:
        pending = pending[:1]
    if not pending:
        return
    queue: asyncio.Queue[BlindedAnnotationItem] = asyncio.Queue()
    for item in pending:
        queue.put_nowait(item)
    limiter = AdaptiveLimiter(spec.concurrency)
    api_key = os.environ.get(spec.api_key_environment_variable, "").strip()
    if not api_key:
        raise JudgeExecutionError(f"Missing API key for {spec.judge_id}")

    async with httpx.AsyncClient(
        base_url=spec.base_url.rstrip("/"),
        timeout=configuration.request_timeout_seconds,
        follow_redirects=False,
    ) as client:

        async def worker() -> None:
            while not queue.empty() and not stop_requested(judge_root):
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await _judge_one_item(
                        item=item,
                        spec=spec,
                        configuration=configuration,
                        rubric=rubric,
                        judge_root=judge_root,
                        client=client,
                        api_key=api_key,
                        limiter=limiter,
                        monitor=monitor,
                    )
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(spec.concurrency)))


async def run_judges(
    *,
    repository_root: str | Path,
    raw_root: str | Path,
    judge_root: str | Path,
    configuration_path: str | Path,
    judge_ids: Sequence[str] | None = None,
    smoke_one_each: bool = False,
) -> tuple[JudgeProgress, ...]:
    root = Path(repository_root)
    output_root = Path(judge_root)
    configuration = load_judge_configuration(configuration_path)
    specs = select_judges(configuration, judge_ids)
    rubric = load_rubric(root / "config" / "rubric.yaml")
    if rubric.version != configuration.rubric_version or rubric.status != "FROZEN":
        raise JudgeExecutionError("Frozen judge rubric does not match config/rubric.yaml")
    items, _ = load_blinded_judge_items(repository_root=root, raw_root=raw_root)
    monitor = RunMonitor(output_root, specs, smoke=smoke_one_each)
    try:
        await asyncio.gather(
            *(
                _run_judge_queue(
                    spec=spec,
                    configuration=configuration,
                    rubric=rubric,
                    items=items,
                    judge_root=output_root,
                    monitor=monitor,
                    smoke_one=smoke_one_each,
                )
                for spec in specs
            )
        )
        progress = judge_progress(judge_root=output_root, configuration=configuration)
        if stop_requested(output_root):
            monitor.finish("STOPPED", "Stopped safely; completed judgements were preserved.")
        elif smoke_one_each:
            expected = {spec.judge_id for spec in specs}
            passed = all(row.completed >= 1 for row in progress if row.judge_id in expected)
            monitor.finish(
                "SMOKE_COMPLETE" if passed else "INCOMPLETE",
                "One-item validation completed." if passed else "One-item validation failed.",
            )
        else:
            by_id = {row.judge_id: row for row in progress}
            complete = all(by_id[spec.judge_id].completed == EXPECTED_ITEMS for spec in specs)
            monitor.finish(
                "COMPLETE" if complete else "INCOMPLETE",
                "All selected judgements completed."
                if complete
                else "Some selected judgements remain missing.",
            )
        return progress
    except Exception:
        monitor.finish("FAILED", "Judge worker stopped after an error; saved results are intact.")
        raise


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_worker_lock(judge_root: str | Path) -> dict[str, Any] | None:
    path = Path(judge_root) / "worker.lock"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("token"), str) or not isinstance(value.get("pid"), int):
            raise ValueError
        return value
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise JudgeExecutionError("Judge worker lock is malformed") from error


def worker_is_active(judge_root: str | Path) -> bool:
    value = read_worker_lock(judge_root)
    if value is None:
        return False
    # A zero PID is a short-lived reservation while the subprocess starts.
    return value["pid"] == 0 or _process_running(value["pid"])


def reserve_worker(judge_root: str | Path) -> str:
    root = Path(judge_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "worker.lock"
    if lock_path.exists():
        if worker_is_active(root):
            raise JudgeExecutionError("An LLM judge worker is already running")
        lock_path.unlink()
    token = uuid.uuid4().hex
    atomic_write_json(
        lock_path,
        {"token": token, "pid": 0, "created_at": utc_now().isoformat()},
    )
    return token


def claim_worker(judge_root: str | Path, token: str) -> None:
    root = Path(judge_root)
    value = read_worker_lock(root)
    if value is None or value["token"] != token:
        raise JudgeExecutionError("Judge worker reservation is missing or stale")
    value["pid"] = os.getpid()
    atomic_write_json(root / "worker.lock", value, overwrite=True)


def release_worker(judge_root: str | Path, token: str) -> None:
    root = Path(judge_root)
    value = read_worker_lock(root)
    if value is not None and value["token"] == token:
        (root / "worker.lock").unlink(missing_ok=True)


def launch_judge_worker(
    *,
    repository_root: str | Path,
    judge_root: str | Path,
    raw_root: str | Path,
    configuration_path: str | Path,
    judge_ids: Sequence[str] | None = None,
) -> int:
    root = Path(repository_root)
    token = reserve_worker(judge_root)
    clear_stop_request(judge_root)
    command = [
        sys.executable,
        str(root / "scripts" / "run_judges.py"),
        "--live",
        "--confirm-live",
        "--lock-token",
        token,
        "--output-root",
        str(judge_root),
        "--raw-root",
        str(raw_root),
        "--configuration",
        str(configuration_path),
    ]
    for judge_id in judge_ids or ():
        command.extend(["--judge", judge_id])
    values = dict(os.environ)
    values["RUN_LIVE_JUDGES"] = "1"
    log_path = Path(judge_root) / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
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
        release_worker(judge_root, token)
        raise
    finally:
        log_handle.close()
    return process.pid
