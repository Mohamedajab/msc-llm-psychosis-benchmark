"""Tests for ordinal exact agreement and weighted-kappa reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.annotation import (
    AnnotationError,
    compute_inter_rater_reliability,
    compute_intra_rater_reliability,
    exact_agreement,
    linearly_weighted_cohen_kappa,
    ordinary_cohen_kappa,
)
from src.schemas import AnnotationEvent, AxisScores, BlindingMapEntry

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def _scores(a1: int, *, a2: int = 1) -> AxisScores:
    return AxisScores(A1=a1, A2=a2, A3=1, B1=0, B2=0, B3=0, C1=2)


def _event(
    item_id: str,
    source_number: int,
    rating_round: str,
    scores: AxisScores,
    *,
    annotator: str = "rater-01",
    minute: int = 0,
) -> AnnotationEvent:
    return AnnotationEvent(
        annotation_id=f"ann-{item_id}-{annotator}-{minute}",
        blinded_item_id=item_id,
        rating_round=rating_round,
        annotator_id=annotator,
        scores=scores,
        source_response_hash=f"{source_number:064x}",
        saved_at=NOW + timedelta(minutes=minute),
    )


def _paired_fixture() -> tuple[list[AnnotationEvent], list[BlindingMapEntry]]:
    initial_values = [0, 1, 2, 2]
    rerating_values = [0, 2, 2, 1]
    events: list[AnnotationEvent] = []
    mapping: list[BlindingMapEntry] = []
    for index, (initial, rerating) in enumerate(
        zip(initial_values, rerating_values, strict=True), start=1
    ):
        initial_id = f"initial-{index}"
        rerating_id = f"rerating-{index}"
        mapping.extend(
            [
                BlindingMapEntry(
                    blinded_item_id=initial_id,
                    run_id=f"run-{index}",
                    turn_number=1,
                    rating_round="initial",
                ),
                BlindingMapEntry(
                    blinded_item_id=rerating_id,
                    run_id=f"run-{index}",
                    turn_number=1,
                    rating_round="rerating",
                ),
            ]
        )
        events.extend(
            [
                _event(initial_id, index, "initial", _scores(initial), minute=index),
                _event(
                    rerating_id,
                    index,
                    "rerating",
                    _scores(rerating),
                    minute=10 + index,
                ),
            ]
        )
    return events, mapping


def test_exact_agreement_and_linear_weighted_kappa_match_known_values() -> None:
    first = [0, 1, 2, 2]
    second = [0, 2, 2, 1]
    assert exact_agreement(first, second) == pytest.approx(0.5)
    assert linearly_weighted_cohen_kappa(first, second) == pytest.approx(3 / 7)


def test_intra_rater_report_is_per_axis_and_handles_undefined_kappa() -> None:
    events, mapping = _paired_fixture()
    report = compute_intra_rater_reliability(events, mapping, annotator_id="rater-01")

    assert report.reliability_type == "intra-rater"
    assert report.label == "Intra-rater reliability"
    assert report.matched_items == 4
    assert len(report.axes) == 7
    a1 = next(axis for axis in report.axes if axis.axis_id == "A1")
    assert a1.n_pairs == 4
    assert a1.exact_agreement == pytest.approx(0.5)
    assert a1.cohen_kappa == pytest.approx(3 / 7)
    assert a1.kappa_method == "linear_weighted"

    # A2 is identically 1 in both rounds: exact agreement exists but kappa does not.
    a2 = next(axis for axis in report.axes if axis.axis_id == "A2")
    assert a2.exact_agreement == 1.0
    assert a2.cohen_kappa is None
    assert "expected weighted disagreement is zero" in a2.kappa_unavailable_reason

    a3 = next(axis for axis in report.axes if axis.axis_id == "A3")
    assert a3.kappa_method == "unweighted"


def test_unavailable_reliability_is_returned_without_crashing() -> None:
    events, mapping = _paired_fixture()
    only_initial = [event for event in events if event.rating_round == "initial"]
    report = compute_intra_rater_reliability(only_initial, mapping, annotator_id="rater-01")

    assert not report.available
    assert report.matched_items == 0
    assert report.unavailable_reason is not None
    assert all(axis.n_pairs == 0 for axis in report.axes)
    assert all(axis.exact_agreement is None for axis in report.axes)
    assert all(axis.cohen_kappa is None for axis in report.axes)


def test_inter_rater_label_requires_two_independent_annotators() -> None:
    events, mapping = _paired_fixture()
    initial = [event for event in events if event.rating_round == "initial"]
    second_rater = [
        _event(
            event.blinded_item_id,
            index,
            "initial",
            event.scores,
            annotator="rater-02",
            minute=30 + index,
        )
        for index, event in enumerate(initial, start=1)
    ]
    report = compute_inter_rater_reliability(
        [*initial, *second_rater],
        mapping,
        annotator_a="rater-01",
        annotator_b="rater-02",
    )
    assert report.reliability_type == "inter-rater"
    assert report.label == "Inter-rater reliability"
    assert report.matched_items == 4
    assert all(axis.exact_agreement == 1.0 for axis in report.axes)

    with pytest.raises(AnnotationError, match="two different"):
        compute_inter_rater_reliability(
            initial,
            mapping,
            annotator_a="rater-01",
            annotator_b="rater-01",
        )


def test_metric_helpers_ignore_incomplete_pairs_and_reject_invalid_values() -> None:
    assert exact_agreement([0, None, 2], [0, 1, None]) == 1.0
    assert exact_agreement([0, "N/A", 1], [0, 1, "N/A"]) == 1.0
    assert linearly_weighted_cohen_kappa([1], [1]) is None
    assert ordinary_cohen_kappa([0, 0, 1, 1], [0, 1, 1, 1]) == pytest.approx(0.5)
    assert exact_agreement([None], [None]) is None
    with pytest.raises(AnnotationError, match="0, 1, 2"):
        linearly_weighted_cohen_kappa([3, 1], [2, 1])
    with pytest.raises(AnnotationError, match="same length"):
        exact_agreement([0, 1], [0])
