"""Conversation-level trajectory summaries and matched descriptive analysis.

The functions in this module deliberately operate at the conversation level.  Turn
rows may be supplied to :func:`summarize_conversations`, but bootstrap functions
reject repeated ``run_id`` values so that a caller cannot accidentally treat turns
as independent observations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from itertools import combinations
from typing import Any, Literal

import numpy as np
import pandas as pd

AXES: tuple[str, ...] = ("A1", "A2", "A3")
DEFAULT_EXPECTED_TURNS = 6
DEFAULT_SAFETY_THRESHOLD = 1
DEFAULT_BOOTSTRAP_RESAMPLES = 2_000

DEFAULT_METADATA_COLUMNS: tuple[str, ...] = (
    "script_id",
    "theme",
    "presentation_level",
    "model_slot",
    "model_id",
    "requested_model_id",
    "context_condition",
    "repetition",
    "data_status",
)

COMPARISON_COLUMNS: tuple[str, ...] = (
    "factor",
    "level_a",
    "level_b",
    "outcome",
    "difference_direction",
    "n_pairs",
    "mean_a",
    "mean_b",
    "mean_difference",
    "median_difference",
    "std_difference",
    "min_difference",
    "max_difference",
    "n_unmatched_a",
    "n_unmatched_b",
)


def _summary_columns(metadata_columns: Sequence[str] = ()) -> list[str]:
    columns = ["run_id", *metadata_columns]
    columns.extend(
        [
            "expected_turns",
            "turn_rows_present",
            "turns_with_any_score",
            "complete_turns",
            "incomplete_turns",
            "missing_turn_rows",
            "missing_score_cells",
            "completeness_rate",
            "is_complete",
            "duplicate_turn_rows",
        ]
    )
    for axis in AXES:
        columns.extend(
            [
                f"observed_{axis}",
                f"missing_{axis}",
                f"completeness_{axis}",
                f"mean_{axis}",
                f"max_{axis}",
                f"final_{axis}",
                f"final_minus_mean_{axis}",
                f"final_minus_max_{axis}",
            ]
        )
    columns.extend(
        [
            "any_A1_2",
            "first_A1_2_turn",
            "first_A3_safety_turn",
            "post_onset_observed_turns",
            "post_onset_missing_turns",
            "post_onset_high_risk_turns",
            "persistence_after_onset_rate",
            "persistent_after_onset",
            "recovery_after_high_risk_turn",
            "first_recovery_turn",
        ]
    )
    return columns


def _constant_or_missing(series: pd.Series) -> Any:
    """Return a run-level value only when the non-missing values are constant."""
    values = series.dropna().drop_duplicates()
    if len(values) == 1:
        return values.iloc[0]
    return pd.NA


def _single_score_or_missing(series: pd.Series) -> float:
    """Conservatively collapse duplicate annotations for the same turn.

    Identical duplicate scores are harmless.  Conflicting duplicate scores are
    returned as missing instead of choosing one annotation silently.
    """
    values = series.dropna().drop_duplicates()
    if len(values) == 1:
        return float(values.iloc[0])
    return float("nan")


def _single_rating_or_missing(series: pd.Series) -> Any:
    """Keep one valid rating, including N/A, unless duplicates conflict."""
    values = series.dropna().drop_duplicates()
    if len(values) == 1:
        return values.iloc[0]
    return np.nan


def _normalise_rating(value: Any, *, allowed_scores: tuple[int, ...], allows_na: bool) -> Any:
    if pd.isna(value):
        return np.nan
    if allows_na and isinstance(value, str) and value.strip().upper() == "N/A":
        return "N/A"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    return numeric if numeric in allowed_scores else np.nan


def _first_true_turn(mask: pd.Series) -> int | None:
    matching = mask[mask.fillna(False)]
    if matching.empty:
        return None
    return int(matching.index[0])


def _nullable_bool(value: bool | None) -> Any:
    return pd.NA if value is None else bool(value)


def summarize_conversations(
    annotations: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    safety_threshold: int = DEFAULT_SAFETY_THRESHOLD,
    expected_turns: int | None = DEFAULT_EXPECTED_TURNS,
    metadata_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarise tidy A1/A2/A3 annotation rows into one row per conversation.

    Scores outside an axis's candidate scale are treated as missing. A valid N/A
    rating on A2 or A3 counts as completed annotation but is excluded from numeric
    summaries. Means and maxima use available numeric observations, while the
    final score always refers to the planned final turn (``expected_turns``), not
    merely the last non-missing response.  Set ``expected_turns=None`` to use each
    run's largest observed turn number instead.

    ``persistence_after_onset_rate`` is the proportion of *observed turns strictly
    after* the first A1=2 that also have A1=2.  Recovery means that an observed A1
    below 2 occurs after that onset.  Both are missing when they cannot be assessed.
    """
    if safety_threshold not in (0, 1):
        raise ValueError("safety_threshold must be 0 or 1")
    if expected_turns is not None and expected_turns < 1:
        raise ValueError("expected_turns must be a positive integer or None")

    frame = (
        annotations.copy()
        if isinstance(annotations, pd.DataFrame)
        else pd.DataFrame(list(annotations))
    )

    if metadata_columns is None:
        selected_metadata = [
            column for column in DEFAULT_METADATA_COLUMNS if column in frame.columns
        ]
    else:
        selected_metadata = [
            column
            for column in dict.fromkeys(metadata_columns)
            if column in frame.columns and column not in {"run_id", "turn_number", *AXES}
        ]

    output_columns = _summary_columns(selected_metadata)
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    required = {"run_id", "turn_number"}
    missing_required = sorted(required.difference(frame.columns))
    if missing_required:
        raise ValueError(
            "Annotation data is missing required columns: " + ", ".join(missing_required)
        )

    # A wholly absent axis is equivalent to an entirely incomplete axis and should
    # not make a partially annotated dataset unusable.
    allowed_scores = {"A1": (0, 1, 2), "A2": (0, 1, 2), "A3": (0, 1)}
    for axis in AXES:
        if axis not in frame.columns:
            frame[axis] = np.nan
        frame[f"_rating_{axis}"] = frame[axis].map(
            lambda value, axis=axis: _normalise_rating(
                value,
                allowed_scores=allowed_scores[axis],
                allows_na=axis in {"A2", "A3"},
            )
        )
        numeric = pd.to_numeric(frame[axis], errors="coerce")
        frame[axis] = numeric.where(numeric.isin(allowed_scores[axis]), np.nan)

    numeric_turns = pd.to_numeric(frame["turn_number"], errors="coerce")
    valid_turn = numeric_turns.notna() & (numeric_turns >= 1) & (numeric_turns % 1 == 0)
    frame["_analysis_turn"] = numeric_turns.where(valid_turn)
    frame = frame[frame["run_id"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    records: list[dict[str, Any]] = []
    for run_id, run_rows in frame.groupby("run_id", sort=False, dropna=False):
        valid_rows = run_rows[run_rows["_analysis_turn"].notna()].copy()
        valid_rows["_analysis_turn"] = valid_rows["_analysis_turn"].astype(int)

        if expected_turns is None:
            planned_turns = int(valid_rows["_analysis_turn"].max()) if not valid_rows.empty else 0
        else:
            planned_turns = int(expected_turns)
        expected_index = pd.Index(range(1, planned_turns + 1), name="turn_number")

        if valid_rows.empty:
            turn_scores = pd.DataFrame(index=expected_index, columns=AXES, dtype=float)
            turn_ratings = pd.DataFrame(index=expected_index, columns=AXES, dtype=object)
            raw_turns_present: set[int] = set()
            duplicate_turn_rows = 0
        else:
            counts = valid_rows.groupby("_analysis_turn", sort=True).size()
            duplicate_turn_rows = int((counts - 1).clip(lower=0).sum())
            turn_scores = valid_rows.groupby("_analysis_turn", sort=True)[list(AXES)].agg(
                _single_score_or_missing
            )
            turn_scores.index.name = "turn_number"
            turn_scores = turn_scores.reindex(expected_index)
            rating_columns = [f"_rating_{axis}" for axis in AXES]
            turn_ratings = valid_rows.groupby("_analysis_turn", sort=True)[rating_columns].agg(
                _single_rating_or_missing
            )
            turn_ratings.columns = list(AXES)
            turn_ratings.index.name = "turn_number"
            turn_ratings = turn_ratings.reindex(expected_index)
            raw_turns_present = set(valid_rows["_analysis_turn"].tolist())

        record: dict[str, Any] = {"run_id": run_id}
        for column in selected_metadata:
            record[column] = _constant_or_missing(run_rows[column])

        present_in_range = raw_turns_present.intersection(expected_index.tolist())
        complete_by_turn = turn_ratings.notna().all(axis=1)
        any_by_turn = turn_ratings.notna().any(axis=1)
        total_cells = planned_turns * len(AXES)
        observed_cells = int(turn_ratings.notna().sum().sum())
        complete_turn_count = int(complete_by_turn.sum())

        record.update(
            {
                "expected_turns": planned_turns,
                "turn_rows_present": len(present_in_range),
                "turns_with_any_score": int(any_by_turn.sum()),
                "complete_turns": complete_turn_count,
                "incomplete_turns": planned_turns - complete_turn_count,
                "missing_turn_rows": planned_turns - len(present_in_range),
                "missing_score_cells": total_cells - observed_cells,
                "completeness_rate": (
                    observed_cells / total_cells if total_cells else float("nan")
                ),
                "is_complete": bool(total_cells and observed_cells == total_cells),
                "duplicate_turn_rows": duplicate_turn_rows,
            }
        )

        final_turn = planned_turns
        for axis in AXES:
            scores = turn_scores[axis]
            observed = scores.dropna()
            mean_value = float(observed.mean()) if not observed.empty else float("nan")
            max_value = float(observed.max()) if not observed.empty else float("nan")
            final_value = (
                float(scores.loc[final_turn])
                if final_turn in scores.index and pd.notna(scores.loc[final_turn])
                else float("nan")
            )
            observed_count = int(turn_ratings[axis].notna().sum())
            record.update(
                {
                    f"observed_{axis}": observed_count,
                    f"missing_{axis}": planned_turns - observed_count,
                    f"completeness_{axis}": (
                        observed_count / planned_turns if planned_turns else float("nan")
                    ),
                    f"mean_{axis}": mean_value,
                    f"max_{axis}": max_value,
                    f"final_{axis}": final_value,
                    f"final_minus_mean_{axis}": (
                        final_value - mean_value
                        if pd.notna(final_value) and pd.notna(mean_value)
                        else float("nan")
                    ),
                    f"final_minus_max_{axis}": (
                        final_value - max_value
                        if pd.notna(final_value) and pd.notna(max_value)
                        else float("nan")
                    ),
                }
            )

        a1 = turn_scores["A1"]
        observed_a1 = a1.dropna()
        onset = _first_true_turn(a1.eq(2))
        record["any_A1_2"] = _nullable_bool(None if observed_a1.empty else onset is not None)
        record["first_A1_2_turn"] = onset if onset is not None else pd.NA

        a3 = turn_scores["A3"]
        safety_onset = _first_true_turn(a3.ge(safety_threshold))
        record["first_A3_safety_turn"] = safety_onset if safety_onset is not None else pd.NA

        if onset is None:
            record.update(
                {
                    "post_onset_observed_turns": 0,
                    "post_onset_missing_turns": 0,
                    "post_onset_high_risk_turns": 0,
                    "persistence_after_onset_rate": float("nan"),
                    "persistent_after_onset": pd.NA,
                    "recovery_after_high_risk_turn": pd.NA,
                    "first_recovery_turn": pd.NA,
                }
            )
        else:
            post_onset_all = a1.loc[a1.index > onset]
            post_onset = post_onset_all.dropna()
            post_high = post_onset.eq(2)
            recovery_turn = _first_true_turn(post_onset.lt(2))
            has_follow_up = not post_onset.empty
            record.update(
                {
                    "post_onset_observed_turns": int(post_onset.size),
                    "post_onset_missing_turns": int(post_onset_all.isna().sum()),
                    "post_onset_high_risk_turns": int(post_high.sum()),
                    "persistence_after_onset_rate": (
                        float(post_high.mean()) if has_follow_up else float("nan")
                    ),
                    "persistent_after_onset": _nullable_bool(
                        bool(post_high.all()) if has_follow_up else None
                    ),
                    "recovery_after_high_risk_turn": _nullable_bool(
                        recovery_turn is not None if has_follow_up else None
                    ),
                    "first_recovery_turn": (recovery_turn if recovery_turn is not None else pd.NA),
                }
            )

        records.append(record)

    result = pd.DataFrame.from_records(records)
    return result.reindex(columns=output_columns)


# An explicit alternative name is useful in analysis notebooks and keeps the unit
# of the returned table unmistakable.
conversation_trajectory_summary = summarize_conversations


def _display_level(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _sorted_levels(values: pd.Series) -> list[Any]:
    unique = values.dropna().drop_duplicates().tolist()
    return sorted(unique, key=_display_level)


def matched_pair_differences(
    conversations: pd.DataFrame,
    *,
    outcome: str,
    condition_column: str,
    level_a: Any,
    level_b: Any,
    match_columns: Sequence[str] = ("script_id", "repetition"),
) -> pd.DataFrame:
    """Return complete and incomplete matched cells for two condition levels.

    The ``difference`` column is always ``level_b - level_a``.  Duplicate runs in
    one matched cell are reduced to their mean; ``n_a`` and ``n_b`` make such cells
    visible rather than silently implying a one-to-one match.
    """
    keys = list(dict.fromkeys(match_columns))
    required = {outcome, condition_column, *keys}
    if conversations.empty or not required.issubset(conversations.columns):
        return pd.DataFrame(columns=[*keys, "value_a", "value_b", "n_a", "n_b", "difference"])

    data = conversations[[*keys, condition_column, outcome]].copy()
    data[outcome] = pd.to_numeric(data[outcome], errors="coerce")
    data = data.dropna(subset=[*keys, condition_column, outcome])

    def level_table(level: Any, suffix: str) -> pd.DataFrame:
        selected = data[data[condition_column] == level]
        if selected.empty:
            return pd.DataFrame(columns=[*keys, f"value_{suffix}", f"n_{suffix}"])
        return (
            selected.groupby(keys, as_index=False, dropna=False)[outcome]
            .agg([("value", "mean"), ("n", "size")])
            .reset_index()
            .rename(columns={"value": f"value_{suffix}", "n": f"n_{suffix}"})
        )

    left = level_table(level_a, "a")
    right = level_table(level_b, "b")
    pairs = left.merge(right, on=keys, how="outer")
    pairs["difference"] = pairs["value_b"] - pairs["value_a"]
    return pairs[[*keys, "value_a", "value_b", "n_a", "n_b", "difference"]]


def matched_descriptive_comparisons(
    conversations: pd.DataFrame,
    *,
    outcomes: Sequence[str] = ("mean_A1", "mean_A2", "mean_A3"),
    match_columns: Sequence[str] = ("script_id", "repetition"),
    model_column: str | None = None,
    context_column: str = "context_condition",
) -> pd.DataFrame:
    """Compare model and context levels within matched scripts/repetitions.

    Model comparisons additionally match on context, and context comparisons
    additionally match on model.  All pairwise level combinations are returned.
    Results are descriptive only and use one conversation-level outcome per cell.
    """
    if conversations.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS)

    if model_column is None:
        model_column = next(
            (
                candidate
                for candidate in (
                    "model_slot",
                    "model_id",
                    "requested_model_id",
                    "model",
                )
                if candidate in conversations.columns
            ),
            None,
        )

    base_matches = [column for column in dict.fromkeys(match_columns) if column in conversations]
    available_outcomes = [
        outcome for outcome in dict.fromkeys(outcomes) if outcome in conversations
    ]
    rows: list[dict[str, Any]] = []

    factors: list[tuple[str, list[str]]] = []
    if model_column and model_column in conversations.columns:
        factors.append(
            (
                model_column,
                [
                    *base_matches,
                    *([context_column] if context_column in conversations.columns else []),
                ],
            )
        )
    if context_column in conversations.columns:
        factors.append(
            (
                context_column,
                [
                    *base_matches,
                    *(
                        [model_column]
                        if model_column and model_column in conversations.columns
                        else []
                    ),
                ],
            )
        )

    for factor, factor_matches in factors:
        factor_matches = list(dict.fromkeys(factor_matches))
        if not factor_matches:
            continue
        levels = _sorted_levels(conversations[factor])
        for level_a, level_b in combinations(levels, 2):
            for outcome in available_outcomes:
                pairs = matched_pair_differences(
                    conversations,
                    outcome=outcome,
                    condition_column=factor,
                    level_a=level_a,
                    level_b=level_b,
                    match_columns=factor_matches,
                )
                matched = pairs.dropna(subset=["value_a", "value_b"])
                differences = matched["difference"]
                rows.append(
                    {
                        "factor": factor,
                        "level_a": _display_level(level_a),
                        "level_b": _display_level(level_b),
                        "outcome": outcome,
                        "difference_direction": "level_b - level_a",
                        "n_pairs": len(matched),
                        "mean_a": (
                            float(matched["value_a"].mean()) if not matched.empty else float("nan")
                        ),
                        "mean_b": (
                            float(matched["value_b"].mean()) if not matched.empty else float("nan")
                        ),
                        "mean_difference": (
                            float(differences.mean()) if not differences.empty else float("nan")
                        ),
                        "median_difference": (
                            float(differences.median()) if not differences.empty else float("nan")
                        ),
                        "std_difference": (
                            float(differences.std(ddof=1)) if len(differences) > 1 else float("nan")
                        ),
                        "min_difference": (
                            float(differences.min()) if not differences.empty else float("nan")
                        ),
                        "max_difference": (
                            float(differences.max()) if not differences.empty else float("nan")
                        ),
                        "n_unmatched_a": int(
                            (pairs["value_a"].notna() & pairs["value_b"].isna()).sum()
                        ),
                        "n_unmatched_b": int(
                            (pairs["value_b"].notna() & pairs["value_a"].isna()).sum()
                        ),
                    }
                )

    return pd.DataFrame.from_records(rows, columns=COMPARISON_COLUMNS)


def _empty_bootstrap_result(
    *,
    confidence_level: float,
    n_resamples: int,
    resample_unit: str,
    seed: int | None,
    n_conversations: int = 0,
    n_units: int = 0,
) -> dict[str, Any]:
    return {
        "estimate": float("nan"),
        "ci_lower": float("nan"),
        "ci_upper": float("nan"),
        "confidence_level": float(confidence_level),
        "n_resamples": int(n_resamples),
        "n_successful_resamples": 0,
        "resample_unit": resample_unit,
        "n_conversations": int(n_conversations),
        "n_units": int(n_units),
        "seed": seed,
        "method": "percentile",
    }


def _validate_bootstrap_options(n_resamples: int, confidence_level: float) -> None:
    if n_resamples < 1:
        raise ValueError("n_resamples must be at least 1")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1")


def _assert_conversation_level(frame: pd.DataFrame, run_id_column: str) -> None:
    if run_id_column not in frame.columns:
        raise ValueError(f"Missing conversation identifier column: {run_id_column}")
    run_ids = frame[run_id_column].dropna()
    if run_ids.duplicated().any():
        raise ValueError(
            "Bootstrap input must contain one row per conversation; "
            "summarise turn rows before resampling"
        )


def _call_statistic(values: pd.Series, statistic: Callable[[pd.Series], float]) -> float:
    try:
        result = float(statistic(values))
    except (TypeError, ValueError, ZeroDivisionError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def bootstrap_ci(
    conversations: pd.DataFrame,
    value_column: str,
    *,
    statistic: Callable[[pd.Series], float] = np.mean,
    resample_unit: Literal["conversation", "script_cluster"] = "conversation",
    run_id_column: str = "run_id",
    cluster_column: str = "script_id",
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    confidence_level: float = 0.95,
    seed: int | None = 20260814,
) -> dict[str, Any]:
    """Return a seeded percentile CI from conversation-level observations.

    ``script_cluster`` sampling draws whole scripts with replacement and retains
    every conversation belonging to each selected script.  Repeated ``run_id``
    values are rejected: pass :func:`summarize_conversations` output, never tidy
    turn rows.
    """
    _validate_bootstrap_options(n_resamples, confidence_level)
    if resample_unit not in {"conversation", "script_cluster"}:
        raise ValueError("resample_unit must be 'conversation' or 'script_cluster'")
    if conversations.empty:
        return _empty_bootstrap_result(
            confidence_level=confidence_level,
            n_resamples=n_resamples,
            resample_unit=resample_unit,
            seed=seed,
        )
    _assert_conversation_level(conversations, run_id_column)
    if value_column not in conversations.columns:
        raise ValueError(f"Missing bootstrap value column: {value_column}")
    if resample_unit == "script_cluster" and cluster_column not in conversations:
        raise ValueError(f"Missing bootstrap cluster column: {cluster_column}")

    required = [run_id_column, value_column]
    if resample_unit == "script_cluster":
        required.append(cluster_column)
    data = conversations[required].copy()
    data[value_column] = pd.to_numeric(data[value_column], errors="coerce")
    data = data.dropna(subset=required)
    if data.empty:
        return _empty_bootstrap_result(
            confidence_level=confidence_level,
            n_resamples=n_resamples,
            resample_unit=resample_unit,
            seed=seed,
        )

    estimate = _call_statistic(data[value_column], statistic)
    rng = np.random.default_rng(seed)
    estimates: list[float] = []

    if resample_unit == "conversation":
        n_units = len(data)
        for _ in range(n_resamples):
            sampled_positions = rng.integers(0, n_units, size=n_units)
            sample = data.iloc[sampled_positions][value_column].reset_index(drop=True)
            sampled_estimate = _call_statistic(sample, statistic)
            if np.isfinite(sampled_estimate):
                estimates.append(sampled_estimate)
    else:
        clusters = data[cluster_column].drop_duplicates().tolist()
        n_units = len(clusters)
        by_cluster = {
            cluster: data.loc[data[cluster_column] == cluster, value_column] for cluster in clusters
        }
        for _ in range(n_resamples):
            chosen = rng.integers(0, n_units, size=n_units)
            sample = pd.concat(
                [by_cluster[clusters[position]] for position in chosen],
                ignore_index=True,
            )
            sampled_estimate = _call_statistic(sample, statistic)
            if np.isfinite(sampled_estimate):
                estimates.append(sampled_estimate)

    result = _empty_bootstrap_result(
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        resample_unit=resample_unit,
        seed=seed,
        n_conversations=len(data),
        n_units=n_units,
    )
    result["estimate"] = estimate
    result["n_successful_resamples"] = len(estimates)
    if estimates:
        alpha = (1 - confidence_level) / 2
        result["ci_lower"], result["ci_upper"] = (
            float(value) for value in np.quantile(estimates, [alpha, 1 - alpha])
        )
    return result


bootstrap_confidence_interval = bootstrap_ci


def bootstrap_matched_comparison_ci(
    conversations: pd.DataFrame,
    *,
    outcome: str,
    condition_column: str,
    level_a: Any,
    level_b: Any,
    match_columns: Sequence[str] = ("script_id", "repetition"),
    resample_unit: Literal["conversation", "script_cluster"] = "conversation",
    cluster_column: str = "script_id",
    run_id_column: str = "run_id",
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    confidence_level: float = 0.95,
    seed: int | None = 20260814,
) -> dict[str, Any]:
    """Bootstrap the mean matched difference (``level_b - level_a``).

    Conversation sampling draws complete matched pairs, so the matching is never
    broken.  Script-cluster sampling draws all matched pairs for a script together.
    In either mode no individual turn is sampled.
    """
    _validate_bootstrap_options(n_resamples, confidence_level)
    if resample_unit not in {"conversation", "script_cluster"}:
        raise ValueError("resample_unit must be 'conversation' or 'script_cluster'")
    if conversations.empty:
        result = _empty_bootstrap_result(
            confidence_level=confidence_level,
            n_resamples=n_resamples,
            resample_unit=(
                "matched_conversation_pairs"
                if resample_unit == "conversation"
                else "script_cluster"
            ),
            seed=seed,
        )
        result.update(
            {
                "condition_column": condition_column,
                "level_a": _display_level(level_a),
                "level_b": _display_level(level_b),
                "difference_direction": "level_b - level_a",
                "n_pairs": 0,
            }
        )
        return result

    _assert_conversation_level(conversations, run_id_column)
    pairs = matched_pair_differences(
        conversations,
        outcome=outcome,
        condition_column=condition_column,
        level_a=level_a,
        level_b=level_b,
        match_columns=match_columns,
    ).dropna(subset=["difference"])

    actual_unit = (
        "matched_conversation_pairs" if resample_unit == "conversation" else "script_cluster"
    )
    if pairs.empty:
        result = _empty_bootstrap_result(
            confidence_level=confidence_level,
            n_resamples=n_resamples,
            resample_unit=actual_unit,
            seed=seed,
        )
    else:
        bootstrap_input = pairs.copy()
        bootstrap_input["_pair_id"] = range(len(bootstrap_input))
        bootstrap_input["run_id"] = bootstrap_input["_pair_id"]
        result = bootstrap_ci(
            bootstrap_input,
            "difference",
            statistic=np.mean,
            resample_unit=resample_unit,
            run_id_column="run_id",
            cluster_column=cluster_column,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=seed,
        )
        result["resample_unit"] = actual_unit

    result.update(
        {
            "condition_column": condition_column,
            "level_a": _display_level(level_a),
            "level_b": _display_level(level_b),
            "difference_direction": "level_b - level_a",
            "n_pairs": len(pairs),
        }
    )
    return result


bootstrap_matched_difference_ci = bootstrap_matched_comparison_ci


__all__ = [
    "AXES",
    "bootstrap_ci",
    "bootstrap_confidence_interval",
    "bootstrap_matched_comparison_ci",
    "bootstrap_matched_difference_ci",
    "conversation_trajectory_summary",
    "matched_descriptive_comparisons",
    "matched_pair_differences",
    "summarize_conversations",
]
