"""Tests for conversation-level trajectory and matched-condition analysis."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.trajectory_analysis import (
    bootstrap_ci,
    bootstrap_matched_comparison_ci,
    matched_descriptive_comparisons,
    summarize_conversations,
)


def _complete_turn_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": ["run-1"] * 6,
            "script_id": ["script-1"] * 6,
            "repetition": [1] * 6,
            "model_slot": ["model_a"] * 6,
            "context_condition": ["no_preloaded_context"] * 6,
            "turn_number": [1, 2, 3, 4, 5, 6],
            "A1": [0, 1, 2, 2, 1, 0],
            "A2": [0, 0, 1, 2, 1, 0],
            "A3": [0, 0, 0, 1, 1, 1],
        }
    )


def test_conversation_summary_captures_onset_persistence_recovery_and_final() -> None:
    summary = summarize_conversations(_complete_turn_rows()).iloc[0]

    assert summary["mean_A1"] == pytest.approx(1.0)
    assert summary["mean_A2"] == pytest.approx(2 / 3)
    assert summary["mean_A3"] == pytest.approx(0.5)
    assert summary["max_A1"] == 2
    assert summary["max_A2"] == 2
    assert bool(summary["any_A1_2"])
    assert summary["first_A1_2_turn"] == 3
    assert summary["first_A3_safety_turn"] == 4
    assert summary["post_onset_observed_turns"] == 3
    assert summary["post_onset_high_risk_turns"] == 1
    assert summary["persistence_after_onset_rate"] == pytest.approx(1 / 3)
    assert not bool(summary["persistent_after_onset"])
    assert bool(summary["recovery_after_high_risk_turn"])
    assert summary["first_recovery_turn"] == 5
    assert summary["final_A1"] == 0
    assert summary["final_minus_mean_A1"] == pytest.approx(-1)
    assert summary["final_minus_max_A1"] == pytest.approx(-2)
    assert summary["completeness_rate"] == 1
    assert bool(summary["is_complete"])


def test_summary_handles_missing_invalid_and_absent_axis_data() -> None:
    rows = pd.DataFrame(
        {
            "run_id": ["partial"] * 4,
            "script_id": ["script-1"] * 4,
            "turn_number": [1, 2, 4, 6],
            "A1": [None, "2", 99, 1],
            "A3": [0, None, 1, None],
            # A2 is deliberately absent and is treated as entirely missing.
        }
    )

    summary = summarize_conversations(rows).iloc[0]

    assert summary["observed_A1"] == 2
    assert summary["missing_A1"] == 4
    assert summary["observed_A2"] == 0
    assert math.isnan(summary["mean_A2"])
    assert summary["first_A1_2_turn"] == 2
    assert summary["first_A3_safety_turn"] == 4
    assert summary["missing_turn_rows"] == 2
    assert summary["missing_score_cells"] == 14
    assert summary["completeness_rate"] == pytest.approx(4 / 18)
    assert summary["final_A1"] == 1
    assert math.isnan(summary["final_A3"])
    assert not bool(summary["is_complete"])


def test_valid_na_ratings_count_as_complete_but_not_numeric() -> None:
    rows = _complete_turn_rows()
    rows[["A2", "A3"]] = rows[["A2", "A3"]].astype(object)
    rows.loc[0, "A2"] = "N/A"
    rows.loc[1, "A3"] = "N/A"

    summary = summarize_conversations(rows).iloc[0]

    assert summary["completeness_rate"] == 1
    assert bool(summary["is_complete"])
    assert summary["observed_A2"] == 6
    assert summary["observed_A3"] == 6
    assert summary["mean_A2"] == pytest.approx(4 / 5)
    assert summary["mean_A3"] == pytest.approx(3 / 5)


def test_missing_follow_up_makes_persistence_and_recovery_not_assessable() -> None:
    rows = pd.DataFrame(
        {
            "run_id": ["onset-at-end"],
            "turn_number": [6],
            "A1": [2],
            "A2": [0],
            "A3": [0],
        }
    )
    summary = summarize_conversations(rows).iloc[0]

    assert summary["any_A1_2"]
    assert pd.isna(summary["persistence_after_onset_rate"])
    assert pd.isna(summary["persistent_after_onset"])
    assert pd.isna(summary["recovery_after_high_risk_turn"])


def test_conflicting_duplicate_turn_scores_are_missing_not_silently_selected() -> None:
    rows = pd.DataFrame(
        {
            "run_id": ["duplicate", "duplicate"],
            "turn_number": [1, 1],
            "A1": [0, 2],
            "A2": [1, 1],
            "A3": [0, 0],
        }
    )
    summary = summarize_conversations(rows, expected_turns=1).iloc[0]

    assert summary["duplicate_turn_rows"] == 1
    assert pd.isna(summary["mean_A1"])
    assert summary["mean_A2"] == 1
    assert summary["missing_score_cells"] == 1


def _factorial_conversations() -> pd.DataFrame:
    rows = []
    values = {
        ("model_a", "none"): [0.0, 1.0],
        ("model_b", "none"): [1.0, 3.0],
        ("model_a", "prefix"): [2.0, 2.0],
        ("model_b", "prefix"): [4.0, 3.0],
    }
    for (model, context), outcomes in values.items():
        for repetition, outcome in enumerate(outcomes, start=1):
            rows.append(
                {
                    "run_id": f"s1-{model}-{context}-{repetition}",
                    "script_id": "s1",
                    "repetition": repetition,
                    "model_slot": model,
                    "context_condition": context,
                    "mean_A1": outcome,
                }
            )
    return pd.DataFrame(rows)


def test_matched_comparisons_preserve_script_repetition_and_other_factor() -> None:
    comparisons = matched_descriptive_comparisons(_factorial_conversations(), outcomes=["mean_A1"])

    model = comparisons[comparisons["factor"] == "model_slot"].iloc[0]
    assert model["level_a"] == "model_a"
    assert model["level_b"] == "model_b"
    assert model["n_pairs"] == 4
    assert model["mean_difference"] == pytest.approx(1.5)

    context = comparisons[comparisons["factor"] == "context_condition"].iloc[0]
    assert context["level_a"] == "none"
    assert context["level_b"] == "prefix"
    assert context["n_pairs"] == 4
    assert context["mean_difference"] == pytest.approx(1.5)


def test_matched_comparisons_report_incomplete_pairs_without_crashing() -> None:
    data = _factorial_conversations()
    missing_run = "s1-model_b-prefix-2"
    data.loc[data["run_id"] == missing_run, "mean_A1"] = None
    comparisons = matched_descriptive_comparisons(data, outcomes=["mean_A1"])

    model = comparisons[comparisons["factor"] == "model_slot"].iloc[0]
    assert model["n_pairs"] == 3
    assert model["n_unmatched_a"] == 1
    assert model["n_unmatched_b"] == 0


def test_seeded_bootstrap_is_reproducible_for_conversations_and_clusters() -> None:
    data = pd.DataFrame(
        {
            "run_id": ["r1", "r2", "r3", "r4"],
            "script_id": ["s1", "s1", "s2", "s2"],
            "mean_A1": [0.0, 1.0, 3.0, 4.0],
        }
    )

    conversation_a = bootstrap_ci(data, "mean_A1", n_resamples=200, seed=17)
    conversation_b = bootstrap_ci(data, "mean_A1", n_resamples=200, seed=17)
    assert conversation_a == conversation_b
    assert conversation_a["estimate"] == 2
    assert conversation_a["n_units"] == 4

    cluster_a = bootstrap_ci(
        data,
        "mean_A1",
        resample_unit="script_cluster",
        n_resamples=200,
        seed=23,
    )
    cluster_b = bootstrap_ci(
        data,
        "mean_A1",
        resample_unit="script_cluster",
        n_resamples=200,
        seed=23,
    )
    assert cluster_a == cluster_b
    assert cluster_a["n_units"] == 2
    assert cluster_a["ci_lower"] <= cluster_a["estimate"] <= cluster_a["ci_upper"]


def test_bootstrap_rejects_turn_rows_as_independent_units() -> None:
    turns = pd.DataFrame(
        {
            "run_id": ["r1", "r1"],
            "script_id": ["s1", "s1"],
            "turn_number": [1, 2],
            "A1": [0, 2],
        }
    )

    with pytest.raises(ValueError, match="one row per conversation"):
        bootstrap_ci(turns, "A1", n_resamples=10)


def test_matched_bootstrap_is_seeded_and_uses_complete_pairs() -> None:
    data = _factorial_conversations()
    first = bootstrap_matched_comparison_ci(
        data,
        outcome="mean_A1",
        condition_column="model_slot",
        level_a="model_a",
        level_b="model_b",
        match_columns=("script_id", "repetition", "context_condition"),
        resample_unit="script_cluster",
        n_resamples=100,
        seed=5,
    )
    second = bootstrap_matched_comparison_ci(
        data,
        outcome="mean_A1",
        condition_column="model_slot",
        level_a="model_a",
        level_b="model_b",
        match_columns=("script_id", "repetition", "context_condition"),
        resample_unit="script_cluster",
        n_resamples=100,
        seed=5,
    )

    assert first == second
    assert first["n_pairs"] == 4
    assert first["estimate"] == pytest.approx(1.5)
    assert first["resample_unit"] == "script_cluster"


def test_empty_inputs_return_stable_empty_outputs() -> None:
    summary = summarize_conversations(pd.DataFrame())
    comparisons = matched_descriptive_comparisons(pd.DataFrame())
    bootstrap = bootstrap_ci(pd.DataFrame(), "mean_A1", n_resamples=10)

    assert summary.empty
    assert "mean_A1" in summary.columns
    assert comparisons.empty
    assert math.isnan(bootstrap["estimate"])
    assert bootstrap["n_successful_resamples"] == 0
