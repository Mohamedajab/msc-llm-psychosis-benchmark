"""Deterministic full-study manifest generation and validation."""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pandas as pd

from src.config_loader import generation_for_repetition, resolve_model_ids
from src.schemas import ContextCondition, ManifestRow, ModelsConfig, RunStatus, ScriptConfig

STUDY_VERSION = "study-v2.0.0"
EXECUTION_RANDOM_SEED = 20260814


def _run_id(
    study_version: str,
    script_id: str,
    model_slot: str,
    context: ContextCondition,
    repetition: int,
) -> str:
    return f"{study_version}_{script_id}_{model_slot}_{context.value}_r{repetition}"


def generate_manifest(
    scripts: list[ScriptConfig],
    models: ModelsConfig,
    *,
    random_seed: int = EXECUTION_RANDOM_SEED,
    study_version: str = STUDY_VERSION,
) -> list[ManifestRow]:
    model_ids = resolve_model_ids(models)
    factors: list[tuple[ScriptConfig, str, ContextCondition, int]] = []
    for script in sorted(scripts, key=lambda item: item.script_id):
        for model_slot in models.model_slots:
            for context in ContextCondition:
                for repetition in (1, 2):
                    factors.append((script, model_slot, context, repetition))
    random.Random(random_seed).shuffle(factors)
    return [
        ManifestRow(
            study_version=study_version,
            run_id=_run_id(study_version, script.script_id, model_slot, context, repetition),
            script_id=script.script_id,
            theme=script.theme,
            presentation_level=script.presentation_level,
            model_slot=model_slot,
            requested_model_id=model_ids[model_slot],
            context_condition=context,
            repetition=repetition,
            generation_config_version=models.generation.version,
            planned_seed=generation_for_repetition(models, repetition).seed,
            execution_order=order,
            status=RunStatus.PLANNED,
        )
        for order, (script, model_slot, context, repetition) in enumerate(factors, start=1)
    ]


def validate_manifest(
    rows: list[ManifestRow],
    *,
    models: ModelsConfig | None = None,
    expected_study_version: str | None = None,
) -> list[str]:
    errors: list[str] = []
    model_slots = {row.model_slot for row in rows}
    expected_rows = 9 * len(model_slots) * len(ContextCondition) * 2
    if len(model_slots) != 2:
        errors.append("Study V2 requires exactly two named model slots")
    if models is not None:
        configured_slots = set(models.model_slots)
        configured_ids = resolve_model_ids(models)
        if model_slots != configured_slots:
            errors.append("Manifest model slots differ from the supplied configuration")
        for row in rows:
            if configured_ids.get(row.model_slot) != row.requested_model_id:
                errors.append("Manifest contains an unknown or mismatched model ID")
                break
            if row.generation_config_version != models.generation.version:
                errors.append("Manifest generation version differs from configuration")
                break
            if row.planned_seed != models.repetition_seeds.get(row.repetition):
                errors.append("Manifest repetition seed differs from configuration")
                break
    if expected_study_version is not None and any(
        row.study_version != expected_study_version for row in rows
    ):
        errors.append("Manifest study version differs from the expected frozen version")
    if any(
        "placeholder" in row.requested_model_id.casefold()
        or row.requested_model_id in {"openrouter/free", "openrouter/auto"}
        or "latest" in row.requested_model_id.casefold()
        or not row.requested_model_id.endswith(":free")
        for row in rows
    ):
        errors.append("Manifest contains a placeholder, router, alias or non-free model ID")
    if expected_rows != 72:
        errors.append(f"Study V2 must contain 72 rows; derived {expected_rows}")
    if len(rows) != expected_rows:
        errors.append(f"Expected {expected_rows} manifest rows; found {len(rows)}")
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
    if len(counts) != expected_rows or set(counts.values()) != {1}:
        errors.append(f"The 3x3x{len(model_slots)}x2x2 factorial cells are not perfectly balanced")
    if len(rows) * 6 != 432:
        errors.append("Study V2 must contain 432 planned response slots")
    return errors


def manifest_dataframe(rows: list[ManifestRow]) -> pd.DataFrame:
    return pd.DataFrame([row.model_dump(mode="json") for row in rows]).sort_values(
        "execution_order"
    )


def write_manifest_csv(
    rows: list[ManifestRow],
    path: str | Path,
    *,
    models: ModelsConfig | None = None,
    expected_study_version: str | None = None,
) -> Path:
    errors = validate_manifest(
        rows,
        models=models,
        expected_study_version=expected_study_version,
    )
    if errors:
        raise ValueError("; ".join(errors))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_dataframe(rows).to_csv(output, index=False)
    return output
