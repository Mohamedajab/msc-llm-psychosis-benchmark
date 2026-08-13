"""Tests for the guarded conversation-grouped supervised baseline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.baseline import (
    DEMO_ONLY_LABEL,
    InsufficientBaselineDataError,
    assert_no_group_leakage,
    evaluate_grouped_baseline,
    grouped_cv_splits,
)


def _labelled_frame(*, include_theme: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    themes = ("monitoring", "messages", "relationship")
    for theme_number, theme in enumerate(themes):
        for conversation_number in range(4):
            label = conversation_number % 2
            conversation_id = f"{theme_number}-{conversation_number}"
            for turn in (1, 2):
                row: dict[str, object] = {
                    "conversation_id": conversation_id,
                    "turn_number": turn,
                    "response_text": (
                        "uncertain ordinary alternative evidence"
                        if label == 0
                        else "definitely confirms special hidden meaning"
                    ),
                    "label": label,
                    "data_status": "demo_fixture",
                }
                if include_theme:
                    row["theme"] = theme
                rows.append(row)
    return pd.DataFrame(rows)


def test_baseline_refuses_too_few_conversations() -> None:
    frame = _labelled_frame().query("conversation_id in ['0-0', '0-1', '0-2', '0-3']")
    with pytest.raises(InsufficientBaselineDataError, match="at least 6"):
        evaluate_grouped_baseline(frame)


def test_baseline_refuses_a_single_class() -> None:
    frame = _labelled_frame()
    frame["label"] = 0
    with pytest.raises(InsufficientBaselineDataError, match="two target classes"):
        evaluate_grouped_baseline(frame)


def test_baseline_refuses_class_seen_in_only_one_conversation() -> None:
    frame = _labelled_frame()
    frame["label"] = 0
    frame.loc[frame["conversation_id"] == "0-0", "label"] = 1
    with pytest.raises(InsufficientBaselineDataError, match="at least 2 conversations"):
        evaluate_grouped_baseline(frame)


def test_grouped_splits_never_leak_a_conversation() -> None:
    frame = _labelled_frame(include_theme=False)
    splits = grouped_cv_splits(frame, theme_col=None)
    assert len(splits) >= 2
    assert_no_group_leakage(frame, splits)
    for train, test in splits:
        train_groups = set(frame.iloc[train]["conversation_id"])
        test_groups = set(frame.iloc[test]["conversation_id"])
        assert train_groups.isdisjoint(test_groups)


def test_leave_one_theme_out_reports_metrics_composition_and_demo_label() -> None:
    result = evaluate_grouped_baseline(_labelled_frame())

    assert result["cv_strategy"] == "leave_one_theme_out"
    assert result["demo_only"] is True
    assert result["evidence_status"] == DEMO_ONLY_LABEL
    assert result["classes"] == [0, 1]
    assert len(result["folds"]) == 3
    assert len(result["confusion_matrix"]) == 2
    assert 0.0 <= result["macro_f1_mean"] <= 1.0
    assert 0.0 <= result["balanced_accuracy_mean"] <= 1.0
    for fold in result["folds"]:
        assert set(fold["train_conversations"]).isdisjoint(fold["test_conversations"])
        assert fold["test_themes"] == [fold["held_out_theme"]]
        assert len(fold["confusion_matrix"]) == 2
        assert len(fold["train_class_balance"]) == 2
        assert len(fold["test_class_balance"]) == 2


def test_baseline_output_is_deterministic() -> None:
    frame = _labelled_frame()
    first = evaluate_grouped_baseline(frame)
    second = evaluate_grouped_baseline(frame)
    assert first == second
