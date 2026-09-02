from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import rankdata, wilcoxon

from src.trajectory_analysis import matched_pair_differences


INPUT_ROOT = ROOT / "data" / "private" / "analysis-v1"
PRIMARY = INPUT_ROOT / "primary"
TRAJECTORIES = INPUT_ROOT / "trajectories"
AGREEMENT = INPUT_ROOT / "agreement"

OUTPUT = ROOT / "data" / "private" / "analysis-v2"
TABLES = OUTPUT / "tables"
FIGURES = OUTPUT / "figures"

AXES = ("A1", "A2", "A3")
SEED = 20260902
N_BOOTSTRAP = 10000


def holm_adjust(pvalues):
    pvalues = np.asarray(pvalues, dtype=float)

    result = np.full(len(pvalues), np.nan)

    valid = np.where(np.isfinite(pvalues))[0]

    if len(valid) == 0:
        return result

    ordered = valid[
        np.argsort(pvalues[valid])
    ]

    previous = 0.0
    m = len(ordered)

    for rank, index in enumerate(ordered):
        adjusted = min(
            1.0,
            (m - rank) * pvalues[index],
        )

        adjusted = max(
            adjusted,
            previous,
        )

        result[index] = adjusted
        previous = adjusted

    return result


def rank_biserial(differences):
    values = np.asarray(
        differences,
        dtype=float,
    )

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

    positive = ranks[
        values > 0
    ].sum()

    negative = ranks[
        values < 0
    ].sum()

    denominator = positive + negative

    if denominator == 0:
        return 0.0

    return float(
        (positive - negative)
        / denominator
    )


def bootstrap_difference_ci(
    differences,
    *,
    seed,
    n_resamples=N_BOOTSTRAP,
):
    values = np.asarray(
        differences,
        dtype=float,
    )

    values = values[
        np.isfinite(values)
    ]

    if len(values) == 0:
        return (
            np.nan,
            np.nan,
        )

    rng = np.random.default_rng(seed)

    samples = rng.choice(
        values,
        size=(
            n_resamples,
            len(values),
        ),
        replace=True,
    )

    estimates = samples.mean(axis=1)

    lower, upper = np.quantile(
        estimates,
        [0.025, 0.975],
    )

    return (
        float(lower),
        float(upper),
    )


def matched_test(
    conversations,
    *,
    factor,
    level_a,
    level_b,
    outcome,
    match_columns,
    seed,
):
    pairs = matched_pair_differences(
        conversations,
        outcome=outcome,
        condition_column=factor,
        level_a=level_a,
        level_b=level_b,
        match_columns=match_columns,
    )

    matched = pairs.dropna(
        subset=[
            "value_a",
            "value_b",
            "difference",
        ]
    ).copy()

    differences = matched[
        "difference"
    ].to_numpy(dtype=float)

    n_pairs = len(differences)

    if n_pairs == 0:
        statistic = np.nan
        p_value = np.nan

    elif np.allclose(
        differences,
        0,
    ):
        statistic = 0.0
        p_value = 1.0

    else:
        test = wilcoxon(
            differences,
            zero_method="wilcox",
            alternative="two-sided",
            method="auto",
        )

        statistic = float(
            test.statistic
        )

        p_value = float(
            test.pvalue
        )

    ci_lower, ci_upper = (
        bootstrap_difference_ci(
            differences,
            seed=seed,
        )
    )

    return {
        "factor": factor,
        "level_a": level_a,
        "level_b": level_b,
        "outcome": outcome,
        "difference_direction":
            "level_b - level_a",
        "n_pairs": n_pairs,
        "mean_a":
            float(
                matched["value_a"].mean()
            )
            if n_pairs else np.nan,
        "mean_b":
            float(
                matched["value_b"].mean()
            )
            if n_pairs else np.nan,
        "mean_difference":
            float(
                np.mean(differences)
            )
            if n_pairs else np.nan,
        "median_difference":
            float(
                np.median(differences)
            )
            if n_pairs else np.nan,
        "bootstrap_95_ci_lower":
            ci_lower,
        "bootstrap_95_ci_upper":
            ci_upper,
        "wilcoxon_statistic":
            statistic,
        "p_value":
            p_value,
        "rank_biserial_effect":
            rank_biserial(
                differences
            ),
        "zero_differences":
            int(
                np.sum(
                    differences == 0
                )
            ),
    }


def test_family(
    conversations,
    comparisons,
    *,
    family_name,
):
    rows = []

    for index, comparison in enumerate(
        comparisons
    ):
        for axis_index, axis in enumerate(
            AXES
        ):
            rows.append(
                matched_test(
                    conversations,
                    factor=comparison[
                        "factor"
                    ],
                    level_a=comparison[
                        "level_a"
                    ],
                    level_b=comparison[
                        "level_b"
                    ],
                    outcome=f"mean_{axis}",
                    match_columns=comparison[
                        "match_columns"
                    ],
                    seed=(
                        SEED
                        + index * 100
                        + axis_index
                    ),
                )
            )

    frame = pd.DataFrame(rows)

    frame["p_holm"] = holm_adjust(
        frame["p_value"]
    )

    frame["significant_0_05"] = (
        frame["p_holm"] < 0.05
    )

    frame.insert(
        0,
        "family",
        family_name,
    )

    return frame


def bootstrap_group_mean(
    values,
    *,
    seed,
    n_resamples=5000,
):
    values = pd.to_numeric(
        pd.Series(values),
        errors="coerce",
    ).dropna().to_numpy()

    if len(values) == 0:
        return (
            np.nan,
            np.nan,
            np.nan,
        )

    estimate = float(
        values.mean()
    )

    rng = np.random.default_rng(seed)

    samples = rng.choice(
        values,
        size=(
            n_resamples,
            len(values),
        ),
        replace=True,
    )

    means = samples.mean(axis=1)

    lower, upper = np.quantile(
        means,
        [0.025, 0.975],
    )

    return (
        estimate,
        float(lower),
        float(upper),
    )


def trajectory_event_table(
    conversations,
):
    rows = []

    factors = (
        "model_slot",
        "presentation_level",
        "context_condition",
        "theme",
    )

    for factor in factors:
        for level, group in conversations.groupby(
            factor,
            dropna=False,
        ):
            any_risk = pd.to_numeric(
                group["any_A1_2"],
                errors="coerce",
            ).dropna()

            safety_turn = pd.to_numeric(
                group[
                    "first_A3_safety_turn"
                ],
                errors="coerce",
            )

            risk_turn = pd.to_numeric(
                group[
                    "first_A1_2_turn"
                ],
                errors="coerce",
            )

            recovery = pd.to_numeric(
                group[
                    "recovery_after_high_risk_turn"
                ],
                errors="coerce",
            ).dropna()

            persistence = pd.to_numeric(
                group[
                    "persistence_after_onset_rate"
                ],
                errors="coerce",
            ).dropna()

            rows.append(
                {
                    "factor": factor,
                    "level": level,
                    "n_conversations":
                        len(group),
                    "conversations_with_A1_2":
                        int(
                            any_risk.sum()
                        )
                        if len(any_risk)
                        else 0,
                    "proportion_with_A1_2":
                        float(
                            any_risk.mean()
                        )
                        if len(any_risk)
                        else np.nan,
                    "median_first_A1_2_turn":
                        float(
                            risk_turn.median()
                        )
                        if risk_turn.notna().any()
                        else np.nan,
                    "conversations_with_A3_intervention":
                        int(
                            safety_turn.notna().sum()
                        ),
                    "median_first_A3_intervention_turn":
                        float(
                            safety_turn.median()
                        )
                        if safety_turn.notna().any()
                        else np.nan,
                    "recovery_rate_after_A1_2":
                        float(
                            recovery.mean()
                        )
                        if len(recovery)
                        else np.nan,
                    "mean_persistence_after_A1_2":
                        float(
                            persistence.mean()
                        )
                        if len(persistence)
                        else np.nan,
                }
            )

    return pd.DataFrame(rows)


def make_figures(
    human,
    conversations,
    agreement,
):
    # --------------------------------------------------
    # Figure 1: presentation level and conversation A1
    # --------------------------------------------------
    presentation_order = [
        "control",
        "ambiguous",
        "fixed_belief",
    ]

    labels = []
    means = []
    lowers = []
    uppers = []

    for index, level in enumerate(
        presentation_order
    ):
        values = conversations.loc[
            conversations[
                "presentation_level"
            ].eq(level),
            "mean_A1",
        ]

        mean, low, high = (
            bootstrap_group_mean(
                values,
                seed=SEED + index,
            )
        )

        labels.append(level)
        means.append(mean)
        lowers.append(mean - low)
        uppers.append(high - mean)

    fig, ax = plt.subplots(
        figsize=(7, 4.5)
    )

    ax.errorbar(
        labels,
        means,
        yerr=[
            lowers,
            uppers,
        ],
        fmt="o",
        capsize=5,
    )

    ax.set_ylabel(
        "Mean A1 belief-confirmation score"
    )
    ax.set_xlabel(
        "Presentation level"
    )
    ax.set_title(
        "Belief confirmation by presentation level"
    )
    ax.set_ylim(
        0,
        2,
    )

    fig.tight_layout()

    fig.savefig(
        FIGURES
        / "figure_a1_by_presentation.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # --------------------------------------------------
    # Figure 2: model comparison
    # --------------------------------------------------
    model_order = [
        "model_minimax",
        "model_nemotron",
    ]

    labels = []
    means = []
    lowers = []
    uppers = []

    for index, model in enumerate(
        model_order
    ):
        values = conversations.loc[
            conversations[
                "model_slot"
            ].eq(model),
            "mean_A1",
        ]

        mean, low, high = (
            bootstrap_group_mean(
                values,
                seed=SEED + 20 + index,
            )
        )

        labels.append(
            model.replace(
                "model_",
                "",
            ).title()
        )

        means.append(mean)
        lowers.append(mean - low)
        uppers.append(high - mean)

    fig, ax = plt.subplots(
        figsize=(6, 4.5)
    )

    ax.errorbar(
        labels,
        means,
        yerr=[
            lowers,
            uppers,
        ],
        fmt="o",
        capsize=5,
    )

    ax.set_ylabel(
        "Mean A1 belief-confirmation score"
    )

    ax.set_xlabel(
        "Target model"
    )

    ax.set_title(
        "Belief confirmation by target model"
    )

    ax.set_ylim(
        0,
        2,
    )

    fig.tight_layout()

    fig.savefig(
        FIGURES
        / "figure_a1_by_model.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # --------------------------------------------------
    # Figure 3: A1 across turns by model
    # --------------------------------------------------
    turn_summary = (
        human.groupby(
            [
                "model_slot",
                "turn_number",
            ],
            as_index=False,
        )["A1"]
        .mean()
    )

    fig, ax = plt.subplots(
        figsize=(7, 4.5)
    )

    for model, group in turn_summary.groupby(
        "model_slot"
    ):
        ax.plot(
            group["turn_number"],
            group["A1"],
            marker="o",
            label=model.replace(
                "model_",
                "",
            ).title(),
        )

    ax.set_xlabel(
        "Conversation turn"
    )

    ax.set_ylabel(
        "Mean A1 belief-confirmation score"
    )

    ax.set_title(
        "Belief-confirmation trajectory across six turns"
    )

    ax.set_xticks(
        range(1, 7)
    )

    ax.set_ylim(
        0,
        2,
    )

    ax.legend()

    fig.tight_layout()

    fig.savefig(
        FIGURES
        / "figure_a1_trajectory_by_model.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # --------------------------------------------------
    # Figure 4: A1 across turns by presentation
    # --------------------------------------------------
    presentation_turn = (
        human.groupby(
            [
                "presentation_level",
                "turn_number",
            ],
            as_index=False,
        )["A1"]
        .mean()
    )

    fig, ax = plt.subplots(
        figsize=(7, 4.5)
    )

    for level, group in presentation_turn.groupby(
        "presentation_level"
    ):
        ax.plot(
            group["turn_number"],
            group["A1"],
            marker="o",
            label=level.replace(
                "_",
                " ",
            ).title(),
        )

    ax.set_xlabel(
        "Conversation turn"
    )

    ax.set_ylabel(
        "Mean A1 belief-confirmation score"
    )

    ax.set_title(
        "Belief-confirmation trajectory by presentation level"
    )

    ax.set_xticks(
        range(1, 7)
    )

    ax.set_ylim(
        0,
        2,
    )

    ax.legend()

    fig.tight_layout()

    fig.savefig(
        FIGURES
        / "figure_a1_trajectory_by_presentation.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # --------------------------------------------------
    # Figure 5: human-judge kappa
    # --------------------------------------------------
    human_agreement = agreement[
        agreement["source_a"].eq(
            "human"
        )
        | agreement["source_b"].eq(
            "human"
        )
    ].copy()

    human_agreement[
        "judge"
    ] = np.where(
        human_agreement[
            "source_a"
        ].eq("human"),
        human_agreement[
            "source_b"
        ],
        human_agreement[
            "source_a"
        ],
    )

    pivot = human_agreement.pivot(
        index="axis",
        columns="judge",
        values="cohen_kappa",
    )

    ax = pivot.plot(
        kind="bar",
        figsize=(9, 5),
    )

    ax.set_ylabel(
        "Cohen's kappa"
    )

    ax.set_xlabel(
        "Rubric axis"
    )

    ax.set_title(
        "Agreement between human annotation and LLM judges"
    )

    ax.axhline(
        0,
        linewidth=0.8,
    )

    plt.xticks(
        rotation=0,
    )

    plt.tight_layout()

    plt.savefig(
        FIGURES
        / "figure_human_judge_kappa.png",
        dpi=300,
        bbox_inches="tight",
    )

    plt.close()


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

    conversations = pd.read_csv(
        TRAJECTORIES
        / "human_conversation_trajectory_summary.csv"
    )

    agreement = pd.read_csv(
        AGREEMENT
        / "pairwise_agreement.csv"
    )

    assert len(human) == 432
    assert len(conversations) == 72

    # ================================================
    # RQ1 — PRESENTATION LEVEL
    # ================================================
    presentation_comparisons = [
        {
            "factor":
                "presentation_level",
            "level_a":
                "control",
            "level_b":
                "ambiguous",
            "match_columns": [
                "theme",
                "model_slot",
                "context_condition",
                "repetition",
            ],
        },
        {
            "factor":
                "presentation_level",
            "level_a":
                "control",
            "level_b":
                "fixed_belief",
            "match_columns": [
                "theme",
                "model_slot",
                "context_condition",
                "repetition",
            ],
        },
        {
            "factor":
                "presentation_level",
            "level_a":
                "ambiguous",
            "level_b":
                "fixed_belief",
            "match_columns": [
                "theme",
                "model_slot",
                "context_condition",
                "repetition",
            ],
        },
    ]

    rq1 = test_family(
        conversations,
        presentation_comparisons,
        family_name=
            "RQ1_presentation_level",
    )

    rq1.to_csv(
        TABLES
        / "rq1_presentation_level_tests.csv",
        index=False,
    )

    # ================================================
    # RQ2 — TARGET MODEL
    # ================================================
    model_comparisons = [
        {
            "factor":
                "model_slot",
            "level_a":
                "model_minimax",
            "level_b":
                "model_nemotron",
            "match_columns": [
                "script_id",
                "context_condition",
                "repetition",
            ],
        }
    ]

    rq2 = test_family(
        conversations,
        model_comparisons,
        family_name=
            "RQ2_target_model",
    )

    rq2.to_csv(
        TABLES
        / "rq2_model_tests.csv",
        index=False,
    )

    # ================================================
    # RQ3 — PRELOADED CONTEXT
    # ================================================
    context_comparisons = [
        {
            "factor":
                "context_condition",
            "level_a":
                "no_preloaded_context",
            "level_b":
                "standardised_preloaded_context",
            "match_columns": [
                "script_id",
                "model_slot",
                "repetition",
            ],
        }
    ]

    rq3 = test_family(
        conversations,
        context_comparisons,
        family_name=
            "RQ3_context",
    )

    rq3.to_csv(
        TABLES
        / "rq3_context_tests.csv",
        index=False,
    )

    # ================================================
    # RQ4 — MULTI-TURN ONSET / PERSISTENCE / RECOVERY
    # ================================================
    events = trajectory_event_table(
        conversations
    )

    events.to_csv(
        TABLES
        / "rq4_trajectory_events.csv",
        index=False,
    )

    turn_summary = (
        human.groupby(
            [
                "turn_number",
                "model_slot",
                "presentation_level",
            ],
            as_index=False,
        )
        .agg(
            n=("A1", "size"),
            mean_A1=("A1", "mean"),
            proportion_A1_2=(
                "A1",
                lambda values:
                    float(
                        (
                            values == 2
                        ).mean()
                    ),
            ),
        )
    )

    turn_summary.to_csv(
        TABLES
        / "rq4_turn_level_a1_descriptives.csv",
        index=False,
    )

    # ================================================
    # FIGURES
    # ================================================
    make_figures(
        human,
        conversations,
        agreement,
    )

    # ================================================
    # FINAL COMBINED TEST TABLE
    # ================================================
    combined = pd.concat(
        [
            rq1,
            rq2,
            rq3,
        ],
        ignore_index=True,
    )

    combined.to_csv(
        TABLES
        / "all_primary_matched_tests.csv",
        index=False,
    )

    print()
    print("=" * 76)
    print("ANALYSIS V2 COMPLETE")
    print("=" * 76)

    print()
    print("RQ1 — Presentation level")
    print(
        rq1[
            [
                "level_a",
                "level_b",
                "outcome",
                "n_pairs",
                "mean_difference",
                "bootstrap_95_ci_lower",
                "bootstrap_95_ci_upper",
                "p_value",
                "p_holm",
                "rank_biserial_effect",
            ]
        ].to_string(index=False)
    )

    print()
    print("RQ2 — MiniMax vs Nemotron")
    print(
        rq2[
            [
                "outcome",
                "n_pairs",
                "mean_a",
                "mean_b",
                "mean_difference",
                "bootstrap_95_ci_lower",
                "bootstrap_95_ci_upper",
                "p_value",
                "p_holm",
                "rank_biserial_effect",
            ]
        ].to_string(index=False)
    )

    print()
    print("RQ3 — No context vs standardised context")
    print(
        rq3[
            [
                "outcome",
                "n_pairs",
                "mean_a",
                "mean_b",
                "mean_difference",
                "bootstrap_95_ci_lower",
                "bootstrap_95_ci_upper",
                "p_value",
                "p_holm",
                "rank_biserial_effect",
            ]
        ].to_string(index=False)
    )

    print()
    print("RQ4 — trajectory events")
    print(
        events.to_string(
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
        "All inferential tests use conversation-level "
        "matched outcomes, not independent turns."
    )

    print(
        "NO NETWORK CALLS WERE MADE."
    )


if __name__ == "__main__":
    main()
