from __future__ import annotations

import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import rankdata, wilcoxon

from src.annotation import (
    linearly_weighted_cohen_kappa,
    ordinary_cohen_kappa,
)

V1 = ROOT / "data" / "private" / "analysis-v1"
V2 = ROOT / "data" / "private" / "analysis-v2"

PRIMARY = V1 / "primary"
AGREEMENT = V1 / "agreement"

OUTPUT = ROOT / "data" / "private" / "analysis-v3"
TABLES = OUTPUT / "tables"
FIGURES = OUTPUT / "figures"

ALL_AXES = ("A1", "A2", "A3", "B1", "B2", "B3", "C1")
PRIMARY_AXES = ("A1", "A2", "A3")
EXPLORATORY_AXES = ("B1", "B2", "B3", "C1")

JUDGES = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.3-flash",
)

SEED = 20260902
N_BOOTSTRAP = 10000


def numeric(series):
    return pd.to_numeric(series, errors="coerce")


def holm_adjust(values):
    p = np.asarray(values, dtype=float)
    adjusted = np.full(len(p), np.nan)

    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return adjusted

    order = valid[np.argsort(p[valid])]
    previous = 0.0
    m = len(order)

    for rank, index in enumerate(order):
        value = min(
            1.0,
            (m - rank) * p[index],
        )
        value = max(value, previous)
        adjusted[index] = value
        previous = value

    return adjusted


def rank_biserial(values):
    values = np.asarray(values, dtype=float)
    values = values[
        np.isfinite(values)
        & (values != 0)
    ]

    if len(values) == 0:
        return 0.0

    ranks = rankdata(
        np.abs(values),
        method="average",
    )

    positive = ranks[values > 0].sum()
    negative = ranks[values < 0].sum()

    denominator = positive + negative

    if denominator == 0:
        return 0.0

    return float(
        (positive - negative)
        / denominator
    )


def bootstrap_mean_ci(
    values,
    *,
    seed,
):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan, np.nan

    rng = np.random.default_rng(seed)

    sample = rng.choice(
        values,
        size=(N_BOOTSTRAP, len(values)),
        replace=True,
    )

    estimates = sample.mean(axis=1)

    low, high = np.quantile(
        estimates,
        [0.025, 0.975],
    )

    return float(low), float(high)


def one_sample_test(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan, np.nan

    if np.allclose(values, 0):
        return 0.0, 1.0

    result = wilcoxon(
        values,
        zero_method="wilcox",
        alternative="two-sided",
        method="auto",
    )

    return (
        float(result.statistic),
        float(result.pvalue),
    )


def build_conversation_table(human):
    rows = []

    metadata = [
        "run_id",
        "script_id",
        "theme",
        "presentation_level",
        "model_slot",
        "context_condition",
        "repetition",
    ]

    for run_id, group in human.groupby("run_id"):
        row = {"run_id": run_id}

        for column in metadata:
            if column == "run_id":
                continue
            values = group[column].drop_duplicates()
            row[column] = (
                values.iloc[0]
                if len(values) == 1
                else np.nan
            )

        group = group.sort_values("turn_number")

        for axis in ALL_AXES:
            scores = numeric(group[axis])

            row[f"mean_{axis}"] = (
                float(scores.mean())
                if scores.notna().any()
                else np.nan
            )

            early = scores[
                group["turn_number"].isin([1, 2])
            ]

            late = scores[
                group["turn_number"].isin([5, 6])
            ]

            early_mean = (
                float(early.mean())
                if early.notna().any()
                else np.nan
            )

            late_mean = (
                float(late.mean())
                if late.notna().any()
                else np.nan
            )

            row[f"early_{axis}"] = early_mean
            row[f"late_{axis}"] = late_mean

            row[f"late_minus_early_{axis}"] = (
                late_mean - early_mean
                if (
                    np.isfinite(early_mean)
                    and np.isfinite(late_mean)
                )
                else np.nan
            )

        rows.append(row)

    result = pd.DataFrame(rows)

    if len(result) != 72:
        raise RuntimeError(
            f"Expected 72 conversations; found {len(result)}"
        )

    return result


def matched_values(
    frame,
    *,
    factor,
    level_a,
    level_b,
    outcome,
    match_columns,
):
    columns = [
        *match_columns,
        factor,
        outcome,
    ]

    data = frame[columns].copy()
    data[outcome] = numeric(data[outcome])

    a = (
        data[data[factor].eq(level_a)]
        .groupby(match_columns, as_index=False)[outcome]
        .mean()
        .rename(columns={outcome: "value_a"})
    )

    b = (
        data[data[factor].eq(level_b)]
        .groupby(match_columns, as_index=False)[outcome]
        .mean()
        .rename(columns={outcome: "value_b"})
    )

    pairs = a.merge(
        b,
        on=match_columns,
        how="inner",
    )

    pairs = pairs.dropna(
        subset=["value_a", "value_b"]
    ).copy()

    pairs["difference"] = (
        pairs["value_b"]
        - pairs["value_a"]
    )

    return pairs


def matched_result(
    frame,
    *,
    family,
    factor,
    level_a,
    level_b,
    outcome,
    match_columns,
    seed,
):
    pairs = matched_values(
        frame,
        factor=factor,
        level_a=level_a,
        level_b=level_b,
        outcome=outcome,
        match_columns=match_columns,
    )

    differences = pairs["difference"].to_numpy()

    statistic, p_value = one_sample_test(
        differences
    )

    low, high = bootstrap_mean_ci(
        differences,
        seed=seed,
    )

    return {
        "family": family,
        "factor": factor,
        "level_a": level_a,
        "level_b": level_b,
        "outcome": outcome,
        "difference_direction":
            "level_b - level_a",
        "n_pairs": len(pairs),
        "mean_a":
            float(pairs["value_a"].mean())
            if len(pairs) else np.nan,
        "mean_b":
            float(pairs["value_b"].mean())
            if len(pairs) else np.nan,
        "mean_difference":
            float(differences.mean())
            if len(differences) else np.nan,
        "median_difference":
            float(np.median(differences))
            if len(differences) else np.nan,
        "ci_lower": low,
        "ci_upper": high,
        "wilcoxon_statistic": statistic,
        "p_value": p_value,
        "rank_biserial":
            rank_biserial(differences),
    }


def exploratory_main_effects(conversations):
    rows = []
    counter = 0

    # Presentation
    presentation_matches = [
        "theme",
        "model_slot",
        "context_condition",
        "repetition",
    ]

    for a, b in combinations(
        ["control", "ambiguous", "fixed_belief"],
        2,
    ):
        for axis in EXPLORATORY_AXES:
            rows.append(
                matched_result(
                    conversations,
                    family="exploratory_presentation",
                    factor="presentation_level",
                    level_a=a,
                    level_b=b,
                    outcome=f"mean_{axis}",
                    match_columns=presentation_matches,
                    seed=SEED + counter,
                )
            )
            counter += 1

    # Model
    for axis in EXPLORATORY_AXES:
        rows.append(
            matched_result(
                conversations,
                family="exploratory_model",
                factor="model_slot",
                level_a="model_minimax",
                level_b="model_nemotron",
                outcome=f"mean_{axis}",
                match_columns=[
                    "script_id",
                    "context_condition",
                    "repetition",
                ],
                seed=SEED + counter,
            )
        )
        counter += 1

    # Context
    for axis in EXPLORATORY_AXES:
        rows.append(
            matched_result(
                conversations,
                family="exploratory_context",
                factor="context_condition",
                level_a="no_preloaded_context",
                level_b="standardised_preloaded_context",
                outcome=f"mean_{axis}",
                match_columns=[
                    "script_id",
                    "model_slot",
                    "repetition",
                ],
                seed=SEED + counter,
            )
        )
        counter += 1

    result = pd.DataFrame(rows)

    result["p_holm"] = np.nan

    for family, indexes in result.groupby(
        "family"
    ).groups.items():
        result.loc[
            indexes,
            "p_holm",
        ] = holm_adjust(
            result.loc[
                indexes,
                "p_value",
            ]
        )

    result["significant_0_05"] = (
        result["p_holm"] < 0.05
    )

    return result


def theme_effects(conversations):
    rows = []
    counter = 500

    themes = [
        "ai_relationship",
        "monitoring",
        "personal_messages",
    ]

    for a, b in combinations(themes, 2):
        for axis in ALL_AXES:
            rows.append(
                matched_result(
                    conversations,
                    family="exploratory_theme",
                    factor="theme",
                    level_a=a,
                    level_b=b,
                    outcome=f"mean_{axis}",
                    match_columns=[
                        "presentation_level",
                        "model_slot",
                        "context_condition",
                        "repetition",
                    ],
                    seed=SEED + counter,
                )
            )
            counter += 1

    result = pd.DataFrame(rows)

    result["p_holm"] = holm_adjust(
        result["p_value"]
    )

    result["significant_0_05"] = (
        result["p_holm"] < 0.05
    )

    return result


def model_by_presentation_interactions(
    conversations,
):
    rows = []
    counter = 1000

    presentations = [
        "control",
        "ambiguous",
        "fixed_belief",
    ]

    for axis in ALL_AXES:
        outcome = f"mean_{axis}"

        model_differences = {}

        for presentation in presentations:
            subset = conversations[
                conversations[
                    "presentation_level"
                ].eq(presentation)
            ]

            pairs = matched_values(
                subset,
                factor="model_slot",
                level_a="model_minimax",
                level_b="model_nemotron",
                outcome=outcome,
                match_columns=[
                    "theme",
                    "context_condition",
                    "repetition",
                ],
            )

            model_differences[
                presentation
            ] = pairs[
                [
                    "theme",
                    "context_condition",
                    "repetition",
                    "difference",
                ]
            ].rename(
                columns={
                    "difference":
                        f"model_diff_{presentation}"
                }
            )

        for a, b in combinations(
            presentations,
            2,
        ):
            merged = model_differences[a].merge(
                model_differences[b],
                on=[
                    "theme",
                    "context_condition",
                    "repetition",
                ],
                how="inner",
            )

            interaction = (
                merged[
                    f"model_diff_{b}"
                ]
                - merged[
                    f"model_diff_{a}"
                ]
            ).to_numpy()

            statistic, p_value = (
                one_sample_test(interaction)
            )

            low, high = bootstrap_mean_ci(
                interaction,
                seed=SEED + counter,
            )

            rows.append(
                {
                    "axis": axis,
                    "presentation_a": a,
                    "presentation_b": b,
                    "interaction_definition":
                        "(Nemotron-MiniMax at B) - "
                        "(Nemotron-MiniMax at A)",
                    "n_matched_cells":
                        len(interaction),
                    "mean_interaction":
                        float(
                            interaction.mean()
                        )
                        if len(interaction)
                        else np.nan,
                    "ci_lower": low,
                    "ci_upper": high,
                    "p_value": p_value,
                    "rank_biserial":
                        rank_biserial(
                            interaction
                        ),
                }
            )

            counter += 1

    result = pd.DataFrame(rows)

    result["p_holm"] = holm_adjust(
        result["p_value"]
    )

    result["significant_0_05"] = (
        result["p_holm"] < 0.05
    )

    return result


def presentation_by_time_interactions(
    conversations,
):
    rows = []
    counter = 1500

    presentations = [
        "control",
        "ambiguous",
        "fixed_belief",
    ]

    for axis in PRIMARY_AXES:
        outcome = (
            f"late_minus_early_{axis}"
        )

        for a, b in combinations(
            presentations,
            2,
        ):
            result = matched_result(
                conversations,
                family=
                    "presentation_x_time",
                factor=
                    "presentation_level",
                level_a=a,
                level_b=b,
                outcome=outcome,
                match_columns=[
                    "theme",
                    "model_slot",
                    "context_condition",
                    "repetition",
                ],
                seed=SEED + counter,
            )

            result[
                "interpretation"
            ] = (
                "Difference in late-minus-early "
                "change between presentation levels"
            )

            rows.append(result)
            counter += 1

    result = pd.DataFrame(rows)

    result["p_holm"] = holm_adjust(
        result["p_value"]
    )

    result["significant_0_05"] = (
        result["p_holm"] < 0.05
    )

    return result


def overall_early_late(conversations):
    rows = []

    for axis in ALL_AXES:
        column = (
            f"late_minus_early_{axis}"
        )

        values = numeric(
            conversations[column]
        ).dropna().to_numpy()

        statistic, p_value = (
            one_sample_test(values)
        )

        low, high = bootstrap_mean_ci(
            values,
            seed=SEED + 2000
            + ALL_AXES.index(axis),
        )

        rows.append(
            {
                "axis": axis,
                "n_conversations":
                    len(values),
                "mean_late_minus_early":
                    float(values.mean())
                    if len(values)
                    else np.nan,
                "median_late_minus_early":
                    float(np.median(values))
                    if len(values)
                    else np.nan,
                "ci_lower": low,
                "ci_upper": high,
                "p_value": p_value,
                "rank_biserial":
                    rank_biserial(values),
            }
        )

    result = pd.DataFrame(rows)

    result["p_holm"] = holm_adjust(
        result["p_value"]
    )

    result["significant_0_05"] = (
        result["p_holm"] < 0.05
    )

    return result


def load_judge_scores():
    judge_root = (
        ROOT
        / "data"
        / "private"
        / "judges"
    )

    result = {}

    for judge in JUDGES:
        rows = []

        for path in sorted(
            (
                judge_root
                / judge
                / "successes"
            ).glob("*.json")
        ):
            import json

            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            row = {
                "blinded_item_id":
                    payload[
                        "blinded_item_id"
                    ]
            }

            row.update(
                payload["scores"]
            )

            rows.append(row)

        frame = pd.DataFrame(rows)

        if len(frame) != 432:
            raise RuntimeError(
                f"{judge}: expected 432 ratings"
            )

        result[judge] = frame.set_index(
            "blinded_item_id"
        )

    return result


def canonical_rating(value):
    """Normalise CSV and JSON ratings to the same representation."""

    if pd.isna(value):
        return "N/A"

    if isinstance(value, str):
        cleaned = value.strip()

        if cleaned.upper() == "N/A":
            return "N/A"

        try:
            numeric_value = float(cleaned)
        except ValueError:
            return cleaned

        if numeric_value.is_integer():
            return str(int(numeric_value))

        return str(numeric_value)

    if isinstance(value, (int, np.integer)):
        return str(int(value))

    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return "N/A"

        if float(value).is_integer():
            return str(int(value))

    return str(value)


def majority_vote_agreement(human):
    human_index = human.set_index(
        "blinded_item_id"
    )

    judges = load_judge_scores()

    rows = []

    for axis in ALL_AXES:
        human_values = []
        majority_values = []

        majority_available = 0
        exact_matches = 0
        numeric_exact_matches = 0
        both_na = 0
        human_na_judge_numeric = 0
        human_numeric_judge_na = 0
        unanimous = 0

        for item_id in human_index.index:
            votes = [
                canonical_rating(
                    judges[judge].at[
                        item_id,
                        axis,
                    ]
                )
                for judge in JUDGES
            ]

            counts = Counter(votes)

            most_common = counts.most_common()

            if len(set(votes)) == 1:
                unanimous += 1

            if (
                not most_common
                or most_common[0][1] < 2
            ):
                continue

            majority = most_common[0][0]
            human_score = canonical_rating(
                human_index.at[
                    item_id,
                    axis,
                ]
            )

            majority_available += 1

            if majority == human_score:
                exact_matches += 1

            human_is_na = human_score.upper() == "N/A"
            majority_is_na = majority.upper() == "N/A"

            if human_is_na and majority_is_na:
                both_na += 1
            elif human_is_na and not majority_is_na:
                human_na_judge_numeric += 1
            elif not human_is_na and majority_is_na:
                human_numeric_judge_na += 1

            if not human_is_na and not majority_is_na:
                try:
                    human_numeric = int(float(human_score))
                    majority_numeric = int(float(majority))

                    human_values.append(human_numeric)
                    majority_values.append(majority_numeric)

                    if human_numeric == majority_numeric:
                        numeric_exact_matches += 1
                except ValueError:
                    pass

        if axis == "A3":
            kappa = ordinary_cohen_kappa(
                human_values,
                majority_values,
            )
            method = "unweighted"
        else:
            kappa = (
                linearly_weighted_cohen_kappa(
                    human_values,
                    majority_values,
                )
            )
            method = "linear_weighted"

        rows.append(
            {
                "axis": axis,
                "total_items": 432,
                "majority_available":
                    majority_available,
                "majority_available_rate":
                    majority_available / 432,
                "three_judges_unanimous":
                    unanimous,
                "unanimity_rate":
                    unanimous / 432,
                "human_exact_matches":
                    exact_matches,
                "human_exact_agreement":
                    (
                        exact_matches
                        / majority_available
                        if majority_available
                        else np.nan
                    ),
                "numeric_pairs_for_kappa":
                    len(human_values),
                "numeric_exact_matches":
                    numeric_exact_matches,
                "numeric_exact_agreement":
                    (
                        numeric_exact_matches / len(human_values)
                        if human_values
                        else np.nan
                    ),
                "both_na":
                    both_na,
                "human_na_judge_numeric":
                    human_na_judge_numeric,
                "human_numeric_judge_na":
                    human_numeric_judge_na,
                "human_vs_majority_kappa":
                    kappa,
                "kappa_method": method,
            }
        )

    return pd.DataFrame(rows)


def make_figures(
    conversations,
    theme,
    early_late,
    majority,
):
    # Exploratory axes by presentation
    rows = []

    for level in [
        "control",
        "ambiguous",
        "fixed_belief",
    ]:
        subset = conversations[
            conversations[
                "presentation_level"
            ].eq(level)
        ]

        for axis in EXPLORATORY_AXES:
            rows.append(
                {
                    "presentation": level,
                    "axis": axis,
                    "mean":
                        numeric(
                            subset[
                                f"mean_{axis}"
                            ]
                        ).mean(),
                }
            )

    frame = pd.DataFrame(rows)

    pivot = frame.pivot(
        index="axis",
        columns="presentation",
        values="mean",
    )

    ax = pivot.plot(
        kind="bar",
        figsize=(9, 5),
    )

    ax.set_ylabel(
        "Mean human-rated score"
    )
    ax.set_xlabel(
        "Exploratory rubric axis"
    )
    ax.set_title(
        "Exploratory outcomes by presentation level"
    )

    plt.xticks(rotation=0)
    plt.tight_layout()

    plt.savefig(
        FIGURES
        / "figure_exploratory_axes_by_presentation.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close()

    # Theme A1
    theme_a1 = theme[
        theme["outcome"].eq("mean_A1")
    ]

    labels = []
    values = []

    for level in [
        "ai_relationship",
        "monitoring",
        "personal_messages",
    ]:
        subset = conversations[
            conversations["theme"].eq(level)
        ]

        labels.append(
            level.replace("_", " ").title()
        )

        values.append(
            numeric(
                subset["mean_A1"]
            ).mean()
        )

    fig, ax = plt.subplots(
        figsize=(7, 4.5)
    )

    ax.bar(labels, values)

    ax.set_ylabel(
        "Mean A1 belief-confirmation score"
    )
    ax.set_title(
        "Belief confirmation by scenario theme"
    )
    ax.set_ylim(0, 2)

    plt.xticks(rotation=15)
    plt.tight_layout()

    plt.savefig(
        FIGURES
        / "figure_a1_by_theme.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # Early vs late
    fig, ax = plt.subplots(
        figsize=(8, 4.5)
    )

    ax.bar(
        early_late["axis"],
        early_late[
            "mean_late_minus_early"
        ],
    )

    ax.axhline(
        0,
        linewidth=0.8,
    )

    ax.set_ylabel(
        "Mean late-minus-early score"
    )

    ax.set_xlabel(
        "Rubric axis"
    )

    ax.set_title(
        "Within-conversation change from early to late turns"
    )

    plt.tight_layout()

    plt.savefig(
        FIGURES
        / "figure_early_late_change.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # Majority-vote agreement
    fig, ax = plt.subplots(
        figsize=(8, 4.5)
    )

    ax.bar(
        majority["axis"],
        majority[
            "human_vs_majority_kappa"
        ],
    )

    ax.axhline(
        0,
        linewidth=0.8,
    )

    ax.set_ylabel(
        "Cohen's kappa"
    )

    ax.set_xlabel(
        "Rubric axis"
    )

    ax.set_title(
        "Human agreement with three-judge majority vote"
    )

    plt.tight_layout()

    plt.savefig(
        FIGURES
        / "figure_human_vs_judge_majority.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)


def main():
    TABLES.mkdir(
        parents=True,
        exist_ok=True,
    )
    FIGURES.mkdir(
        parents=True,
        exist_ok=True,
    )

    human = pd.read_csv(
        PRIMARY
        / "human_turn_level.csv"
    )

    if len(human) != 432:
        raise RuntimeError(
            "Expected 432 human rows."
        )

    conversations = (
        build_conversation_table(
            human
        )
    )

    conversations.to_csv(
        TABLES
        / "conversation_all_axes.csv",
        index=False,
    )

    exploratory = (
        exploratory_main_effects(
            conversations
        )
    )

    exploratory.to_csv(
        TABLES
        / "exploratory_axes_main_effects.csv",
        index=False,
    )

    themes = theme_effects(
        conversations
    )

    themes.to_csv(
        TABLES
        / "theme_effects.csv",
        index=False,
    )

    model_interactions = (
        model_by_presentation_interactions(
            conversations
        )
    )

    model_interactions.to_csv(
        TABLES
        / "model_by_presentation_interactions.csv",
        index=False,
    )

    time_interactions = (
        presentation_by_time_interactions(
            conversations
        )
    )

    time_interactions.to_csv(
        TABLES
        / "presentation_by_time_interactions.csv",
        index=False,
    )

    early_late = overall_early_late(
        conversations
    )

    early_late.to_csv(
        TABLES
        / "overall_early_late_change.csv",
        index=False,
    )

    majority = majority_vote_agreement(
        human
    )

    majority.to_csv(
        TABLES
        / "human_vs_three_judge_majority.csv",
        index=False,
    )

    make_figures(
        conversations,
        themes,
        early_late,
        majority,
    )

    print()
    print("=" * 78)
    print("ANALYSIS V3 COMPLETE")
    print("=" * 78)

    print()
    print(
        "EXPLORATORY AXES — statistically supported after Holm correction"
    )

    supported = exploratory[
        exploratory[
            "significant_0_05"
        ]
    ]

    if supported.empty:
        print("None.")
    else:
        print(
            supported[
                [
                    "family",
                    "level_a",
                    "level_b",
                    "outcome",
                    "mean_difference",
                    "ci_lower",
                    "ci_upper",
                    "p_holm",
                    "rank_biserial",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print(
        "THEME EFFECTS — statistically supported after Holm correction"
    )

    supported_theme = themes[
        themes[
            "significant_0_05"
        ]
    ]

    if supported_theme.empty:
        print("None.")
    else:
        print(
            supported_theme[
                [
                    "level_a",
                    "level_b",
                    "outcome",
                    "mean_difference",
                    "ci_lower",
                    "ci_upper",
                    "p_holm",
                    "rank_biserial",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print(
        "MODEL × PRESENTATION interactions supported after correction"
    )

    supported_model = (
        model_interactions[
            model_interactions[
                "significant_0_05"
            ]
        ]
    )

    if supported_model.empty:
        print("None.")
    else:
        print(
            supported_model.to_string(
                index=False
            )
        )

    print()
    print(
        "PRESENTATION × TIME interactions supported after correction"
    )

    supported_time = (
        time_interactions[
            time_interactions[
                "significant_0_05"
            ]
        ]
    )

    if supported_time.empty:
        print("None.")
    else:
        print(
            supported_time.to_string(
                index=False
            )
        )

    print()
    print(
        "OVERALL EARLY → LATE CHANGE"
    )

    print(
        early_late[
            [
                "axis",
                "n_conversations",
                "mean_late_minus_early",
                "ci_lower",
                "ci_upper",
                "p_holm",
                "rank_biserial",
            ]
        ].to_string(
            index=False
        )
    )

    print()
    print(
        "HUMAN VS THREE-JUDGE MAJORITY"
    )

    print(
        majority[
            [
                "axis",
                "majority_available",
                "human_exact_agreement",
                "numeric_exact_agreement",
                "human_vs_majority_kappa",
                "unanimity_rate",
            ]
        ].to_string(
            index=False
        )
    )

    print()
    print("Figures:")

    for path in sorted(
        FIGURES.glob("*.png")
    ):
        print(path.name)

    print()
    print("Outputs:")
    print(OUTPUT)

    print()
    print(
        "V3 exploratory analyses remain secondary to A1/A2/A3 primary results."
    )

    print(
        "NO NETWORK CALLS WERE MADE."
    )


if __name__ == "__main__":
    main()
