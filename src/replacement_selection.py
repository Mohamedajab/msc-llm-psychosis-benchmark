"""Deterministic, content-blind replacement selection from retained evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.config_loader import canonical_hash
from src.replacement_screening import (
    CATALOGUE_EVIDENCE_VERSION,
    SCREEN_VERSION,
    SELECTION_POLICY_VERSION,
    ScreenVerdict,
    assess_replacement_screen,
    build_catalogue_evidence,
    candidate_evidence_key,
)
from src.schemas import StrictModel
from src.storage import atomic_write_json

SELECTION_RECORD_VERSION = "replacement-selection-record-v1.0.0"
SELECTION_NAMESPACE = "replacement-selection-v1.0.0"
SELECTION_REASON_CODE = "first_technical_pass_in_frozen_catalogue_order"


class SelectionStatus(StrEnum):
    NOT_SELECTED = "NOT_SELECTED"
    BLOCKED = "BLOCKED"
    SELECTABLE = "SELECTABLE"
    SELECTED = "SELECTED"


class ReplacementSelectionError(RuntimeError):
    """Selection evidence is absent, inconsistent, stale or policy-ineligible."""


class ReplacementSelectionDecision(StrictModel):
    selection_policy_version: str = SELECTION_POLICY_VERSION
    status: SelectionStatus
    selected_model_id: str | None = None
    blocker: str | None = None
    catalogue_evidence_hash: str
    catalogue_record_sha256: str
    candidate_ordering: tuple[str, ...]
    candidate_ordering_hash: str
    candidate_screen_verdicts: dict[str, str] = Field(default_factory=dict)
    selected_screen_evidence_hash: str | None = None


class ReplacementSelectionRecord(StrictModel):
    record_version: str = SELECTION_RECORD_VERSION
    selection_id: str
    selection_policy_version: str = SELECTION_POLICY_VERSION
    screening_policy_version: str = SCREEN_VERSION
    selected_model_id: str
    catalogue_evidence_hash: str
    catalogue_record_sha256: str
    candidate_ordering: tuple[str, ...]
    candidate_ordering_hash: str
    technical_screen_evidence_hash: str
    screen_verdict: str
    selection_timestamp: datetime
    selection_reason_code: str = SELECTION_REASON_CODE
    response_content_consulted: bool = False
    substantive_outcome_used: bool = False
    supersedes_selection_id: str | None = None


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_catalogue_record(path: str | Path) -> tuple[dict[str, Any], Path]:
    source = Path(path)
    if not source.is_file():
        raise ReplacementSelectionError("Retained replacement-catalogue evidence is required")
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplacementSelectionError("Catalogue evidence is malformed") from error
    if record.get("catalogue_evidence_version") != CATALOGUE_EVIDENCE_VERSION:
        raise ReplacementSelectionError("Catalogue evidence version is not frozen v1.0.0")
    if record.get("selection_policy_version") != SELECTION_POLICY_VERSION:
        raise ReplacementSelectionError("Catalogue selection policy version mismatch")
    if record.get("generation_requests_made") != 0:
        raise ReplacementSelectionError("Catalogue evidence unexpectedly reports generation")
    retrieved_at_raw = record.get("retrieved_at")
    metadata = record.get("candidate_metadata")
    if not isinstance(retrieved_at_raw, str) or not isinstance(metadata, list):
        raise ReplacementSelectionError("Catalogue evidence lacks verifiable metadata")
    try:
        retrieved_at = datetime.fromisoformat(retrieved_at_raw.replace("Z", "+00:00"))
        rebuilt = build_catalogue_evidence(metadata, retrieved_at=retrieved_at)
    except (TypeError, ValueError) as error:
        raise ReplacementSelectionError("Catalogue evidence cannot be recomputed") from error
    compared = (
        "catalogue_evidence_hash",
        "eligibility_policy",
        "selection_policy",
        "candidate_metadata",
        "candidate_evaluations",
        "deterministic_eligible_order",
    )
    if any(record.get(field) != rebuilt.get(field) for field in compared):
        raise ReplacementSelectionError("Catalogue evidence or ordering is stale or tampered")
    return record, source


def determine_replacement_selection(
    *,
    catalogue_record_path: str | Path,
    screen_output_root: str | Path,
    repository_root: str | Path,
) -> ReplacementSelectionDecision:
    """Select the first PASS in frozen order, stopping at any unresolved predecessor."""

    catalogue, source = _load_catalogue_record(catalogue_record_path)
    ordering = tuple(str(value) for value in catalogue["deterministic_eligible_order"])
    catalogue_hash = str(catalogue["catalogue_evidence_hash"])
    record_hash = sha256_file(source)
    ordering_hash = canonical_hash(list(ordering))
    if not ordering:
        return ReplacementSelectionDecision(
            status=SelectionStatus.BLOCKED,
            blocker="catalogue_contains_no_eligible_candidate",
            catalogue_evidence_hash=catalogue_hash,
            catalogue_record_sha256=record_hash,
            candidate_ordering=ordering,
            candidate_ordering_hash=ordering_hash,
        )

    verdicts: dict[str, str] = {}
    for candidate in ordering:
        assessment = assess_replacement_screen(
            candidate_model_id=candidate,
            repository_root=repository_root,
            output_root=screen_output_root,
            persist=False,
        )
        verdicts[candidate] = assessment.verdict.value
        if assessment.verdict == ScreenVerdict.PASS:
            statistics = assessment.statistics
            if (
                statistics.get("successful_response_slots") != 12
                or statistics.get("missing_response_slots") != 0
                or statistics.get("truncation_count") != 0
                or statistics.get("resolved_model_mismatch_count") != 0
            ):
                raise ReplacementSelectionError("PASS assessment lacks frozen technical totals")
            return ReplacementSelectionDecision(
                status=SelectionStatus.SELECTABLE,
                selected_model_id=candidate,
                catalogue_evidence_hash=catalogue_hash,
                catalogue_record_sha256=record_hash,
                candidate_ordering=ordering,
                candidate_ordering_hash=ordering_hash,
                candidate_screen_verdicts=verdicts,
                selected_screen_evidence_hash=assessment.source_evidence_hash,
            )
        if assessment.verdict in {ScreenVerdict.NOT_RUN, ScreenVerdict.INCOMPLETE}:
            return ReplacementSelectionDecision(
                status=SelectionStatus.BLOCKED,
                blocker=f"earlier_candidate_{assessment.verdict.value.casefold()}",
                catalogue_evidence_hash=catalogue_hash,
                catalogue_record_sha256=record_hash,
                candidate_ordering=ordering,
                candidate_ordering_hash=ordering_hash,
                candidate_screen_verdicts=verdicts,
            )
        # A retained FAIL advances to the next candidate under the frozen policy.

    return ReplacementSelectionDecision(
        status=SelectionStatus.BLOCKED,
        blocker="all_eligible_candidates_failed",
        catalogue_evidence_hash=catalogue_hash,
        catalogue_record_sha256=record_hash,
        candidate_ordering=ordering,
        candidate_ordering_hash=ordering_hash,
        candidate_screen_verdicts=verdicts,
    )


def _stable_record_fields(record: ReplacementSelectionRecord) -> dict[str, Any]:
    return record.model_dump(
        mode="json",
        exclude={"selection_id", "selection_timestamp"},
    )


def create_replacement_selection(
    *,
    candidate_model_id: str,
    catalogue_record_path: str | Path,
    screen_output_root: str | Path,
    repository_root: str | Path,
    selection_root: str | Path,
    selected_at: datetime | None = None,
) -> tuple[ReplacementSelectionRecord, Path]:
    """Persist the first valid selection; never overwrite or silently change it."""

    decision = determine_replacement_selection(
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        repository_root=repository_root,
    )
    if decision.status != SelectionStatus.SELECTABLE or not decision.selected_model_id:
        raise ReplacementSelectionError(
            f"Replacement selection is blocked: {decision.blocker or decision.status.value}"
        )
    if candidate_model_id != decision.selected_model_id:
        raise ReplacementSelectionError(
            "Requested candidate is not the first technical PASS in frozen catalogue order"
        )
    timestamp = selected_at or datetime.now(UTC)
    candidate = ReplacementSelectionRecord(
        selection_id=uuid.uuid4().hex,
        selected_model_id=decision.selected_model_id,
        catalogue_evidence_hash=decision.catalogue_evidence_hash,
        catalogue_record_sha256=decision.catalogue_record_sha256,
        candidate_ordering=decision.candidate_ordering,
        candidate_ordering_hash=decision.candidate_ordering_hash,
        technical_screen_evidence_hash=decision.selected_screen_evidence_hash or "",
        screen_verdict=ScreenVerdict.PASS.value,
        selection_timestamp=timestamp,
    )
    root = Path(selection_root)
    existing_paths = sorted(root.glob("*.json")) if root.exists() else []
    for path in existing_paths:
        try:
            existing = ReplacementSelectionRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise ReplacementSelectionError("Existing selection record is malformed") from error
        if existing.selected_model_id != candidate.selected_model_id:
            raise ReplacementSelectionError(
                "Replacement identity is already frozen; a new protocol "
                "deviation/version is required"
            )
        if _stable_record_fields(existing) == _stable_record_fields(candidate):
            return existing, path
        raise ReplacementSelectionError(
            "Selection evidence changed after freezing; a new protocol "
            "deviation/version is required"
        )
    destination = root / (
        f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{candidate_evidence_key(candidate.selected_model_id)}-{candidate.selection_id}.json"
    )
    return candidate, atomic_write_json(destination, candidate.model_dump(mode="json"))


def validate_replacement_selection_record(
    *,
    selection_record_path: str | Path,
    catalogue_record_path: str | Path,
    screen_output_root: str | Path,
    repository_root: str | Path,
) -> ReplacementSelectionRecord:
    """Recompute the selection from source evidence and reject edited verdict files."""

    path = Path(selection_record_path)
    if not path.is_file():
        raise ReplacementSelectionError("Frozen replacement-selection record is required")
    try:
        record = ReplacementSelectionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReplacementSelectionError("Replacement-selection record is malformed") from error
    if (
        record.record_version != SELECTION_RECORD_VERSION
        or record.selection_policy_version != SELECTION_POLICY_VERSION
        or record.screening_policy_version != SCREEN_VERSION
        or record.selection_reason_code != SELECTION_REASON_CODE
        or record.screen_verdict != ScreenVerdict.PASS.value
        or record.supersedes_selection_id is not None
    ):
        raise ReplacementSelectionError("Replacement-selection record version or policy mismatch")
    decision = determine_replacement_selection(
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        repository_root=repository_root,
    )
    expected = {
        "selected_model_id": decision.selected_model_id,
        "catalogue_evidence_hash": decision.catalogue_evidence_hash,
        "catalogue_record_sha256": decision.catalogue_record_sha256,
        "candidate_ordering": decision.candidate_ordering,
        "candidate_ordering_hash": decision.candidate_ordering_hash,
        "technical_screen_evidence_hash": decision.selected_screen_evidence_hash,
        "screen_verdict": ScreenVerdict.PASS.value,
    }
    if decision.status != SelectionStatus.SELECTABLE or any(
        getattr(record, field) != value for field, value in expected.items()
    ):
        raise ReplacementSelectionError("Selection record is stale, mismatched or unverifiable")
    if record.response_content_consulted or record.substantive_outcome_used:
        raise ReplacementSelectionError("Substantive response content cannot determine selection")
    return record


def selection_record_hash(record: ReplacementSelectionRecord) -> str:
    return canonical_hash(record.model_dump(mode="json"))
