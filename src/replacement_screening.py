"""Guarded catalogue discovery and technical replacement-model screening.

This module deliberately keeps replacement discovery separate from Study V2.  It
never selects a model from response content and never mutates active study files.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.config_loader import (
    canonical_hash,
    generation_for_repetition,
    load_histories,
    load_models,
    load_scripts,
)
from src.conversation_runner import ConversationRunner, create_run_header, payload_hash
from src.generation_profiles import (
    GENERATION_V4_MAX_COMPLETION_TOKENS,
    GENERATION_V4_VERSION,
    require_generation_v4,
)
from src.payloads import build_target_messages
from src.provider_client import (
    TargetProvider,
    select_completion_limit_parameter,
)
from src.schemas import (
    ContextCondition,
    GenerationConfig,
    HistoryPrefix,
    ManifestRow,
    ObservationStatus,
    RunStatus,
    ScriptConfig,
    StrictModel,
)
from src.storage import RawRunStore, atomic_write_json, safe_filename
from src.study_execution import result_http_attempts, resume_or_new_header

CATALOGUE_ENDPOINT = "https://openrouter.ai/api/v1/models"
CATALOGUE_EVIDENCE_VERSION = "replacement-catalogue-v2.1.0"
SCREEN_VERSION = "replacement-screen-v2.1.0"
SCREEN_ASSESSMENT_VERSION = "replacement-screen-qualification-v2.1.0"
SELECTION_POLICY_VERSION = "replacement-selection-policy-v2.1.0"
SCREEN_LABEL = "TECHNICAL REPLACEMENT SCREEN - NOT RESEARCH DATA"
SCRIPT_ID = "monitoring_fixed_belief_v1"
GENERATION_VERSION = GENERATION_V4_VERSION
MAX_COMPLETION_TOKENS = GENERATION_V4_MAX_COMPLETION_TOKENS
MINIMUM_CONTEXT_TOKENS = 16_384
MAX_HTTP_ATTEMPTS = 16
MINIMUM_REQUEST_INTERVAL_SECONDS = 5.0
PLANNED_CONVERSATIONS = 2
PLANNED_RESPONSE_SLOTS = 12
REPETITION = 1

EXCLUDED_COMPARATORS = frozenset(
    {
        "minimax/minimax-m3:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    }
)
COMPLETE_LIMIT_PARAMETERS = frozenset({"max_tokens", "max_completion_tokens"})
DISAPPEARING_WITHIN_DAYS = 30
SPECIALISATION_TERMS: dict[str, tuple[str, ...]] = {
    "coding": ("coding model", "code model", "code-specialized", "code specialised"),
    "finance": ("finance model", "financial model", "trading model"),
    "translation": ("translation model", "machine translation", "translator model"),
    "music_audio": ("music model", "audio model", "speech-only", "audio-only"),
    "vision_only": ("vision-only", "vision only"),
    "language_specialised": (
        "japanese-only",
        "japanese only",
        "chinese-only",
        "chinese only",
        "non-english-only",
    ),
}

ELIGIBILITY_POLICY = (
    "exact_stable_non_router_slug",
    "zero_prompt_and_completion_price",
    "text_input_and_output",
    "advertised_seed_support",
    "explicit_4096_token_completion_limit_support",
    "minimum_16384_token_context",
    "not_batch_only_expired_deprecated_or_disappearing_within_30_days",
    "not_existing_minimax_or_rejected_nemotron_comparator",
)
SELECTION_POLICY = (
    "filter_only_with_versioned_catalogue_eligibility_policy",
    "keep_substantive_candidate_responses_private_during_selection",
    "use_only_catalogue_metadata_and_prespecified_technical_aggregates",
    "order_general_purpose_before_specialisation_warning_then_canonical_slug",
    "screen_in_frozen_order_and_stop_on_first_pass",
    "retain_every_attempted_candidate_and_verdict",
    "change_rule_only_for_a_documented_genuine_technical_defect",
    "prefer_max_completion_tokens_then_max_tokens_for_equivalent_4096_envelope",
)
SCREEN_CRITERIA = (
    "exactly_two_frozen_context_cells",
    "twelve_contiguous_successful_turns",
    "persisted_http_attempts_at_most_16",
    "resolved_model_equals_requested_model",
    "no_provider_or_model_mismatch",
    "nonempty_private_response_text",
    "provider_and_finish_reason_reported",
    "all_finish_reasons_exactly_stop",
    "zero_truncated_responses",
    "frozen_replacement_screen_metadata_matches",
    "evidence_is_well_formed_unique_and_verifiable",
)

CATALOGUE_FIELDS = (
    "id",
    "canonical_slug",
    "name",
    "description",
    "pricing",
    "architecture",
    "supported_parameters",
    "reasoning",
    "context_length",
    "top_provider",
    "max_completion_tokens",
    "max_tokens",
    "expiration_date",
    "expires_at",
    "status",
    "endpoint_type",
    "availability",
    "is_batch_only",
    "created",
)


class ReplacementScreenError(RuntimeError):
    """A replacement workflow invariant was not satisfied."""


class ScreenVerdict(StrEnum):
    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"
    FAIL = "FAIL"
    PASS = "PASS"


class ReplacementScreenAssessment(StrictModel):
    assessment_version: str = SCREEN_ASSESSMENT_VERSION
    assessment_id: str
    assessed_at: datetime
    screen_version: str = SCREEN_VERSION
    selection_policy_version: str = SELECTION_POLICY_VERSION
    candidate_model_id: str
    study_version: str = "study-v2.1.0"
    generation_version: str = GENERATION_VERSION
    frozen_criteria: tuple[str, ...] = SCREEN_CRITERIA
    verdict: ScreenVerdict
    failed_criteria: tuple[str, ...] = ()
    statistics: dict[str, Any] = Field(default_factory=dict)
    source_evidence_hash: str
    source_file_hashes: dict[str, str] = Field(default_factory=dict)


def validate_candidate_model_id(model_id: str, *, permit_excluded: bool = False) -> str:
    """Require one stable exact free slug before any network object is constructed."""

    candidate = model_id.strip()
    lowered = candidate.casefold()
    if not candidate or any(character.isspace() for character in candidate):
        raise ReplacementScreenError("An exact nonblank candidate model ID is required")
    if lowered in {"openrouter/free", "openrouter/auto"} or "latest" in lowered:
        raise ReplacementScreenError("Routers, auto-routers and latest aliases are prohibited")
    if lowered.startswith("openrouter/") or lowered.endswith("/auto") or "/auto:" in lowered:
        raise ReplacementScreenError("Routers and auto-routers are prohibited")
    if not candidate.endswith(":free"):
        raise ReplacementScreenError("Candidate model ID must be an exact :free endpoint")
    if not permit_excluded and candidate in EXCLUDED_COMPARATORS:
        raise ReplacementScreenError("The existing or rejected comparator cannot be rescreened")
    return candidate


def _parse_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_expiration(entry: Mapping[str, Any]) -> datetime | None:
    raw = entry.get("expiration_date", entry.get("expires_at"))
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _specialisation_warnings(entry: Mapping[str, Any]) -> tuple[str, ...]:
    searchable = " ".join(
        str(entry.get(field) or "") for field in ("id", "name", "description")
    ).casefold()
    warnings = [
        category
        for category, phrases in SPECIALISATION_TERMS.items()
        if any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", searchable) for phrase in phrases)
    ]
    return tuple(sorted(warnings))


def _maximum_completion_capability(entry: Mapping[str, Any]) -> int | None:
    top_provider = entry.get("top_provider")
    candidates = [entry.get("max_completion_tokens"), entry.get("max_tokens")]
    if isinstance(top_provider, Mapping):
        candidates.extend(
            [top_provider.get("max_completion_tokens"), top_provider.get("max_tokens")]
        )
    numeric = [int(value) for value in candidates if isinstance(value, int) and value > 0]
    return max(numeric) if numeric else None


def relevant_catalogue_metadata(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only catalogue metadata used by the frozen technical policy."""

    return {field: entry.get(field) for field in CATALOGUE_FIELDS if field in entry}


def evaluate_catalogue_candidate(
    entry: Mapping[str, Any], *, retrieved_at: datetime
) -> dict[str, Any]:
    """Apply the versioned eligibility policy without using response behaviour."""

    model_id = str(entry.get("id") or "").strip()
    canonical_slug = str(entry.get("canonical_slug") or model_id).strip()
    reasons: list[str] = []
    try:
        validate_candidate_model_id(model_id)
    except ReplacementScreenError as error:
        message = str(error).casefold()
        if "comparator" in message:
            reasons.append("excluded_existing_or_rejected_comparator")
        elif "router" in message or "alias" in message:
            reasons.append("router_or_unstable_alias")
        else:
            reasons.append("not_exact_free_slug")
    if canonical_slug != model_id:
        reasons.append("canonical_slug_mismatch_or_alias")

    pricing = entry.get("pricing")
    prompt_price = _parse_decimal(pricing.get("prompt")) if isinstance(pricing, Mapping) else None
    completion_price = (
        _parse_decimal(pricing.get("completion")) if isinstance(pricing, Mapping) else None
    )
    if prompt_price is None or completion_price is None:
        reasons.append("pricing_unverifiable")
    elif prompt_price != 0 or completion_price != 0:
        reasons.append("nonzero_prompt_or_completion_price")

    architecture = entry.get("architecture")
    input_modalities = (
        tuple(str(value) for value in architecture.get("input_modalities") or ())
        if isinstance(architecture, Mapping)
        else ()
    )
    output_modalities = (
        tuple(str(value) for value in architecture.get("output_modalities") or ())
        if isinstance(architecture, Mapping)
        else ()
    )
    if "text" not in input_modalities:
        reasons.append("text_input_not_advertised")
    if "text" not in output_modalities:
        reasons.append("text_output_not_advertised")

    supported_parameters = tuple(str(value) for value in entry.get("supported_parameters") or ())
    if "seed" not in supported_parameters:
        reasons.append("seed_not_advertised")
    try:
        completion_parameter = select_completion_limit_parameter(supported_parameters)
    except RuntimeError:
        completion_parameter = None
        reasons.append("explicit_completion_limit_parameter_not_advertised")
    maximum_completion = _maximum_completion_capability(entry)
    if maximum_completion is None:
        reasons.append("maximum_completion_capability_unverifiable")
    elif maximum_completion < MAX_COMPLETION_TOKENS:
        reasons.append("maximum_completion_capability_below_4096")

    context_length = entry.get("context_length")
    if not isinstance(context_length, int) or context_length < MINIMUM_CONTEXT_TOKENS:
        reasons.append("context_length_below_study_minimum")

    if (
        entry.get("is_batch_only") is True
        or str(entry.get("endpoint_type") or "").casefold() == "batch"
        or str(entry.get("availability") or "").casefold() == "batch_only"
    ):
        reasons.append("batch_only_endpoint")
    status = str(entry.get("status") or "").casefold()
    if status in {"expired", "deprecated", "retired", "unavailable"}:
        reasons.append("expired_deprecated_or_unavailable")
    expiration = _parse_expiration(entry)
    raw_expiration_present = any(
        entry.get(field) not in (None, "") for field in ("expiration_date", "expires_at")
    )
    if raw_expiration_present and expiration is None:
        reasons.append("expiration_unverifiable")
    elif expiration is not None and expiration <= retrieved_at + timedelta(
        days=DISAPPEARING_WITHIN_DAYS
    ):
        reasons.append("expired_or_disappearing_within_30_days")

    warnings = _specialisation_warnings(entry)
    return {
        "exact_model_id": model_id,
        "canonical_slug": canonical_slug,
        "display_name": str(entry.get("name") or model_id),
        "zero_price_confirmed": prompt_price == 0 and completion_price == 0,
        "prompt_price": str(prompt_price) if prompt_price is not None else None,
        "completion_price": str(completion_price) if completion_price is not None else None,
        "input_modalities": list(input_modalities),
        "output_modalities": list(output_modalities),
        "context_length": context_length,
        "maximum_completion_capability": maximum_completion,
        "completion_limit_parameter": completion_parameter,
        "relevant_supported_parameters": sorted(
            set(supported_parameters) & ({"seed", "reasoning"} | COMPLETE_LIMIT_PARAMETERS)
        ),
        "expiration_date": expiration.isoformat() if expiration else None,
        "specialisation_warnings": list(warnings),
        "eligible": not reasons,
        "rejection_reasons": sorted(set(reasons)),
    }


def deterministic_candidate_order(evaluations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return eligible candidates in the prespecified content-blind order."""

    eligible = [dict(value) for value in evaluations if value.get("eligible") is True]
    return sorted(
        eligible,
        key=lambda value: (
            bool(value.get("specialisation_warnings")),
            str(value.get("canonical_slug") or "").casefold(),
        ),
    )


def build_catalogue_evidence(
    entries: Iterable[Mapping[str, Any]], *, retrieved_at: datetime
) -> dict[str, Any]:
    """Create content-free, credential-free evidence from one catalogue response."""

    metadata = [relevant_catalogue_metadata(entry) for entry in entries]
    metadata.sort(key=lambda value: str(value.get("id") or ""))
    evaluations = [
        evaluate_catalogue_candidate(entry, retrieved_at=retrieved_at) for entry in metadata
    ]
    evaluations.sort(key=lambda value: str(value["exact_model_id"]))
    ordered = deterministic_candidate_order(evaluations)
    evidence_hash = canonical_hash(metadata)
    return {
        "catalogue_evidence_version": CATALOGUE_EVIDENCE_VERSION,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "record_type": "REPLACEMENT CATALOGUE METADATA - NOT RESEARCH DATA",
        "retrieved_at": retrieved_at.isoformat(),
        "catalogue_endpoint": CATALOGUE_ENDPOINT,
        "catalogue_evidence_hash": evidence_hash,
        "eligibility_policy": list(ELIGIBILITY_POLICY),
        "selection_policy": list(SELECTION_POLICY),
        "candidate_metadata": metadata,
        "candidate_evaluations": evaluations,
        "deterministic_eligible_order": [value["exact_model_id"] for value in ordered],
        "generation_requests_made": 0,
    }


def persist_catalogue_evidence(record: Mapping[str, Any], root: str | Path) -> Path:
    retrieved = datetime.fromisoformat(str(record["retrieved_at"]).replace("Z", "+00:00"))
    destination = (
        Path(root)
        / CATALOGUE_EVIDENCE_VERSION
        / f"{retrieved.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json"
    )
    return atomic_write_json(destination, dict(record))


def candidate_evidence_key(candidate_model_id: str) -> str:
    digest = hashlib.sha256(candidate_model_id.encode("utf-8")).hexdigest()[:12]
    return f"{safe_filename(candidate_model_id)}-{digest}"


def candidate_store_root(output_root: str | Path, candidate_model_id: str) -> Path:
    return Path(output_root) / candidate_evidence_key(candidate_model_id)


def load_screen_configuration(
    repository_root: str | Path,
) -> tuple[ScriptConfig, HistoryPrefix, GenerationConfig]:
    root = Path(repository_root)
    scripts = load_scripts(root / "config" / "scenarios")
    histories = load_histories(root / "config" / "histories")
    models = load_models(root / "config" / "models.yaml")
    generation = generation_for_repetition(models, REPETITION)
    try:
        require_generation_v4(generation)
    except ValueError as error:
        raise ReplacementScreenError(
            "Replacement screen requires the complete frozen generation-v4 profile"
        ) from error
    script = next((value for value in scripts if value.script_id == SCRIPT_ID), None)
    if script is None or script.presentation_level.value != "fixed_belief":
        raise ReplacementScreenError("Frozen fixed-belief technical scenario is unavailable")
    prefix = next((value for value in histories if value.history_id == script.history_id), None)
    if prefix is None:
        raise ReplacementScreenError("Frozen technical-screen history is unavailable")
    return script, prefix, generation


def screen_configuration_hash(
    script: ScriptConfig, prefix: HistoryPrefix, generation: GenerationConfig
) -> str:
    return canonical_hash(
        {
            "screen_version": SCREEN_VERSION,
            "selection_policy_version": SELECTION_POLICY_VERSION,
            "script": script.model_dump(mode="json"),
            "history": prefix.model_dump(mode="json"),
            "generation": generation.model_dump(mode="json"),
            "planned_contexts": [value.value for value in ContextCondition],
            "planned_response_slots": PLANNED_RESPONSE_SLOTS,
            "maximum_http_attempts": MAX_HTTP_ATTEMPTS,
            "minimum_request_interval_seconds": MINIMUM_REQUEST_INTERVAL_SECONDS,
            "qualification_criteria": SCREEN_CRITERIA,
        }
    )


def screen_rows(candidate_model_id: str, repository_root: str | Path) -> list[ManifestRow]:
    candidate = validate_candidate_model_id(candidate_model_id)
    script, _, generation = load_screen_configuration(repository_root)
    key = candidate_evidence_key(candidate)
    rows = [
        ManifestRow(
            study_version=SCREEN_VERSION,
            run_id=f"{SCREEN_VERSION}_{key}_{condition.value}",
            script_id=script.script_id,
            theme=script.theme,
            presentation_level=script.presentation_level,
            model_slot="model_replacement_candidate",
            requested_model_id=candidate,
            context_condition=condition,
            repetition=REPETITION,
            generation_config_version=generation.version,
            planned_seed=generation.seed,
            execution_order=order,
            status=RunStatus.PLANNED,
        )
        for order, condition in enumerate(ContextCondition, start=1)
    ]
    if len(rows) != PLANNED_CONVERSATIONS or len(rows) * 6 != PLANNED_RESPONSE_SLOTS:
        raise ReplacementScreenError("Replacement screen shape must remain 2 cells / 12 slots")
    return rows


def build_offline_screen_plan(
    candidate_model_id: str, repository_root: str | Path
) -> dict[str, Any]:
    """Construct both six-turn payload shapes without provider construction or writes."""

    candidate = validate_candidate_model_id(candidate_model_id)
    script, prefix, generation = load_screen_configuration(repository_root)
    rows = screen_rows(candidate, repository_root)
    runs: list[dict[str, Any]] = []
    for row in rows:
        exchanges: list[tuple[str, str]] = []
        message_counts: list[int] = []
        for turn_number, user_message in enumerate(script.turns, start=1):
            messages = build_target_messages(
                condition=row.context_condition,
                prefix=(
                    prefix
                    if row.context_condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT
                    else None
                ),
                completed_exchanges=exchanges,
                current_user_message=user_message,
                visible_response_instruction=generation.visible_response_instruction,
            )
            message_counts.append(len(messages))
            exchanges.append((user_message, f"<assistant response {turn_number}>"))
        runs.append(
            {
                "execution_order": row.execution_order,
                "context_condition": row.context_condition.value,
                "payload_count": 6,
                "message_counts": message_counts,
            }
        )
    return {
        "screen_version": SCREEN_VERSION,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "status": "offline_preflight",
        "candidate_model_id": candidate,
        "network_called": False,
        "network_requests": 0,
        "catalogue_status": "NOT_FETCHED",
        "generation_version": generation.version,
        "completion_envelope_tokens": generation.completion_envelope_tokens,
        "completion_limit_parameter": "PENDING_CATALOGUE_VERIFICATION",
        "planned_conversations": len(rows),
        "planned_response_slots": len(rows) * 6,
        "maximum_http_attempts": MAX_HTTP_ATTEMPTS,
        "minimum_request_interval_seconds": MINIMUM_REQUEST_INTERVAL_SECONDS,
        "configuration_hash": None,
        "contexts": [row.context_condition.value for row in rows],
        "runs": runs,
    }


def _expected_header(
    *,
    row: ManifestRow,
    script: ScriptConfig,
    generation: GenerationConfig,
    configuration_hash: str,
):
    return create_run_header(
        study_version=SCREEN_VERSION,
        run_id=row.run_id,
        data_status="technical_pilot",
        script=script,
        condition=row.context_condition,
        model_slot=row.model_slot,
        model_id=row.requested_model_id,
        repetition=REPETITION,
        generation=generation,
        configuration_version=SELECTION_POLICY_VERSION,
        configuration_hash=configuration_hash,
    )


def stored_screen_attempts(store: RawRunStore, rows: Iterable[ManifestRow]) -> int:
    attempts = 0
    for row in rows:
        if not (store.run_directory(row.run_id) / "run.json").is_file():
            continue
        record = store.load(row.run_id)
        attempts += sum(result_http_attempts(event.result) for event in record.turns)
        attempts += sum(result_http_attempts(event.result) for event in record.errors)
    return attempts


def execute_screen_conversations(
    *,
    candidate_model_id: str,
    repository_root: str | Path,
    output_root: str | Path,
    provider: TargetProvider,
    maximum_http_attempts: int,
    completion_limit_parameter: str,
) -> None:
    """Run from the first missing turn, stopping the invocation after a new 429."""

    script, prefix, semantic_generation = load_screen_configuration(repository_root)
    if completion_limit_parameter not in COMPLETE_LIMIT_PARAMETERS:
        raise ReplacementScreenError("Completion-limit translation is not verified")
    generation = semantic_generation.model_copy(
        update={"completion_limit_parameter": completion_limit_parameter}
    )
    rows = screen_rows(candidate_model_id, repository_root)
    store = RawRunStore(candidate_store_root(output_root, candidate_model_id))
    configuration_hash = screen_configuration_hash(script, prefix, generation)
    provider.set_request_attempt_budget(maximum_http_attempts)  # type: ignore[attr-defined]
    for row in rows:
        if provider.request_attempt_count >= maximum_http_attempts:  # type: ignore[attr-defined]
            break
        candidate_header = _expected_header(
            row=row,
            script=script,
            generation=generation,
            configuration_hash=configuration_hash,
        )
        header = resume_or_new_header(store, candidate_header)
        if len(store.successful_turns(row.run_id)) == 6:
            continue
        before_errors = len(store.error_events(row.run_id))
        record = ConversationRunner(provider, store).run_or_resume(
            header=header, script=script, prefix=prefix
        )
        new_errors = record.errors[before_errors:]
        if any(event.result.error_type == "http_429" for event in new_errors):
            break


def _source_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def _source_hashes(root: Path, files: list[Path]) -> tuple[str, dict[str, str]]:
    aggregate = hashlib.sha256()
    individual: dict[str, str] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        individual[relative] = digest
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(content)
        aggregate.update(b"\0")
    return aggregate.hexdigest(), individual


def assess_replacement_screen(
    *,
    candidate_model_id: str,
    repository_root: str | Path,
    output_root: str | Path,
    assessment_root: str | Path | None = None,
    persist: bool = False,
    assessed_at: datetime | None = None,
) -> ReplacementScreenAssessment:
    """Recompute a fail-closed verdict from one candidate's private evidence."""

    candidate = validate_candidate_model_id(candidate_model_id)
    script, prefix, semantic_generation = load_screen_configuration(repository_root)
    rows = screen_rows(candidate, repository_root)
    expected = {row.run_id: row for row in rows}
    root = candidate_store_root(output_root, candidate)
    files = _source_files(root)
    source_hash, source_file_hashes = _source_hashes(root, files)
    store = RawRunStore(root)
    failures: set[str] = set()
    integrity_failures: set[str] = set()
    actual_directories = (
        {path.name for path in root.iterdir() if path.is_dir()} if root.exists() else set()
    )
    if actual_directories - set(expected):
        integrity_failures.add("unexpected_or_mixed_candidate_run")

    successful = 0
    complete = 0
    present_cells = 0
    attempts = 0
    technical_errors = 0
    missing_provider = 0
    missing_finish_reason = 0
    empty_response = 0
    mismatches = 0
    truncations = 0
    finish_reasons: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    resolved_models: Counter[str] = Counter()
    event_ids: set[str] = set()
    completion_parameters: set[str] = set()

    for run_id, row in expected.items():
        directory = store.run_directory(run_id)
        if not (directory / "run.json").is_file():
            continue
        present_cells += 1
        recognised = {"run.json"}
        recognised.update(path.name for path in directory.glob("turn-*-success.json"))
        recognised.update(path.name for path in directory.glob("turn-*-error-*.json"))
        if {path.name for path in directory.iterdir() if path.is_file()} != recognised:
            integrity_failures.add("unrecognised_or_duplicate_evidence_file")
        try:
            record = store.load(run_id)
        except (OSError, ValueError):
            integrity_failures.add("malformed_or_non_contiguous_evidence")
            continue
        header = record.header
        completion_parameter = header.generation_config.completion_limit_parameter
        if completion_parameter not in COMPLETE_LIMIT_PARAMETERS:
            integrity_failures.add("completion_limit_parameter_unverified")
            mapped_generation = semantic_generation
            configuration_hash = ""
        else:
            completion_parameters.add(completion_parameter)
            mapped_generation = semantic_generation.model_copy(
                update={"completion_limit_parameter": completion_parameter}
            )
            configuration_hash = screen_configuration_hash(script, prefix, mapped_generation)
        if (
            header.study_version != SCREEN_VERSION
            or header.data_status != "technical_pilot"
            or header.run_id != row.run_id
            or header.script_id != row.script_id
            or header.script_version != script.script_version
            or header.theme != row.theme
            or header.presentation_level != row.presentation_level
            or header.context_condition != row.context_condition
            or header.model_slot != row.model_slot
            or header.requested_model_id != candidate
            or header.repetition != REPETITION
            or header.configuration_version != SELECTION_POLICY_VERSION
            or header.configuration_hash != configuration_hash
            or header.generation_config != mapped_generation
        ):
            integrity_failures.add("mixed_candidate_or_frozen_metadata_mismatch")
        if [event.turn_number for event in record.turns] != list(range(1, len(record.turns) + 1)):
            integrity_failures.add("malformed_or_non_contiguous_evidence")
        if len(record.turns) == 6:
            complete += 1
        successful += len(record.turns)
        technical_errors += len(record.errors)
        for event in (*record.turns, *record.errors):
            if event.event_id in event_ids:
                integrity_failures.add("duplicate_event_id")
            event_ids.add(event.event_id)
            attempts += result_http_attempts(event.result)
            if event.result.http_attempts is None:
                integrity_failures.add("unverifiable_http_attempt_accounting")
            elif event.event_type == "turn_success" and event.result.http_attempts < 1:
                integrity_failures.add("unverifiable_http_attempt_accounting")
            elif (
                event.event_type == "turn_error"
                and event.result.http_attempts < 1
                and event.result.error_type != "request_budget_exhausted"
            ):
                integrity_failures.add("unverifiable_http_attempt_accounting")
            if (
                event.run_id != run_id
                or event.request_model_id != candidate
                or event.result.requested_model_id != candidate
            ):
                integrity_failures.add("event_identity_mismatch")
            expected_messages = build_target_messages(
                condition=row.context_condition,
                prefix=prefix,
                completed_exchanges=[
                    (prior.user_message, prior.result.text or "")
                    for prior in record.turns
                    if prior.turn_number < event.turn_number
                ],
                current_user_message=script.turns[event.turn_number - 1],
                visible_response_instruction=mapped_generation.visible_response_instruction,
            )
            try:
                expected_parameters = mapped_generation.request_parameters()
            except ValueError:
                integrity_failures.add("completion_limit_parameter_unverified")
                expected_parameters = {}
            if (
                event.request_messages != expected_messages
                or event.request_parameters != expected_parameters
                or event.request_stream is not False
                or event.request_payload_hash
                != payload_hash(
                    model_id=candidate,
                    messages=expected_messages,
                    parameters=expected_parameters,
                )
            ):
                integrity_failures.add("request_metadata_or_history_mismatch")
            if (
                event.event_type == "turn_success"
                and event.user_message != script.turns[event.turn_number - 1]
            ):
                integrity_failures.add("request_metadata_or_history_mismatch")
            if event.event_type == "turn_error" and (
                event.result.error_type == "resolved_model_mismatch"
                or (
                    event.result.resolved_model_id is not None
                    and event.result.resolved_model_id != candidate
                )
            ):
                mismatches += 1
        for event in record.turns:
            result = event.result
            if result.status != ObservationStatus.RESPONSE:
                integrity_failures.add("non_response_stored_as_success")
            if not (result.text or "").strip():
                empty_response += 1
            if result.resolved_model_id != candidate:
                mismatches += 1
            else:
                resolved_models[result.resolved_model_id] += 1
            if not (result.provider_name or "").strip():
                missing_provider += 1
            else:
                providers[result.provider_name] += 1
            finish_reason = (result.finish_reason or "").strip().casefold()
            if not finish_reason:
                missing_finish_reason += 1
                finish_reasons["unreported"] += 1
            else:
                finish_reasons[finish_reason] += 1
            if result.truncated:
                truncations += 1

    if len(completion_parameters) > 1:
        integrity_failures.add("mixed_completion_limit_parameters")

    missing = PLANNED_RESPONSE_SLOTS - successful
    remaining = max(0, MAX_HTTP_ATTEMPTS - attempts)
    resumable = attempts <= MAX_HTTP_ATTEMPTS and remaining >= max(0, missing)
    if present_cells != PLANNED_CONVERSATIONS:
        failures.add("exactly_two_frozen_context_cells")
    if successful != PLANNED_RESPONSE_SLOTS or complete != PLANNED_CONVERSATIONS:
        failures.add("twelve_contiguous_successful_turns")
    if attempts > MAX_HTTP_ATTEMPTS:
        failures.add("persisted_http_attempts_at_most_16")
    if mismatches:
        failures.update({"resolved_model_equals_requested_model", "no_provider_or_model_mismatch"})
    if empty_response:
        failures.add("nonempty_private_response_text")
    if missing_provider or missing_finish_reason:
        failures.add("provider_and_finish_reason_reported")
    if any(reason != "stop" for reason in finish_reasons) or missing_finish_reason:
        failures.add("all_finish_reasons_exactly_stop")
    if truncations:
        failures.add("zero_truncated_responses")
    if integrity_failures:
        failures.update(integrity_failures)
        failures.add("evidence_is_well_formed_unique_and_verifiable")

    fatal = {
        "persisted_http_attempts_at_most_16",
        "resolved_model_equals_requested_model",
        "no_provider_or_model_mismatch",
        "nonempty_private_response_text",
        "provider_and_finish_reason_reported",
        "all_finish_reasons_exactly_stop",
        "zero_truncated_responses",
        "evidence_is_well_formed_unique_and_verifiable",
    }
    if not files and not present_cells:
        verdict = ScreenVerdict.NOT_RUN
        failures = {"replacement_screen_evidence_not_present"}
    elif failures & fatal:
        verdict = ScreenVerdict.FAIL
    elif successful < PLANNED_RESPONSE_SLOTS or present_cells < PLANNED_CONVERSATIONS:
        verdict = ScreenVerdict.INCOMPLETE if resumable else ScreenVerdict.FAIL
    elif failures:
        verdict = ScreenVerdict.FAIL
    else:
        verdict = ScreenVerdict.PASS

    assessment = ReplacementScreenAssessment(
        assessment_id=uuid.uuid4().hex,
        assessed_at=assessed_at or datetime.now(UTC),
        candidate_model_id=candidate,
        verdict=verdict,
        failed_criteria=tuple(sorted(failures)),
        statistics={
            "expected_cells": PLANNED_CONVERSATIONS,
            "present_cells": present_cells,
            "completed_conversations": complete,
            "successful_response_slots": successful,
            "missing_response_slots": max(0, missing),
            "technical_error_events": technical_errors,
            "http_attempts_used": attempts,
            "remaining_attempt_allowance": remaining,
            "mathematically_resumable": resumable,
            "truncation_count": truncations,
            "empty_response_count": empty_response,
            "missing_provider_count": missing_provider,
            "missing_finish_reason_count": missing_finish_reason,
            "resolved_model_mismatch_count": mismatches,
            "finish_reasons": dict(finish_reasons),
            "providers": dict(providers),
            "resolved_models": dict(resolved_models),
            "completion_limit_parameter": (
                next(iter(completion_parameters)) if len(completion_parameters) == 1 else None
            ),
            "source_file_count": len(files),
        },
        source_evidence_hash=source_hash,
        source_file_hashes=source_file_hashes,
    )
    if persist:
        destination_root = (
            Path(assessment_root)
            if assessment_root is not None
            else Path(output_root).parent / f"{SCREEN_VERSION}-assessments"
        ) / candidate_evidence_key(candidate)
        timestamp = assessment.assessed_at.strftime("%Y%m%dT%H%M%S%fZ")
        atomic_write_json(
            destination_root / f"{timestamp}-{assessment.assessment_id}.json",
            assessment.model_dump(mode="json"),
        )
    return assessment


def print_safe_assessment(assessment: ReplacementScreenAssessment) -> None:
    """Print only content-free aggregate technical evidence."""

    stats = assessment.statistics
    print(SCREEN_LABEL)
    print(f"candidate_model_id={assessment.candidate_model_id}")
    print(f"verdict={assessment.verdict.value}")
    print(
        f"cells={stats['present_cells']}/{stats['expected_cells']}; "
        f"completed_conversations={stats['completed_conversations']}/2"
    )
    print(
        f"successful_response_slots={stats['successful_response_slots']}/12; "
        f"missing_response_slots={stats['missing_response_slots']}; "
        f"technical_errors={stats['technical_error_events']}"
    )
    print(f"http_attempts={stats['http_attempts_used']}/16")
    print(f"resolved_models={stats['resolved_models']}")
    print(f"providers={stats['providers']}")
    print(f"finish_reasons={stats['finish_reasons']}")
    print(f"truncation_count={stats['truncation_count']}")
    print(f"failed_criteria={list(assessment.failed_criteria)}")
    print(f"source_evidence_hash={assessment.source_evidence_hash}")
    print(
        f"safe_resume_available={'yes' if assessment.verdict == ScreenVerdict.INCOMPLETE else 'no'}"
    )
