"""Generate Study V2 tables/figures from real saved human annotations only."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_study import DEFAULT_OUTPUT_ROOT, load_frozen_study
from src.annotation import AnnotationStore, load_blinding_map, response_hash, tidy_annotation_frame
from src.storage import RawRunStore
from src.trajectory_analysis import (
    bootstrap_ci,
    matched_descriptive_comparisons,
    summarize_conversations,
)

DEFAULT_ANNOTATIONS = ROOT / "data" / "annotations" / "study-v2-annotations.jsonl"
DEFAULT_MAP = ROOT / "data" / "private" / "study-v2-blinding-map.json"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "study-v2-analysis"


def _real_turn_lookup(rows: list, store: RawRunStore) -> dict[tuple[str, int], object]:
    lookup = {}
    for row in rows:
        if not (store.run_directory(row.run_id) / "run.json").is_file():
            continue
        record = store.load(row.run_id)
        if record.header.data_status != "main_study":
            raise ValueError("Analysis refuses fixture, pilot or screen records")
        for event in record.turns:
            lookup[(row.run_id, event.turn_number)] = event
    return lookup


def build_analysis(*, annotations_path: Path, map_path: Path, output_directory: Path) -> dict:
    _, _, _, rows = load_frozen_study()
    if not annotations_path.is_file() or not map_path.is_file():
        return {
            "availability": "unavailable",
            "reason": "Real human annotations and/or the private blinding map do not exist",
        }
    store = RawRunStore(DEFAULT_OUTPUT_ROOT)
    turn_lookup = _real_turn_lookup(rows, store)
    if not turn_lookup:
        return {"availability": "unavailable", "reason": "No real Study V2 responses exist"}
    events = AnnotationStore(annotations_path).read_events()
    if not events:
        return {"availability": "unavailable", "reason": "No real human ratings exist"}
    mapping = {entry.blinded_item_id: entry for entry in load_blinding_map(map_path)}
    tidy = tidy_annotation_frame(events)
    per_item_annotators = tidy.groupby("blinded_item_id")["annotator_id"].nunique()
    if (per_item_annotators > 1).any():
        raise ValueError("Multiple annotators require adjudication before primary analysis")
    wide = tidy.pivot_table(
        index=["blinded_item_id", "source_response_hash"],
        columns="axis_id",
        values="score",
        aggfunc="first",
    ).reset_index()
    manifest = {row.run_id: row for row in rows}
    analysis_rows = []
    for item in wide.to_dict(orient="records"):
        entry = mapping.get(item["blinded_item_id"])
        if entry is None or entry.run_id not in manifest:
            raise ValueError("Annotation mapping is missing or outside Study V2")
        turn = turn_lookup.get((entry.run_id, entry.turn_number))
        if turn is None or response_hash(turn.result.text or "") != item["source_response_hash"]:
            raise ValueError("Annotation source hash does not match immutable Study V2 evidence")
        row = manifest[entry.run_id]
        analysis_rows.append(
            {
                "run_id": entry.run_id,
                "turn_number": entry.turn_number,
                "script_id": row.script_id,
                "theme": row.theme.value,
                "presentation_level": row.presentation_level.value,
                "model_slot": row.model_slot,
                "requested_model_id": row.requested_model_id,
                "context_condition": row.context_condition.value,
                "repetition": row.repetition,
                "data_status": "main_study",
                "truncated": turn.result.truncated,
                **{axis: item.get(axis) for axis in ("A1", "A2", "A3", "B1", "B2", "B3", "C1")},
            }
        )
    turns = pd.DataFrame(analysis_rows)
    conversations = summarize_conversations(turns)
    comparisons = matched_descriptive_comparisons(conversations)
    sensitivity_turns = turns.loc[~turns["truncated"]].copy()
    sensitivity = summarize_conversations(sensitivity_turns)
    bootstrap = {
        axis: {
            unit: bootstrap_ci(
                conversations,
                f"mean_{axis}",
                resample_unit=unit,
                seed=20260814,
            )
            for unit in ("conversation", "script_cluster")
        }
        for axis in ("A1", "A2", "A3")
    }
    output_directory.mkdir(parents=True, exist_ok=False)
    turns.to_csv(output_directory / "rated_turns.csv", index=False)
    conversations.to_csv(output_directory / "conversation_outcomes.csv", index=False)
    comparisons.to_csv(output_directory / "matched_comparisons.csv", index=False)
    sensitivity.to_csv(output_directory / "sensitivity_excluding_truncated.csv", index=False)
    (output_directory / "cluster_bootstrap.json").write_text(
        json.dumps(bootstrap, indent=2) + "\n", encoding="utf-8"
    )
    figure_data = conversations.melt(
        id_vars=["model_slot", "context_condition"],
        value_vars=["mean_A1", "mean_A2", "mean_A3"],
        var_name="primary_axis",
        value_name="conversation_mean",
    )
    figure = px.box(
        figure_data,
        x="primary_axis",
        y="conversation_mean",
        color="model_slot",
        facet_col="context_condition",
        points="all",
        title="Study V2 primary outcomes (human annotations)",
    )
    figure.write_html(
        output_directory / "primary_outcomes.html",
        include_plotlyjs="cdn",
        full_html=True,
        div_id="study-v2-primary-outcomes",
    )
    return {
        "availability": "available",
        "rated_response_observations": len(turns),
        "conversation_summaries": len(conversations),
        "complete_conversation_summaries": int(conversations["is_complete"].sum()),
        "truncated_rated_observations": int(turns["truncated"].sum()),
        "output_directory": str(output_directory.resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--blinding-map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = build_analysis(
            annotations_path=args.annotations,
            map_path=args.blinding_map,
            output_directory=args.output_directory,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    # An honest unavailable state is expected before data collection and is not a
    # software failure. Invalid or mixed evidence still raises and returns 2 above.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
