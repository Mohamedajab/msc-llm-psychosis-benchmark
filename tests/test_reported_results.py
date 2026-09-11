"""Regression checks for the completed study's frozen reported results."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_final_release import (
    EXPECTED_JUDGE_AGREEMENT,
    EXPECTED_RQ1,
    EXPECTED_RQ4_INTERACTION,
    JUDGE_AGREEMENT_PATH,
    REQUIRED_ANALYSIS_OUTPUTS,
    RQ1_PATH,
    RQ2_PATH,
    RQ3_PATH,
    RQ4_INTERACTION_PATH,
    load_csv_rows,
    verify_human_annotations,
    verify_judges,
    verify_study_completion,
)

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(
    not all(path.is_file() for path in REQUIRED_ANALYSIS_OUTPUTS),
    reason="Private frozen analysis outputs are not present in this checkout",
)


def _row(rows: list[dict[str, str]], **fields: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(name) == value for name, value in fields.items())]
    assert len(matches) == 1
    return matches[0]


def test_rq1_supported_comparisons_match_frozen_values() -> None:
    rows = load_csv_rows(RQ1_PATH)
    supported = {
        (row["level_a"], row["level_b"], row["outcome"])
        for row in rows
        if row["significant_0_05"] == "True"
    }
    assert supported == set(EXPECTED_RQ1)
    for key, expected in EXPECTED_RQ1.items():
        row = _row(rows, level_a=key[0], level_b=key[1], outcome=key[2])
        for field, value in expected.items():
            assert float(row[field]) == pytest.approx(value)


@pytest.mark.parametrize(("label", "path"), [("RQ2", RQ2_PATH), ("RQ3", RQ3_PATH)])
def test_no_rq2_or_rq3_primary_comparison_survives_holm_correction(label: str, path: Path) -> None:
    rows = [
        row for row in load_csv_rows(path) if row["outcome"] in {"mean_A1", "mean_A2", "mean_A3"}
    ]
    assert len(rows) == 3, label
    assert all(float(row["p_holm"]) >= 0.05 for row in rows)
    assert all(row["significant_0_05"] == "False" for row in rows)


def test_rq4_presentation_by_time_interaction_matches_frozen_output() -> None:
    row = _row(
        load_csv_rows(RQ4_INTERACTION_PATH),
        level_a="ambiguous",
        level_b="fixed_belief",
        outcome="late_minus_early_A1",
    )
    assert row["significant_0_05"] == "True"
    for field, value in EXPECTED_RQ4_INTERACTION.items():
        assert float(row[field]) == pytest.approx(value)


def test_human_vs_three_judge_majority_matches_frozen_output() -> None:
    rows = load_csv_rows(JUDGE_AGREEMENT_PATH)
    assert {row["axis"] for row in rows} == set(EXPECTED_JUDGE_AGREEMENT)
    for axis, (exact_agreement, kappa) in EXPECTED_JUDGE_AGREEMENT.items():
        row = _row(rows, axis=axis)
        assert float(row["numeric_exact_agreement"]) == pytest.approx(exact_agreement)
        assert float(row["human_vs_majority_kappa"]) == pytest.approx(kappa)


def test_completed_study_annotation_and_judge_counts_are_consistent() -> None:
    study = verify_study_completion()
    human, human_items = verify_human_annotations()
    judges = verify_judges(human_items)

    assert study["conversations"] == 72
    assert study["responses"] == 432
    assert study["model_responses"] == {
        "minimax/minimax-m3:free": 216,
        "nvidia/nemotron-3-super-120b-a12b:free": 216,
    }
    assert study["technical_errors"] == 145
    assert study["automatic_recoveries"] == 127
    assert study["truncations"] == 0
    assert human == {
        "annotations": 432,
        "annotator_id": "annotator_1",
        "annotation_method": "human",
    }
    assert judges["judges"] == {
        "deepseek-v4-pro": 432,
        "deepseek-v4-flash": 432,
        "glm-5.3-flash": 432,
    }
    assert judges["total"] == 1296
