"""Deterministic, fail-closed qualification of versioned technical-pilot evidence."""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.config_loader import configuration_bundle_hash, generation_for_repetition
from src.schemas import ObservationStatus, StrictModel
from src.storage import RawRunStore, atomic_write_json
from src.study_execution import result_http_attempts

V4_ASSESSMENT_VERSION = "pilot-v4-qualification-v1.0.0"
V4_PILOT_VERSION = "technical-pilot-v4.0.0"
V4_PILOT_NAMESPACE = "technical-pilot-v4"
V5_ASSESSMENT_VERSION = "pilot-v5-qualification-v1.0.0"
V5_PILOT_VERSION = "technical-pilot-v5.0.0"
V5_PILOT_NAMESPACE = "technical-pilot-v5"
MAX_HTTP_ATTEMPTS = 32
EXPECTED_CONVERSATIONS = 4
EXPECTED_RESPONSES = 24
ALLOWED_COMPLETE_FINISH_REASONS = frozenset({"stop"})
BASE_FROZEN_CRITERIA = (
    "exactly_four_frozen_model_context_cells",
    "twenty_four_contiguous_successful_turns",
    "persisted_http_attempts_at_most_32",
    "resolved_model_equals_requested_model",
    "no_provider_or_model_mismatch",
    "nonempty_private_response_text",
    "provider_and_finish_reason_reported",
    "zero_truncated_responses",
    "only_complete_finish_reasons",
    "versioned_technical_pilot_evidence_only",
    "frozen_study_v2_configuration_matches",
    "evidence_is_well_formed_unique_and_verifiable",
)


class QualificationVerdict(StrEnum):
    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"
    FAIL = "FAIL"
    PASS = "PASS"


class PilotQualificationAssessment(StrictModel):
    assessment_version: str
    assessment_id: str
    assessed_at: datetime
    pilot_version: str
    study_version: str = "study-v2.0.0"
    configuration_version: str
    generation_version: str
    frozen_criteria: tuple[str, ...] = BASE_FROZEN_CRITERIA
    verdict: QualificationVerdict
    failed_criteria: tuple[str, ...] = ()
    main_study_blocked: bool
    statistics: dict[str, Any] = Field(default_factory=dict)
    source_evidence_hash: str
    source_file_hashes: dict[str, str] = Field(default_factory=dict)


def _source_files(output_root: Path, pilot_namespace: str) -> list[Path]:
    if not output_root.exists():
        return []
    return sorted(
        path
        for directory in output_root.iterdir()
        if directory.is_dir() and directory.name.startswith(f"{pilot_namespace}_")
        for path in directory.rglob("*")
        if path.is_file()
    )


def _hashes(output_root: Path, files: list[Path]) -> tuple[str, dict[str, str]]:
    aggregate = hashlib.sha256()
    individual: dict[str, str] = {}
    for path in files:
        relative = path.relative_to(output_root).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        individual[relative] = digest
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(content)
        aggregate.update(b"\0")
    return aggregate.hexdigest(), individual


def _safe_failure(failures: set[str], criterion: str) -> None:
    failures.add(criterion)


def _assess_pilot(
    *,
    output_root: str | Path,
    pilot_version: str,
    pilot_namespace: str,
    assessment_version: str,
    assessment_directory: str,
    configuration_loader: Any,
    rows_loader: Any,
    assessment_root: str | Path | None = None,
    persist: bool = False,
    assessed_at: datetime | None = None,
) -> PilotQualificationAssessment:
    """Recompute qualification from private raw evidence; never trust a prior verdict."""

    root = Path(output_root)
    files = _source_files(root, pilot_namespace)
    source_hash, source_file_hashes = _hashes(root, files)
    _, _, models, scripts, histories = configuration_loader()
    rows = rows_loader()
    expected = {row.run_id: row for row in rows}
    configuration_hash = configuration_bundle_hash(scripts, histories, models)
    failures: set[str] = set()
    integrity_failures: set[str] = set()
    store = RawRunStore(root)
    actual_directories = {
        directory.name
        for directory in root.iterdir()
        if directory.is_dir() and directory.name.startswith(f"{pilot_namespace}_")
    }
    unexpected = actual_directories - set(expected)
    if unexpected:
        integrity_failures.add("unexpected_or_mixed_versioned_pilot_run")

    successful_responses = 0
    technical_errors = 0
    attempts = 0
    truncation_count = 0
    missing_provider = 0
    missing_finish_reason = 0
    empty_response_count = 0
    resolved_model_mismatches = 0
    disallowed_finish_reasons: Counter[str] = Counter()
    complete_conversations = 0
    present_cells = 0
    providers: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()

    for run_id, row in expected.items():
        run_directory = store.run_directory(run_id)
        if not (run_directory / "run.json").is_file():
            continue
        present_cells += 1
        recognised = {"run.json"}
        recognised.update(path.name for path in run_directory.glob("turn-*-success.json"))
        recognised.update(path.name for path in run_directory.glob("turn-*-error-*.json"))
        if {path.name for path in run_directory.iterdir() if path.is_file()} != recognised:
            integrity_failures.add("unrecognised_or_duplicate_evidence_file")
        try:
            record = store.load(run_id)
        except (OSError, ValueError):
            integrity_failures.add("malformed_or_non_contiguous_evidence")
            continue
        header = record.header
        expected_generation = generation_for_repetition(models, row.repetition)
        if (
            header.study_version != pilot_version
            or header.data_status != "technical_pilot"
            or header.run_id != run_id
            or header.script_id != row.script_id
            or header.theme != row.theme
            or header.presentation_level != row.presentation_level
            or header.context_condition != row.context_condition
            or header.model_slot != row.model_slot
            or header.requested_model_id != row.requested_model_id
            or header.repetition != row.repetition
        ):
            integrity_failures.add("mixed_version_or_frozen_cell_mismatch")
        if (
            header.configuration_version != models.version
            or header.configuration_hash != configuration_hash
            or header.generation_config != expected_generation
        ):
            integrity_failures.add("frozen_configuration_metadata_mismatch")
        success_numbers = [event.turn_number for event in record.turns]
        if success_numbers != list(range(1, len(success_numbers) + 1)):
            integrity_failures.add("malformed_or_non_contiguous_evidence")
        if len(record.turns) == 6:
            complete_conversations += 1
        successful_responses += len(record.turns)
        technical_errors += len(record.errors)
        for event in (*record.turns, *record.errors):
            attempts += result_http_attempts(event.result)
            if event.result.http_attempts is None:
                integrity_failures.add("unverifiable_http_attempt_accounting")
            if event.run_id != run_id or event.request_model_id != row.requested_model_id:
                integrity_failures.add("event_identity_mismatch")
            if event.result.requested_model_id != row.requested_model_id:
                integrity_failures.add("event_identity_mismatch")
            if event.event_type == "turn_error" and (
                event.result.error_type == "resolved_model_mismatch"
                or (
                    event.result.resolved_model_id is not None
                    and event.result.resolved_model_id != row.requested_model_id
                )
            ):
                resolved_model_mismatches += 1
        for event in record.turns:
            result = event.result
            if result.status != ObservationStatus.RESPONSE:
                integrity_failures.add("non_response_stored_as_success")
            if not (result.text or "").strip():
                empty_response_count += 1
            if result.resolved_model_id != row.requested_model_id:
                resolved_model_mismatches += 1
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
                if finish_reason not in ALLOWED_COMPLETE_FINISH_REASONS:
                    disallowed_finish_reasons[finish_reason] += 1
            if result.truncated:
                truncation_count += 1

    missing_responses = EXPECTED_RESPONSES - successful_responses
    remaining_attempts = max(0, MAX_HTTP_ATTEMPTS - attempts)
    mathematically_resumable = attempts <= MAX_HTTP_ATTEMPTS and remaining_attempts >= max(
        0, missing_responses
    )
    if present_cells != EXPECTED_CONVERSATIONS:
        _safe_failure(failures, "exactly_four_frozen_model_context_cells")
    if successful_responses != EXPECTED_RESPONSES or complete_conversations != 4:
        _safe_failure(failures, "twenty_four_contiguous_successful_turns")
    if attempts > MAX_HTTP_ATTEMPTS:
        _safe_failure(failures, "persisted_http_attempts_at_most_32")
    if resolved_model_mismatches:
        _safe_failure(failures, "resolved_model_equals_requested_model")
        _safe_failure(failures, "no_provider_or_model_mismatch")
    if empty_response_count:
        _safe_failure(failures, "nonempty_private_response_text")
    if missing_provider or missing_finish_reason:
        _safe_failure(failures, "provider_and_finish_reason_reported")
    if truncation_count:
        _safe_failure(failures, "zero_truncated_responses")
    if disallowed_finish_reasons:
        _safe_failure(failures, "only_complete_finish_reasons")
    if integrity_failures:
        failures.update(integrity_failures)
        failures.add("evidence_is_well_formed_unique_and_verifiable")

    if not files and present_cells == 0 and not unexpected:
        verdict = QualificationVerdict.NOT_RUN
        failures = {f"{pilot_namespace.replace('-', '_')}_evidence_not_present"}
    elif integrity_failures or any(
        criterion in failures
        for criterion in (
            "persisted_http_attempts_at_most_32",
            "resolved_model_equals_requested_model",
            "no_provider_or_model_mismatch",
            "nonempty_private_response_text",
            "provider_and_finish_reason_reported",
            "zero_truncated_responses",
            "only_complete_finish_reasons",
        )
    ):
        verdict = QualificationVerdict.FAIL
    elif successful_responses < EXPECTED_RESPONSES or present_cells < EXPECTED_CONVERSATIONS:
        verdict = (
            QualificationVerdict.INCOMPLETE
            if mathematically_resumable
            else QualificationVerdict.FAIL
        )
    elif not failures:
        verdict = QualificationVerdict.PASS
    else:
        verdict = QualificationVerdict.FAIL

    assessment = PilotQualificationAssessment(
        assessment_version=assessment_version,
        assessment_id=uuid.uuid4().hex,
        assessed_at=assessed_at or datetime.now(UTC),
        pilot_version=pilot_version,
        configuration_version=models.version,
        generation_version=models.generation.version,
        verdict=verdict,
        failed_criteria=tuple(sorted(failures)),
        main_study_blocked=verdict != QualificationVerdict.PASS,
        statistics={
            "expected_cells": EXPECTED_CONVERSATIONS,
            "present_cells": present_cells,
            "completed_conversations": complete_conversations,
            "successful_response_slots": successful_responses,
            "missing_response_slots": max(0, missing_responses),
            "technical_error_events": technical_errors,
            "http_attempts_used": attempts,
            "remaining_attempt_allowance": remaining_attempts,
            "mathematically_resumable": mathematically_resumable,
            "truncation_count": truncation_count,
            "empty_response_count": empty_response_count,
            "missing_provider_count": missing_provider,
            "missing_finish_reason_count": missing_finish_reason,
            "resolved_model_mismatch_count": resolved_model_mismatches,
            "disallowed_finish_reasons": dict(disallowed_finish_reasons),
            "finish_reasons": dict(finish_reasons),
            "providers": dict(providers),
            "source_file_count": len(files),
        },
        source_evidence_hash=source_hash,
        source_file_hashes=source_file_hashes,
    )
    if persist:
        destination_root = (
            Path(assessment_root)
            if assessment_root is not None
            else root.parent / assessment_directory
        )
        timestamp = assessment.assessed_at.strftime("%Y%m%dT%H%M%S%fZ")
        atomic_write_json(
            destination_root / f"{assessment_version}_{timestamp}_{assessment.assessment_id}.json",
            assessment.model_dump(mode="json"),
        )
    return assessment


def assess_pilot_v4(
    *,
    output_root: str | Path,
    assessment_root: str | Path | None = None,
    persist: bool = False,
    assessed_at: datetime | None = None,
) -> PilotQualificationAssessment:
    """Recompute the frozen Pilot V4 verdict using archived generation-v2 metadata."""

    from scripts.run_pilot_v4 import _configuration, pilot_rows

    return _assess_pilot(
        output_root=output_root,
        pilot_version=V4_PILOT_VERSION,
        pilot_namespace=V4_PILOT_NAMESPACE,
        assessment_version=V4_ASSESSMENT_VERSION,
        assessment_directory="pilot-v4-qualification",
        configuration_loader=_configuration,
        rows_loader=pilot_rows,
        assessment_root=assessment_root,
        persist=persist,
        assessed_at=assessed_at,
    )


def assess_pilot_v5(
    *,
    output_root: str | Path,
    assessment_root: str | Path | None = None,
    persist: bool = False,
    assessed_at: datetime | None = None,
) -> PilotQualificationAssessment:
    """Recompute Pilot V5 qualification from its isolated generation-v3 evidence."""

    from scripts.run_pilot_v5 import _configuration, pilot_rows

    return _assess_pilot(
        output_root=output_root,
        pilot_version=V5_PILOT_VERSION,
        pilot_namespace=V5_PILOT_NAMESPACE,
        assessment_version=V5_ASSESSMENT_VERSION,
        assessment_directory="pilot-v5-qualification",
        configuration_loader=_configuration,
        rows_loader=pilot_rows,
        assessment_root=assessment_root,
        persist=persist,
        assessed_at=assessed_at,
    )


def pilot_v4_safe_cross_tab(*, output_root: str | Path) -> list[dict[str, Any]]:
    """Return content-free V4 model/provider/finish/truncation response counts."""

    from scripts.run_pilot_v4 import pilot_rows

    store = RawRunStore(output_root)
    counts: Counter[tuple[str, str, str, str, bool]] = Counter()
    for row in pilot_rows():
        run_path = store.run_directory(row.run_id) / "run.json"
        if not run_path.is_file():
            continue
        record = store.load(row.run_id)
        for event in record.turns:
            result = event.result
            counts[
                (
                    row.requested_model_id,
                    result.resolved_model_id or "unreported",
                    result.provider_name or "unreported",
                    result.finish_reason or "unreported",
                    result.truncated,
                )
            ] += 1
    return [
        {
            "requested_model": requested,
            "resolved_model": resolved,
            "resolved_provider": provider,
            "finish_reason": finish_reason,
            "truncated": truncated,
            "response_count": count,
        }
        for (requested, resolved, provider, finish_reason, truncated), count in sorted(
            counts.items()
        )
    ]


def pilot_v5_safe_cross_tab(*, output_root: str | Path) -> list[dict[str, Any]]:
    """Return content-free V5 model/provider/finish/truncation response counts."""

    from scripts.run_pilot_v5 import pilot_rows

    store = RawRunStore(output_root)
    counts: Counter[tuple[str, str, str, str, bool]] = Counter()
    for row in pilot_rows():
        run_path = store.run_directory(row.run_id) / "run.json"
        if not run_path.is_file():
            continue
        record = store.load(row.run_id)
        for event in record.turns:
            result = event.result
            counts[
                (
                    row.requested_model_id,
                    result.resolved_model_id or "unreported",
                    result.provider_name or "unreported",
                    result.finish_reason or "unreported",
                    result.truncated,
                )
            ] += 1
    return [
        {
            "requested_model": requested,
            "resolved_model": resolved,
            "resolved_provider": provider,
            "finish_reason": finish_reason,
            "truncated": truncated,
            "response_count": count,
        }
        for (requested, resolved, provider, finish_reason, truncated), count in sorted(
            counts.items()
        )
    ]


def print_safe_assessment(assessment: PilotQualificationAssessment) -> None:
    """Print aggregate qualification metadata without private conversation content."""

    stats = assessment.statistics
    pilot_label = assessment.pilot_version.replace("technical-pilot-", "").split(".")[0].upper()
    print(f"PILOT {pilot_label} TECHNICAL QUALIFICATION - NOT RESEARCH DATA")
    print(f"verdict={assessment.verdict.value}")
    print(
        f"cells={stats['present_cells']}/{stats['expected_cells']}; "
        f"completed_conversations={stats['completed_conversations']}/4"
    )
    print(
        f"successful_response_slots={stats['successful_response_slots']}/24; "
        f"technical_errors={stats['technical_error_events']}"
    )
    print(
        f"http_attempts={stats['http_attempts_used']}/32; "
        f"truncation_count={stats['truncation_count']}"
    )
    print(f"finish_reasons={stats['finish_reasons']}")
    print(f"providers={stats['providers']}")
    print(f"failed_criteria={list(assessment.failed_criteria)}")
    print(f"source_evidence_hash={assessment.source_evidence_hash}")
    print(f"main_study_blocked={'yes' if assessment.main_study_blocked else 'no'}")
