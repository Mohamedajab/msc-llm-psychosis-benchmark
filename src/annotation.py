"""Blinded annotation preparation, persistence, and reliability utilities.

This module deliberately keeps the annotator-facing item separate from the internal
mapping back to a study run.  It contains no aggregate across the seven rubric axes:
the axes have different directions and must be analysed individually (or in explicitly
labelled, direction-consistent groups elsewhere).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import math
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from src.config_loader import load_rubric
from src.schemas import (
    AnnotationEvent,
    AxisScores,
    BlindedAnnotationItem,
    BlindingMapEntry,
    ChatMessage,
    ConversationRecord,
    ObservationStatus,
    RubricConfig,
)

AXIS_IDS: tuple[str, ...] = ("A1", "A2", "A3", "B1", "B2", "B3", "C1")
RATING_ROUNDS: tuple[str, ...] = ("initial", "rerating")
TIDY_COLUMNS: tuple[str, ...] = (
    "annotation_id",
    "blinded_item_id",
    "rating_round",
    "annotator_id",
    "annotation_method",
    "axis_id",
    "score",
    "notes",
    "uncertain_adjudication_needed",
    "source_response_hash",
    "saved_at",
    "revision",
)


class AnnotationError(ValueError):
    """Raised when blinded annotation inputs are inconsistent or unsafe."""


class AnnotationPersistenceError(RuntimeError):
    """Raised when an append-only annotation log cannot be safely interpreted."""


@dataclass(frozen=True)
class BehaviouralScorability:
    """Content-independent primary-annotation eligibility for one observed turn."""

    turn_number: int
    primary_scorable: bool
    reason: Literal["complete_pre_truncation", "truncated", "downstream_of_truncation"]


def behavioural_scorability(record: ConversationRecord) -> tuple[BehaviouralScorability, ...]:
    """Exclude the first truncated response and every downstream trajectory turn."""

    first_truncation_seen = False
    decisions: list[BehaviouralScorability] = []
    for turn in sorted(record.turns, key=lambda event: event.turn_number):
        is_truncated = turn.result.truncated or (
            (turn.result.finish_reason or "").strip().casefold() == "length"
        )
        if first_truncation_seen:
            reason = "downstream_of_truncation"
            scorable = False
        elif is_truncated:
            first_truncation_seen = True
            reason = "truncated"
            scorable = False
        else:
            reason = "complete_pre_truncation"
            scorable = True
        decisions.append(
            BehaviouralScorability(
                turn_number=turn.turn_number,
                primary_scorable=scorable,
                reason=reason,
            )
        )
    return tuple(decisions)


@dataclass(frozen=True)
class AxisReliabilityResult:
    """Agreement statistics for one rubric axis."""

    axis_id: str
    n_pairs: int
    exact_agreement: float | None
    cohen_kappa: float | None
    kappa_method: Literal["linear_weighted", "unweighted"]
    kappa_unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReliabilityReport:
    """A labelled collection of per-axis paired reliability results."""

    reliability_type: Literal["intra-rater", "inter-rater"]
    label: str
    annotators: tuple[str, ...]
    matched_items: int
    axes: tuple[AxisReliabilityResult, ...]
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return any(result.n_pairs > 0 for result in self.axes)

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "reliability_type": self.reliability_type,
                "label": self.label,
                "annotators": ", ".join(self.annotators),
                "matched_items": self.matched_items,
                **axis.as_dict(),
                "report_unavailable_reason": self.unavailable_reason,
            }
            for axis in self.axes
        ]


def load_default_rubric(path: str | Path | None = None) -> RubricConfig:
    """Load and schema-validate the annotation rubric."""

    rubric_path = (
        Path(path) if path is not None else Path(__file__).parents[1] / "config" / "rubric.yaml"
    )
    return load_rubric(rubric_path)


def rubric_display_rows(rubric: RubricConfig | None = None) -> list[dict[str, Any]]:
    """Return concise per-axis content for an annotation interface.

    No combined score is calculated or exposed.
    """

    rubric = rubric or load_default_rubric()
    return [
        {
            "axis_id": axis.id,
            "name": axis.name,
            "role": axis.role,
            "direction": axis.direction,
            "definition": axis.definition,
            "allowed_scores": axis.allowed_scores,
            "allows_na": axis.allows_na,
            "na_guidance": axis.na_guidance,
            "anchors": dict(axis.anchors),
            "notes": axis.notes,
            "examples": axis.examples,
        }
        for axis in rubric.axes
    ]


def response_hash(response_text: str) -> str:
    """Hash the exact response text used for an annotation item."""

    if not response_text.strip():
        raise AnnotationError("Cannot create an annotation item for a blank response")
    return hashlib.sha256(response_text.encode("utf-8")).hexdigest()


def _key_bytes(value: str | bytes, *, field_name: str) -> bytes:
    key = value.encode("utf-8") if isinstance(value, str) else value
    if not key:
        raise AnnotationError(f"{field_name} cannot be blank")
    return key


def _opaque_token(key: str | bytes, purpose: str, *parts: object) -> str:
    """Produce a stable opaque token using a keyed digest.

    A keyed HMAC prevents a blinded identifier from serving as a plain hash lookup of
    a run identifier.  The token contains no sequence, model, condition, or repetition
    label.
    """

    key_bytes = _key_bytes(key, field_name="blinding key")
    payload = "\x1f".join((purpose, *(str(part) for part in parts))).encode("utf-8")
    digest = hmac.new(key_bytes, payload, hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:20]


def _annotator_context(messages: Sequence[ChatMessage]) -> tuple[ChatMessage, ...]:
    """Keep only the target-facing dialogue that existed before the scored response."""

    # System messages are deliberately omitted from the human-facing conversation.
    # The research protocol uses no target system message, but this makes blinding safe
    # if a provider adapter ever adds a neutral technical system message.
    return tuple(message for message in messages if message.role in {"user", "assistant"})


def build_blinded_items(
    conversations: Iterable[ConversationRecord],
    *,
    blinding_key: str | bytes,
) -> tuple[list[BlindedAnnotationItem], list[BlindingMapEntry]]:
    """Build initial-round items and a separate internal mapping.

    Each item uses the exact request messages for its turn, so future turns and future
    responses cannot appear. Failed/missing provider observations, truncated responses,
    and turns downstream of the first truncation are excluded from primary behavioural
    scoring. All remain preserved in raw technical evidence.
    """

    records = sorted(conversations, key=lambda record: record.header.run_id)
    items: list[BlindedAnnotationItem] = []
    mapping: list[BlindingMapEntry] = []
    seen_ids: set[str] = set()

    for record in records:
        scorability = {
            decision.turn_number: decision for decision in behavioural_scorability(record)
        }
        for turn in sorted(record.turns, key=lambda event: event.turn_number):
            decision = scorability[turn.turn_number]
            if turn.result.status != ObservationStatus.RESPONSE or not decision.primary_scorable:
                continue
            text = turn.result.text or ""
            source_hash = response_hash(text)
            blinded_id = "item_" + _opaque_token(
                blinding_key,
                "annotation-item-v1",
                "initial",
                record.header.run_id,
                turn.turn_number,
                source_hash,
            )
            if blinded_id in seen_ids:
                raise AnnotationError("Blinded item identifier collision detected")
            seen_ids.add(blinded_id)
            items.append(
                BlindedAnnotationItem(
                    blinded_item_id=blinded_id,
                    rating_round="initial",
                    turn_number=turn.turn_number,
                    conversation_context=_annotator_context(turn.request_messages),
                    response_to_score=text,
                    source_response_hash=source_hash,
                )
            )
            mapping.append(
                BlindingMapEntry(
                    blinded_item_id=blinded_id,
                    run_id=record.header.run_id,
                    turn_number=turn.turn_number,
                    rating_round="initial",
                )
            )
    # Ordering by the opaque keyed ID is deterministic but avoids preserving manifest
    # order, which could otherwise reveal run groupings through position alone.
    paired = sorted(zip(items, mapping, strict=True), key=lambda pair: pair[0].blinded_item_id)
    return [pair[0] for pair in paired], [pair[1] for pair in paired]


def _write_json_exclusive(path: Path, value: Any, *, overwrite: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    try:
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise FileExistsError(f"File already exists and was not overwritten: {path}") from error
    return path


def save_blinded_items(
    path: str | Path,
    items: Sequence[BlindedAnnotationItem],
    *,
    overwrite: bool = False,
) -> Path:
    """Save annotator-facing items without the internal run mapping."""

    return _write_json_exclusive(
        Path(path),
        [item.model_dump(mode="json") for item in items],
        overwrite=overwrite,
    )


def save_blinding_map(
    path: str | Path,
    mapping: Sequence[BlindingMapEntry],
    *,
    overwrite: bool = False,
) -> Path:
    """Save the re-identification map to a distinct internal file."""

    return _write_json_exclusive(
        Path(path),
        [entry.model_dump(mode="json") for entry in mapping],
        overwrite=overwrite,
    )


def load_blinded_items(path: str | Path) -> list[BlindedAnnotationItem]:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return [BlindedAnnotationItem.model_validate(item) for item in raw]


def load_blinding_map(path: str | Path) -> list[BlindingMapEntry]:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return [BlindingMapEntry.model_validate(entry) for entry in raw]


def _sample_count(total: int, sample_size: float) -> int:
    if isinstance(sample_size, bool):
        raise AnnotationError("sample_size must be an integer count or a fraction")
    if isinstance(sample_size, float):
        if not 0 <= sample_size <= 1:
            raise AnnotationError("A fractional sample_size must be between 0 and 1")
        return min(total, math.ceil(total * sample_size))
    if sample_size < 0:
        raise AnnotationError("sample_size cannot be negative")
    return min(total, sample_size)


def create_rerating_sample(
    items: Sequence[BlindedAnnotationItem],
    blinding_map: Sequence[BlindingMapEntry],
    *,
    sample_size: float,
    selection_seed: str | int,
    blinding_key: str | bytes,
) -> tuple[list[BlindedAnnotationItem], list[BlindingMapEntry]]:
    """Select a deterministic re-rating sample under unlinkable new item IDs."""

    seed_key = _key_bytes(str(selection_seed), field_name="selection seed")
    initial_items = [item for item in items if item.rating_round == "initial"]
    map_by_id = {entry.blinded_item_id: entry for entry in blinding_map}
    if len(map_by_id) != len(blinding_map):
        raise AnnotationError("The blinding map contains duplicate item IDs")

    ranked: list[tuple[str, BlindedAnnotationItem, BlindingMapEntry]] = []
    for item in initial_items:
        entry = map_by_id.get(item.blinded_item_id)
        if entry is None or entry.rating_round != "initial":
            raise AnnotationError(f"Missing initial-round map entry for {item.blinded_item_id}")
        rank = _opaque_token(
            seed_key,
            "rerating-selection-v1",
            item.blinded_item_id,
            item.source_response_hash,
        )
        ranked.append((rank, item, entry))
    ranked.sort(key=lambda row: (row[0], row[1].blinded_item_id))

    selected = ranked[: _sample_count(len(ranked), sample_size)]
    rerating_items: list[BlindedAnnotationItem] = []
    rerating_map: list[BlindingMapEntry] = []
    original_ids = {item.blinded_item_id for item in items}
    new_ids: set[str] = set()
    for _, item, entry in selected:
        blinded_id = "item_" + _opaque_token(
            blinding_key,
            "annotation-item-v1",
            "rerating",
            selection_seed,
            entry.run_id,
            entry.turn_number,
            item.source_response_hash,
        )
        if blinded_id in original_ids or blinded_id in new_ids:
            raise AnnotationError("Re-rating blinded item identifier collision detected")
        new_ids.add(blinded_id)
        rerating_items.append(
            BlindedAnnotationItem(
                blinded_item_id=blinded_id,
                rating_round="rerating",
                turn_number=item.turn_number,
                conversation_context=item.conversation_context,
                response_to_score=item.response_to_score,
                source_response_hash=item.source_response_hash,
            )
        )
        rerating_map.append(
            BlindingMapEntry(
                blinded_item_id=blinded_id,
                run_id=entry.run_id,
                turn_number=entry.turn_number,
                rating_round="rerating",
            )
        )
    return rerating_items, rerating_map


@contextmanager
def _exclusive_log_lock(path: Path) -> Iterator[None]:
    """Use a small cross-platform advisory lock around an append operation."""

    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        lock_handle.seek(0, os.SEEK_END)
        if lock_handle.tell() == 0:
            lock_handle.write(b"0")
            lock_handle.flush()
        lock_handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


class AnnotationStore:
    """Append-only JSONL persistence for progress and annotation revisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read_events(self) -> list[AnnotationEvent]:
        if not self.path.exists():
            return []
        events: list[AnnotationEvent] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    events.append(AnnotationEvent.model_validate_json(line))
                except (ValidationError, ValueError) as error:
                    raise AnnotationPersistenceError(
                        f"Invalid annotation event at {self.path}:{line_number}: {error}"
                    ) from error
        return events

    def append(self, event: AnnotationEvent | Mapping[str, Any]) -> AnnotationEvent:
        validated = (
            event if isinstance(event, AnnotationEvent) else AnnotationEvent.model_validate(event)
        )
        payload = (validated.model_dump_json() + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_log_lock(self.path):
            existing_ids = {saved.annotation_id for saved in self.read_events()}
            if validated.annotation_id in existing_ids:
                raise AnnotationPersistenceError(
                    f"Duplicate annotation_id was not appended: {validated.annotation_id}"
                )
            with self.path.open("ab") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        return validated

    def save(
        self,
        item: BlindedAnnotationItem,
        *,
        annotator_id: str,
        annotation_method: Literal["human", "model_generated"] = "human",
        scores: AxisScores | Mapping[str, int | str | None],
        notes: str = "",
        uncertain_adjudication_needed: bool = False,
        saved_at: datetime | None = None,
    ) -> AnnotationEvent:
        """Append a progress save or later revision for one blinded item."""

        if not annotator_id.strip():
            raise AnnotationError("annotator_id cannot be blank")
        validated_scores = (
            scores if isinstance(scores, AxisScores) else AxisScores.model_validate(scores)
        )
        timestamp = saved_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise AnnotationError("saved_at must be timezone-aware")
        event = AnnotationEvent(
            annotation_id=f"ann_{uuid.uuid4().hex}",
            blinded_item_id=item.blinded_item_id,
            rating_round=item.rating_round,
            annotator_id=annotator_id.strip(),
            annotation_method=annotation_method,
            scores=validated_scores,
            notes=notes,
            uncertain_adjudication_needed=uncertain_adjudication_needed,
            source_response_hash=item.source_response_hash,
            saved_at=timestamp.astimezone(UTC),
        )
        return self.append(event)

    def latest_events(self, *, annotator_id: str | None = None) -> list[AnnotationEvent]:
        """Return the latest revision for each item and annotator."""

        latest: dict[tuple[str, str], tuple[datetime, int, AnnotationEvent]] = {}
        for index, event in enumerate(self.read_events()):
            if annotator_id is not None and event.annotator_id != annotator_id:
                continue
            key = (event.blinded_item_id, event.annotator_id)
            candidate = (event.saved_at, index, event)
            if key not in latest or candidate[:2] >= latest[key][:2]:
                latest[key] = candidate
        return [entry[2] for _, entry in sorted(latest.items(), key=lambda pair: pair[0])]

    def latest_for(
        self, item_or_id: BlindedAnnotationItem | str, *, annotator_id: str
    ) -> AnnotationEvent | None:
        item_id = (
            item_or_id.blinded_item_id
            if isinstance(item_or_id, BlindedAnnotationItem)
            else item_or_id
        )
        candidates = [
            event
            for event in self.latest_events(annotator_id=annotator_id)
            if event.blinded_item_id == item_id
        ]
        return candidates[0] if candidates else None

    def incomplete_items(
        self,
        items: Sequence[BlindedAnnotationItem],
        *,
        annotator_id: str,
    ) -> list[BlindedAnnotationItem]:
        """Return unseen and partially saved items in the supplied stable order."""

        latest = {
            event.blinded_item_id: event for event in self.latest_events(annotator_id=annotator_id)
        }
        return [
            item
            for item in items
            if item.blinded_item_id not in latest
            or not latest[item.blinded_item_id].scores.complete()
        ]

    def next_incomplete(
        self,
        items: Sequence[BlindedAnnotationItem],
        *,
        annotator_id: str,
    ) -> BlindedAnnotationItem | None:
        incomplete = self.incomplete_items(items, annotator_id=annotator_id)
        return incomplete[0] if incomplete else None


def _latest_with_revision(
    events: Iterable[AnnotationEvent],
) -> list[tuple[AnnotationEvent, int]]:
    latest: dict[tuple[str, str], tuple[datetime, int, AnnotationEvent, int]] = {}
    revision_counts: dict[tuple[str, str], int] = {}
    for index, event in enumerate(events):
        key = (event.blinded_item_id, event.annotator_id)
        revision_counts[key] = revision_counts.get(key, 0) + 1
        candidate = (event.saved_at, index, event, revision_counts[key])
        if key not in latest or candidate[:2] >= latest[key][:2]:
            latest[key] = candidate
    return [(value[2], value[3]) for _, value in sorted(latest.items(), key=lambda pair: pair[0])]


def tidy_annotation_rows(
    events: Iterable[AnnotationEvent],
    *,
    latest_only: bool = True,
) -> list[dict[str, Any]]:
    """Return one row per item/axis without unblinded experimental metadata."""

    validated = [
        event if isinstance(event, AnnotationEvent) else AnnotationEvent.model_validate(event)
        for event in events
    ]
    if latest_only:
        selected = _latest_with_revision(validated)
    else:
        counts: dict[tuple[str, str], int] = {}
        selected = []
        for event in validated:
            key = (event.blinded_item_id, event.annotator_id)
            counts[key] = counts.get(key, 0) + 1
            selected.append((event, counts[key]))

    rows: list[dict[str, Any]] = []
    for event, revision in selected:
        scores = event.scores.model_dump()
        for axis_id in AXIS_IDS:
            rows.append(
                {
                    "annotation_id": event.annotation_id,
                    "blinded_item_id": event.blinded_item_id,
                    "rating_round": event.rating_round,
                    "annotator_id": event.annotator_id,
                    "annotation_method": event.annotation_method,
                    "axis_id": axis_id,
                    "score": scores[axis_id],
                    "notes": event.notes,
                    "uncertain_adjudication_needed": event.uncertain_adjudication_needed,
                    "source_response_hash": event.source_response_hash,
                    "saved_at": event.saved_at.isoformat(),
                    "revision": revision,
                }
            )
    return rows


def tidy_annotation_frame(events: Iterable[AnnotationEvent], *, latest_only: bool = True) -> Any:
    """Return a pandas frame lazily, keeping pandas optional for core persistence."""

    import pandas as pd

    return pd.DataFrame(tidy_annotation_rows(events, latest_only=latest_only), columns=TIDY_COLUMNS)


def export_tidy_annotations(
    path: str | Path,
    events: Iterable[AnnotationEvent] | AnnotationStore,
    *,
    latest_only: bool = True,
    overwrite: bool = False,
) -> Path:
    """Export a safe long-form CSV that remains blinded."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(f"Annotation export already exists and was not overwritten: {output}")
    event_values = events.read_events() if isinstance(events, AnnotationStore) else events
    rows = tidy_annotation_rows(event_values, latest_only=latest_only)
    mode = "w"
    with output.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIDY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    return output


def _paired_values(
    first: Sequence[int | str | None], second: Sequence[int | str | None]
) -> tuple[list[int], list[int]]:
    if len(first) != len(second):
        raise AnnotationError("Paired rating vectors must have the same length")
    left: list[int] = []
    right: list[int] = []
    for first_value, second_value in zip(first, second, strict=True):
        if first_value in {None, "N/A"} or second_value in {None, "N/A"}:
            continue
        if first_value not in {0, 1, 2} or second_value not in {0, 1, 2}:
            raise AnnotationError("Reliability scores must be 0, 1, 2, N/A, or missing")
        left.append(first_value)
        right.append(second_value)
    return left, right


def exact_agreement(
    first: Sequence[int | str | None], second: Sequence[int | str | None]
) -> float | None:
    """Return exact paired agreement, or ``None`` when no complete pair exists."""

    left, right = _paired_values(first, second)
    if not left:
        return None
    return sum(a == b for a, b in zip(left, right, strict=True)) / len(left)


def linearly_weighted_cohen_kappa(
    first: Sequence[int | str | None], second: Sequence[int | str | None]
) -> float | None:
    """Calculate linear-weighted Cohen's kappa for the frozen 0-2 scale.

    At least two complete pairs are required.  ``None`` is returned when the statistic
    is undefined (for example, both vectors are constant in the same category).
    """

    left, right = _paired_values(first, second)
    count = len(left)
    if count < 2:
        return None

    categories = (0, 1, 2)
    first_counts = {category: left.count(category) for category in categories}
    second_counts = {category: right.count(category) for category in categories}
    observed_disagreement = sum(abs(a - b) / 2 for a, b in zip(left, right, strict=True)) / count
    expected_disagreement = sum(
        (abs(a - b) / 2) * (first_counts[a] / count) * (second_counts[b] / count)
        for a in categories
        for b in categories
    )
    if math.isclose(expected_disagreement, 0.0, abs_tol=1e-15):
        return None
    return 1.0 - (observed_disagreement / expected_disagreement)


def ordinary_cohen_kappa(
    first: Sequence[int | str | None], second: Sequence[int | str | None]
) -> float | None:
    """Calculate ordinary Cohen's kappa after excluding missing and N/A pairs."""

    left, right = _paired_values(first, second)
    count = len(left)
    if count < 2:
        return None
    categories = sorted(set(left) | set(right))
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / count
    expected = sum(
        (left.count(category) / count) * (right.count(category) / count) for category in categories
    )
    if math.isclose(expected, 1.0, abs_tol=1e-15):
        return None
    return (observed - expected) / (1.0 - expected)


def _axis_results(
    first_events: Mapping[tuple[str, int], AnnotationEvent],
    second_events: Mapping[tuple[str, int], AnnotationEvent],
) -> tuple[int, tuple[AxisReliabilityResult, ...]]:
    matched_keys = sorted(set(first_events) & set(second_events))
    results: list[AxisReliabilityResult] = []
    for axis_id in AXIS_IDS:
        first_values = [getattr(first_events[key].scores, axis_id) for key in matched_keys]
        second_values = [getattr(second_events[key].scores, axis_id) for key in matched_keys]
        paired_first, paired_second = _paired_values(first_values, second_values)
        agreement = exact_agreement(paired_first, paired_second)
        method: Literal["linear_weighted", "unweighted"] = (
            "unweighted" if axis_id == "A3" else "linear_weighted"
        )
        kappa = (
            ordinary_cohen_kappa(paired_first, paired_second)
            if method == "unweighted"
            else linearly_weighted_cohen_kappa(paired_first, paired_second)
        )
        reason: str | None = None
        if len(paired_first) == 0:
            reason = "No paired complete scores are available for this axis"
        elif len(paired_first) < 2:
            reason = "At least two paired complete scores are required for kappa"
        elif kappa is None:
            reason = (
                "Kappa is undefined because expected disagreement is zero"
                if method == "unweighted"
                else "Kappa is undefined because expected weighted disagreement is zero"
            )
        results.append(
            AxisReliabilityResult(
                axis_id=axis_id,
                n_pairs=len(paired_first),
                exact_agreement=agreement,
                cohen_kappa=kappa,
                kappa_method=method,
                kappa_unavailable_reason=reason,
            )
        )
    return len(matched_keys), tuple(results)


def _latest_by_source(
    events: Iterable[AnnotationEvent],
    mapping: Sequence[BlindingMapEntry],
    *,
    annotator_id: str,
    rating_round: Literal["initial", "rerating"],
) -> dict[tuple[str, int], AnnotationEvent]:
    map_by_id = {entry.blinded_item_id: entry for entry in mapping}
    if len(map_by_id) != len(mapping):
        raise AnnotationError("The blinding map contains duplicate item IDs")
    latest: dict[tuple[str, int], tuple[datetime, int, AnnotationEvent]] = {}
    for index, event in enumerate(events):
        if event.annotator_id != annotator_id or event.rating_round != rating_round:
            continue
        entry = map_by_id.get(event.blinded_item_id)
        if entry is None:
            continue
        if entry.rating_round != event.rating_round:
            raise AnnotationError(f"Rating-round mismatch for mapped item {event.blinded_item_id}")
        source_key = (entry.run_id, entry.turn_number)
        candidate = (event.saved_at, index, event)
        if source_key not in latest or candidate[:2] >= latest[source_key][:2]:
            latest[source_key] = candidate
    return {key: value[2] for key, value in latest.items()}


def compute_intra_rater_reliability(
    events: Iterable[AnnotationEvent],
    blinding_map: Sequence[BlindingMapEntry],
    *,
    annotator_id: str,
) -> ReliabilityReport:
    """Compare one annotator's latest initial and re-rating scores by source item."""

    event_list = list(events)
    initial = _latest_by_source(
        event_list, blinding_map, annotator_id=annotator_id, rating_round="initial"
    )
    rerating = _latest_by_source(
        event_list, blinding_map, annotator_id=annotator_id, rating_round="rerating"
    )
    matched, axes = _axis_results(initial, rerating)
    reason = None if matched else "No source items have both initial and re-rating annotations"
    return ReliabilityReport(
        reliability_type="intra-rater",
        label="Intra-rater reliability",
        annotators=(annotator_id,),
        matched_items=matched,
        axes=axes,
        unavailable_reason=reason,
    )


def compute_inter_rater_reliability(
    events: Iterable[AnnotationEvent],
    blinding_map: Sequence[BlindingMapEntry],
    *,
    annotator_a: str,
    annotator_b: str,
    rating_round: Literal["initial", "rerating"] = "initial",
) -> ReliabilityReport:
    """Compare two independent annotators on the same mapped source items."""

    if annotator_a == annotator_b:
        raise AnnotationError(
            "Inter-rater reliability requires two different annotator identifiers"
        )
    event_list = list(events)
    first = _latest_by_source(
        event_list, blinding_map, annotator_id=annotator_a, rating_round=rating_round
    )
    second = _latest_by_source(
        event_list, blinding_map, annotator_id=annotator_b, rating_round=rating_round
    )
    matched, axes = _axis_results(first, second)
    reason = None if matched else "No mapped source items were scored by both annotators"
    return ReliabilityReport(
        reliability_type="inter-rater",
        label="Inter-rater reliability",
        annotators=(annotator_a, annotator_b),
        matched_items=matched,
        axes=axes,
        unavailable_reason=reason,
    )


# Short aliases used by dashboard/integration code.
weighted_kappa = linearly_weighted_cohen_kappa
intra_rater_reliability = compute_intra_rater_reliability
inter_rater_reliability = compute_inter_rater_reliability
