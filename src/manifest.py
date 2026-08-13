"""Deterministic full-study manifest generation and validation."""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pandas as pd

from src.config_loader import resolve_model_ids
from src.schemas import ContextCondition, ManifestRow, ModelsConfig, RunStatus, ScriptConfig

STUDY_VERSION = "study-v1.0.0"
EXECUTION_RANDOM_SEED = 20260814


def _run_id(script_id: str, model_slot: str, context: ContextCondition, repetition: int) -> str:
    return f"{STUDY_VERSION}_{script_id}_{model_slot}_{context.value}_r{repetition}"


def generate_manifest(
    scripts: list[ScriptConfig],
    models: ModelsConfig,
    *,
    random_seed: int = EXECUTION_RANDOM_SEED,
) -> list[ManifestRow]:
    model_ids = resolve_model_ids(models)
    factors: list[tuple[ScriptConfig, str, ContextCondition, int]] = []
    for script in sorted(scripts, key=lambda item: item.script_id):
        for model_slot in ("model_a", "model_b"):
            for context in ContextCondition:
                for repetition in (1, 2):
                    factors.append((script, model_slot, context, repetition))
    random.Random(random_seed).shuffle(factors)
    return [
        ManifestRow(
            study_version=STUDY_VERSION,
            run_id=_run_id(script.script_id, model_slot, context, repetition),
            script_id=script.script_id,
            theme=script.theme,
            presentation_level=script.presentation_level,
            model_slot=model_slot,  # type: ignore[arg-type]
            requested_model_id=model_ids[model_slot],
            context_condition=context,
            repetition=repetition,
            generation_config_version=models.generation.version,
            planned_seed=models.generation.seed,
            execution_order=order,
            status=RunStatus.PLANNED,
        )
        for order, (script, model_slot, context, repetition) in enumerate(factors, start=1)
    ]


def validate_manifest(rows: list[ManifestRow]) -> list[str]:
    errors: list[str] = []
    if len(rows) != 72:
        errors.append(f"Expected 72 manifest rows; found {len(rows)}")
    if len({row.run_id for row in rows}) != len(rows):
        errors.append("Manifest run IDs are not unique")
    if {row.execution_order for row in rows} != set(range(1, len(rows) + 1)):
        errors.append("Execution order must be a complete 1..N sequence")
    counts = Counter(
        (
            row.theme.value,
            row.presentation_level.value,
            row.model_slot,
            row.context_condition.value,
            row.repetition,
        )
        for row in rows
    )
    if len(counts) != 72 or set(counts.values()) != {1}:
        errors.append("The 3x3x2x2x2 factorial cells are not perfectly balanced")
    return errors


def manifest_dataframe(rows: list[ManifestRow]) -> pd.DataFrame:
    return pd.DataFrame([row.model_dump(mode="json") for row in rows]).sort_values(
        "execution_order"
    )


def write_manifest_csv(rows: list[ManifestRow], path: str | Path) -> Path:
    errors = validate_manifest(rows)
    if errors:
        raise ValueError("; ".join(errors))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_dataframe(rows).to_csv(output, index=False)
    return output
