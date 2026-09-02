from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import os
from collections import Counter
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.annotation import (
    AnnotationStore,
    build_blinded_items,
    linearly_weighted_cohen_kappa,
    ordinary_cohen_kappa,
)
from src.config_loader import (
    configuration_bundle_hash,
    load_histories,
    load_models,
    load_scripts,
)
from src.storage import RawRunStore
from src.trajectory_analysis import summarize_conversations


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

RAW_ROOT = ROOT / "data" / "raw" / "study-v2"
ANNOTATION_PATH = ROOT / "data" / "annotations" / "annotations.jsonl"
JUDGE_ROOT = ROOT / "data" / "private" / "judges"

# Keep analysis outputs private until they have been checked.
OUTPUT_ROOT = ROOT / "data" / "private" / "analysis-v1"

PRIMARY_DIR = OUTPUT_ROOT / "primary"
TRAJECTORY_DIR = OUTPUT_ROOT / "trajectories"
AGREEMENT_DIR = OUTPUT_ROOT / "agreement"
QA_DIR = OUTPUT_ROOT / "qa"

AXES = ("A1", "A2", "A3", "B1", "B2", "B3", "C1")

JUDGES = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.3-flash",
)

EXPECTED_ITEMS = 432
EXPECTED_CONVERSATIONS = 72


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def normalise_rating(value: Any) -> int | str | None:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if value.upper() == "N/A":
            return "N/A"

        try:
            value = int(value)
        except ValueError:
            return None

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, float) and value.is_integer():
        return int(value)

    return None


def numeric_values(series: pd.Series) -> pd.Series:
    values = series.map(
        lambda value: np.nan
        if isinstance(value, str) and value.strip().upper() == "N/A"
        else value
    )
    return pd.to_numeric(values, errors="coerce")


def load_study_records():
    store = RawRunStore(RAW_ROOT)

    records = [
        store.load(run_id)
        for run_id in store.list_run_ids()
    ]

    records.sort(key=lambda record: record.header.run_id)

    if len(records) != EXPECTED_CONVERSATIONS:
        raise RuntimeError(
            f"Expected {EXPECTED_CONVERSATIONS} conversations; "
            f"found {len(records)}."
        )

    return records


def reconstruct_blinding(records):
    scripts = list(load_scripts(ROOT / "config" / "scenarios"))
    histories = list(load_histories(ROOT / "config" / "histories"))
    models = load_models(ROOT / "config" / "models.yaml")

    bundle_hash = configuration_bundle_hash(
        scripts,
        histories,
        models,
    )

    blinding_key = (
        os.getenv("ANNOTATION_BLINDING_KEY")
        or ("local-prototype-" + bundle_hash)
    )

    items, mapping = build_blinded_items(
        records,
        blinding_key=blinding_key,
    )

    if len(items) != EXPECTED_ITEMS:
        raise RuntimeError(
            f"Expected {EXPECTED_ITEMS} blinded items; "
            f"reconstructed {len(items)}."
        )

    return items, mapping


def metadata_lookup(records):
    lookup = {}

    for record in records:
        header = record.header

        lookup[header.run_id] = {
            "run_id": header.run_id,
            "script_id": header.script_id,
            "theme": enum_value(header.theme),
            "presentation_level": enum_value(
                header.presentation_level
            ),
            "model_slot": header.model_slot,
            "requested_model_id": header.requested_model_id,
            "context_condition": enum_value(
                header.context_condition
            ),
            "repetition": header.repetition,
            "data_status": header.data_status,
        }

    return lookup


def load_human(mapping, run_metadata):
    store = AnnotationStore(ANNOTATION_PATH)

    events = [
        event
        for event in store.latest_events(
            annotator_id="annotator_1"
        )
        if event.rating_round == "initial"
    ]

    if len(events) != EXPECTED_ITEMS:
        raise RuntimeError(
            f"Expected {EXPECTED_ITEMS} human ratings; "
            f"found {len(events)}."
        )

    if any(
        event.annotation_method != "human"
        for event in events
    ):
        raise RuntimeError(
            "Human annotation provenance is not entirely human."
        )

    map_by_item = {
        entry.blinded_item_id: entry
        for entry in mapping
        if entry.rating_round == "initial"
    }

    rows = []

    for event in events:
        entry = map_by_item.get(event.blinded_item_id)

        if entry is None:
            raise RuntimeError(
                "Human annotation could not be rejoined to "
                f"blinding map: {event.blinded_item_id}"
            )

        meta = run_metadata[entry.run_id]

        row = {
            **meta,
            "blinded_item_id": event.blinded_item_id,
            "turn_number": entry.turn_number,
            "source_response_hash":
                event.source_response_hash,
            "annotation_method":
                event.annotation_method,
        }

        row.update(
            {
                axis: normalise_rating(value)
                for axis, value
                in event.scores.model_dump().items()
            }
        )

        rows.append(row)

    frame = pd.DataFrame(rows)

    frame = frame.sort_values(
        ["run_id", "turn_number"]
    ).reset_index(drop=True)

    return frame


def load_judge(judge_id: str) -> pd.DataFrame:
    directory = JUDGE_ROOT / judge_id / "successes"

    files = sorted(directory.glob("*.json"))

    if len(files) != EXPECTED_ITEMS:
        raise RuntimeError(
            f"{judge_id}: expected {EXPECTED_ITEMS} successes, "
            f"found {len(files)}."
        )

    rows = []

    for path in files:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )

        row = {
            "blinded_item_id":
                payload["blinded_item_id"],
            "source_response_hash":
                payload["source_response_hash"],
            "judge_id":
                payload["judge_id"],
        }

        for axis in AXES:
            row[axis] = normalise_rating(
                payload["scores"][axis]
            )

        rows.append(row)

    frame = pd.DataFrame(rows)

    if frame["blinded_item_id"].duplicated().any():
        raise RuntimeError(
            f"{judge_id}: duplicate success item IDs detected."
        )

    return frame.sort_values(
        "blinded_item_id"
    ).reset_index(drop=True)


def validate_joins(
    human: pd.DataFrame,
    judges: dict[str, pd.DataFrame],
):
    human_ids = set(human["blinded_item_id"])

    report = {
        "human_items": len(human),
        "human_unique_ids":
            human["blinded_item_id"].nunique(),
        "human_methods":
            dict(Counter(human["annotation_method"])),
        "judges": {},
    }

    for judge_id, frame in judges.items():
        judge_ids = set(frame["blinded_item_id"])

        missing_from_judge = sorted(
            human_ids - judge_ids
        )

        extra_in_judge = sorted(
            judge_ids - human_ids
        )

        merged = human[
            [
                "blinded_item_id",
                "source_response_hash",
            ]
        ].merge(
            frame[
                [
                    "blinded_item_id",
                    "source_response_hash",
                ]
            ],
            on="blinded_item_id",
            how="inner",
            suffixes=("_human", "_judge"),
        )

        hash_mismatches = int(
            (
                merged["source_response_hash_human"]
                != merged["source_response_hash_judge"]
            ).sum()
        )

        report["judges"][judge_id] = {
            "items": len(frame),
            "unique_ids":
                frame["blinded_item_id"].nunique(),
            "missing_from_judge":
                len(missing_from_judge),
            "extra_in_judge":
                len(extra_in_judge),
            "source_hash_mismatches":
                hash_mismatches,
        }

        if (
            missing_from_judge
            or extra_in_judge
            or hash_mismatches
        ):
            raise RuntimeError(
                f"{judge_id}: human/judge join validation failed."
            )

    return report


def score_summary(
    frame: pd.DataFrame,
    *,
    factor: str | None = None,
) -> pd.DataFrame:
    if factor is None:
        groups = [("all", frame)]
        factor_name = "overall"
    else:
        groups = list(
            frame.groupby(
                factor,
                dropna=False,
                sort=True,
            )
        )
        factor_name = factor

    rows = []

    for level, group in groups:
        for axis in AXES:
            raw = group[axis].map(normalise_rating)
            numeric = numeric_values(raw)

            n_total = len(raw)
            n_na = int((raw == "N/A").sum())
            n_numeric = int(numeric.notna().sum())

            counts = {
                score: int((numeric == score).sum())
                for score in (0, 1, 2)
            }

            row = {
                "factor": factor_name,
                "level": str(level),
                "axis": axis,
                "n_total": n_total,
                "n_numeric": n_numeric,
                "n_na": n_na,
                "mean":
                    float(numeric.mean())
                    if n_numeric else np.nan,
                "median":
                    float(numeric.median())
                    if n_numeric else np.nan,
                "std":
                    float(numeric.std(ddof=1))
                    if n_numeric > 1 else np.nan,
                "count_0": counts[0],
                "count_1": counts[1],
                "count_2": counts[2],
                "prop_0":
                    counts[0] / n_numeric
                    if n_numeric else np.nan,
                "prop_1":
                    counts[1] / n_numeric
                    if n_numeric else np.nan,
                "prop_2":
                    counts[2] / n_numeric
                    if n_numeric else np.nan,
            }

            rows.append(row)

    return pd.DataFrame(rows)


def grouped_score_summary(
    frame: pd.DataFrame,
    factors: list[str],
) -> pd.DataFrame:
    rows = []

    for levels, group in frame.groupby(
        factors,
        dropna=False,
        sort=True,
    ):
        if not isinstance(levels, tuple):
            levels = (levels,)

        metadata = dict(zip(factors, levels, strict=True))

        for axis in AXES:
            raw = group[axis].map(normalise_rating)
            numeric = numeric_values(raw)

            n_numeric = int(numeric.notna().sum())

            rows.append(
                {
                    **metadata,
                    "axis": axis,
                    "n_total": len(group),
                    "n_numeric": n_numeric,
                    "n_na":
                        int((raw == "N/A").sum()),
                    "mean":
                        float(numeric.mean())
                        if n_numeric else np.nan,
                    "median":
                        float(numeric.median())
                        if n_numeric else np.nan,
                    "count_0":
                        int((numeric == 0).sum()),
                    "count_1":
                        int((numeric == 1).sum()),
                    "count_2":
                        int((numeric == 2).sum()),
                    "prop_score_2":
                        float((numeric == 2).mean())
                        if n_numeric else np.nan,
                }
            )

    return pd.DataFrame(rows)


def numeric_pairs(
    left: pd.Series,
    right: pd.Series,
):
    first = []
    second = []

    for a, b in zip(left, right, strict=True):
        a = normalise_rating(a)
        b = normalise_rating(b)

        if a is None or b is None:
            continue

        if a == "N/A" or b == "N/A":
            continue

        first.append(int(a))
        second.append(int(b))

    return first, second


def agreement_table(
    sources: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []

    aligned = {}

    for source, frame in sources.items():
        aligned[source] = frame.set_index(
            "blinded_item_id"
        ).sort_index()

    for source_a, source_b in combinations(
        sources,
        2,
    ):
        a = aligned[source_a]
        b = aligned[source_b]

        common = a.index.intersection(b.index)

        for axis in AXES:
            raw_a = [
                normalise_rating(v)
                for v in a.loc[common, axis]
            ]

            raw_b = [
                normalise_rating(v)
                for v in b.loc[common, axis]
            ]

            all_complete = [
                (x, y)
                for x, y in zip(
                    raw_a,
                    raw_b,
                    strict=True,
                )
                if x is not None and y is not None
            ]

            all_exact = (
                sum(x == y for x, y in all_complete)
                / len(all_complete)
                if all_complete else np.nan
            )

            first, second = numeric_pairs(
                pd.Series(raw_a),
                pd.Series(raw_b),
            )

            numeric_exact = (
                sum(
                    x == y
                    for x, y in zip(
                        first,
                        second,
                        strict=True,
                    )
                )
                / len(first)
                if first else np.nan
            )

            if axis == "A3":
                kappa = ordinary_cohen_kappa(
                    first,
                    second,
                )
                method = "unweighted"
            else:
                kappa = linearly_weighted_cohen_kappa(
                    first,
                    second,
                )
                method = "linear_weighted"

            rows.append(
                {
                    "source_a": source_a,
                    "source_b": source_b,
                    "axis": axis,
                    "n_items_common": len(common),
                    "n_all_ratings": len(all_complete),
                    "exact_agreement_including_NA":
                        all_exact,
                    "n_numeric_pairs": len(first),
                    "exact_agreement_numeric":
                        numeric_exact,
                    "cohen_kappa": kappa,
                    "kappa_method": method,
                }
            )

    return pd.DataFrame(rows)


def confusion_table(
    sources: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []

    aligned = {
        source: frame.set_index(
            "blinded_item_id"
        ).sort_index()
        for source, frame in sources.items()
    }

    for source_a, source_b in combinations(
        sources,
        2,
    ):
        a = aligned[source_a]
        b = aligned[source_b]

        common = a.index.intersection(b.index)

        for axis in AXES:
            counts = Counter()

            for item_id in common:
                score_a = normalise_rating(
                    a.at[item_id, axis]
                )
                score_b = normalise_rating(
                    b.at[item_id, axis]
                )

                counts[
                    (str(score_a), str(score_b))
                ] += 1

            for (
                score_a,
                score_b,
            ), count in sorted(counts.items()):
                rows.append(
                    {
                        "source_a": source_a,
                        "source_b": source_b,
                        "axis": axis,
                        "score_a": score_a,
                        "score_b": score_b,
                        "count": count,
                    }
                )

    return pd.DataFrame(rows)


def judge_consensus(
    human: pd.DataFrame,
    judges: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    base = human[
        ["blinded_item_id", *AXES]
    ].set_index("blinded_item_id").sort_index()

    judge_frames = {
        judge_id:
            frame[
                ["blinded_item_id", *AXES]
            ].set_index(
                "blinded_item_id"
            ).sort_index()
        for judge_id, frame in judges.items()
    }

    rows = []

    for axis in AXES:
        unanimous = 0
        human_matches = 0

        for item_id in base.index:
            ratings = [
                normalise_rating(
                    frame.at[item_id, axis]
                )
                for frame in judge_frames.values()
            ]

            if (
                all(rating is not None for rating in ratings)
                and len(set(ratings)) == 1
            ):
                unanimous += 1

                human_rating = normalise_rating(
                    base.at[item_id, axis]
                )

                if human_rating == ratings[0]:
                    human_matches += 1

        rows.append(
            {
                "axis": axis,
                "items": len(base),
                "three_judges_unanimous":
                    unanimous,
                "judge_unanimity_rate":
                    unanimous / len(base),
                "human_matches_unanimous_judges":
                    human_matches,
                "human_match_rate_when_judges_unanimous":
                    (
                        human_matches / unanimous
                        if unanimous
                        else np.nan
                    ),
            }
        )

    return pd.DataFrame(rows)


def main():
    for directory in (
        PRIMARY_DIR,
        TRAJECTORY_DIR,
        AGREEMENT_DIR,
        QA_DIR,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("Loading 72 frozen conversations...")
    records = load_study_records()

    print("Reconstructing blinded item mapping...")
    items, mapping = reconstruct_blinding(records)

    run_metadata = metadata_lookup(records)

    print("Loading primary human ratings...")
    human = load_human(
        mapping,
        run_metadata,
    )

    print("Loading three supplementary judges...")
    judges = {
        judge_id: load_judge(judge_id)
        for judge_id in JUDGES
    }

    print("Validating all human/judge joins...")
    qa_report = validate_joins(
        human,
        judges,
    )

    QA_DIR.joinpath(
        "data_join_report.json"
    ).write_text(
        json.dumps(
            qa_report,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # -----------------------------------------------------
    # PRIMARY HUMAN ANALYSIS
    # -----------------------------------------------------
    human.to_csv(
        PRIMARY_DIR / "human_turn_level.csv",
        index=False,
    )

    score_summary(human).to_csv(
        PRIMARY_DIR
        / "human_overall_axis_summary.csv",
        index=False,
    )

    factors = {
        "model":
            "model_slot",
        "presentation":
            "presentation_level",
        "context":
            "context_condition",
        "theme":
            "theme",
        "turn":
            "turn_number",
    }

    for filename, factor in factors.items():
        score_summary(
            human,
            factor=factor,
        ).to_csv(
            PRIMARY_DIR
            / f"human_by_{filename}.csv",
            index=False,
        )

    grouped_score_summary(
        human,
        [
            "model_slot",
            "presentation_level",
        ],
    ).to_csv(
        PRIMARY_DIR
        / "human_by_model_and_presentation.csv",
        index=False,
    )

    grouped_score_summary(
        human,
        [
            "model_slot",
            "turn_number",
        ],
    ).to_csv(
        PRIMARY_DIR
        / "human_by_model_and_turn.csv",
        index=False,
    )

    grouped_score_summary(
        human,
        [
            "presentation_level",
            "turn_number",
        ],
    ).to_csv(
        PRIMARY_DIR
        / "human_by_presentation_and_turn.csv",
        index=False,
    )

    # -----------------------------------------------------
    # CONVERSATION-LEVEL TRAJECTORIES
    # -----------------------------------------------------
    trajectory = summarize_conversations(
        human,
        expected_turns=6,
    )

    if len(trajectory) != EXPECTED_CONVERSATIONS:
        raise RuntimeError(
            "Trajectory summary did not produce exactly "
            "72 conversation rows."
        )

    trajectory.to_csv(
        TRAJECTORY_DIR
        / "human_conversation_trajectory_summary.csv",
        index=False,
    )

    # -----------------------------------------------------
    # SUPPLEMENTARY JUDGE AGREEMENT
    # -----------------------------------------------------
    sources = {
        "human": human[
            ["blinded_item_id", *AXES]
        ].copy(),
        **{
            judge_id:
                frame[
                    ["blinded_item_id", *AXES]
                ].copy()
            for judge_id, frame
            in judges.items()
        },
    }

    agreement = agreement_table(sources)

    agreement.to_csv(
        AGREEMENT_DIR
        / "pairwise_agreement.csv",
        index=False,
    )

    confusion_table(sources).to_csv(
        AGREEMENT_DIR
        / "pairwise_confusion_counts.csv",
        index=False,
    )

    judge_consensus(
        human,
        judges,
    ).to_csv(
        AGREEMENT_DIR
        / "three_judge_consensus_vs_human.csv",
        index=False,
    )

    # -----------------------------------------------------
    # SMALL CONSOLE SUMMARY
    # -----------------------------------------------------
    print()
    print("=" * 72)
    print("ANALYSIS V1 COMPLETE")
    print("=" * 72)

    print("Conversations:", len(records))
    print("Human ratings:", len(human))

    for judge_id, frame in judges.items():
        print(
            f"{judge_id}:",
            len(frame),
        )

    print()
    print("Human experimental balance:")
    print(
        human.groupby(
            [
                "model_slot",
                "presentation_level",
                "context_condition",
            ]
        ).size()
    )

    print()
    print("Human A1 overall:")
    print(
        human["A1"]
        .value_counts(
            dropna=False
        )
        .sort_index()
    )

    print()
    print("Human A1 by model:")
    for model, group in human.groupby(
        "model_slot"
    ):
        numeric = numeric_values(group["A1"])

        print(
            model,
            {
                "n": int(numeric.notna().sum()),
                "mean":
                    round(
                        float(numeric.mean()),
                        3,
                    ),
                "A1=2":
                    int((numeric == 2).sum()),
                "A1=2 proportion":
                    round(
                        float((numeric == 2).mean()),
                        3,
                    ),
            },
        )

    print()
    print("Human A1 by presentation level:")
    for level, group in human.groupby(
        "presentation_level"
    ):
        numeric = numeric_values(group["A1"])

        print(
            level,
            {
                "n": int(numeric.notna().sum()),
                "mean":
                    round(
                        float(numeric.mean()),
                        3,
                    ),
                "A1=2":
                    int((numeric == 2).sum()),
                "A1=2 proportion":
                    round(
                        float((numeric == 2).mean()),
                        3,
                    ),
            },
        )

    print()
    print("Human vs judge agreement:")
    print(
        agreement[
            agreement["source_a"].eq("human")
            | agreement["source_b"].eq("human")
        ][
            [
                "source_a",
                "source_b",
                "axis",
                "n_numeric_pairs",
                "exact_agreement_numeric",
                "cohen_kappa",
            ]
        ].to_string(index=False)
    )

    print()
    print("Files written under:")
    print(OUTPUT_ROOT)

    print()
    print("NO NETWORK CALLS WERE MADE.")


if __name__ == "__main__":
    main()
