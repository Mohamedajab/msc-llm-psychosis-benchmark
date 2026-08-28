"""Configuration loading, cross-file validation, and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from src.schemas import GenerationConfig, HistoryPrefix, ModelsConfig, RubricConfig, ScriptConfig


class ConfigurationError(ValueError):
    """A required versioned configuration is missing or invalid."""


def _load_raw(path: str | Path) -> Any:
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigurationError(f"Configuration file not found: {file_path}")
    try:
        with file_path.open(encoding="utf-8") as handle:
            if file_path.suffix.casefold() in {".yaml", ".yml"}:
                return yaml.safe_load(handle)
            return json.load(handle)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ConfigurationError(f"Malformed configuration in {file_path}: {error}") from error


def _load_model[ModelT: BaseModel](path: str | Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate(_load_raw(path))
    except ValidationError as error:
        raise ConfigurationError(f"Invalid configuration in {path}: {error}") from error


def load_scripts(directory: str | Path) -> list[ScriptConfig]:
    scripts = [_load_model(path, ScriptConfig) for path in sorted(Path(directory).glob("*.json"))]
    if not scripts:
        raise ConfigurationError(f"No script JSON files found in {directory}")
    return scripts


def load_histories(directory: str | Path) -> list[HistoryPrefix]:
    histories = [
        _load_model(path, HistoryPrefix) for path in sorted(Path(directory).glob("*.json"))
    ]
    if not histories:
        raise ConfigurationError(f"No history JSON files found in {directory}")
    return histories


def load_models(path: str | Path) -> ModelsConfig:
    return _load_model(path, ModelsConfig)


def load_rubric(path: str | Path) -> RubricConfig:
    return _load_model(path, RubricConfig)


def resolve_model_ids(
    config: ModelsConfig,
) -> dict[str, str]:
    """Return exact model slugs from the versioned configuration."""

    resolved: dict[str, str] = {}
    for slot_name, slot in config.model_slots.items():
        value = slot.default_model_id.strip()
        if not value or value in {"openrouter/free", "openrouter/auto"} or "latest" in value:
            raise ConfigurationError(
                f"{slot_name} must contain one exact concrete model slug; received {value!r}"
            )
        resolved[slot_name] = value
    if set(resolved) != set(config.model_slots):
        raise ConfigurationError("Every configured target-model slot must resolve")
    if len(set(resolved.values())) != len(resolved):
        raise ConfigurationError("Configured target-model slots must resolve to distinct IDs")
    return resolved


def generation_for_repetition(config: ModelsConfig, repetition: int) -> GenerationConfig:
    """Return generation settings containing the prespecified per-run seed."""
    try:
        seed = config.repetition_seeds[repetition]
    except KeyError as error:
        raise ConfigurationError(f"No prespecified seed for repetition {repetition}") from error
    return config.generation.model_copy(update={"seed": seed})


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 over JSON-compatible configuration content."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def validate_catalogue(scripts: list[ScriptConfig], histories: list[HistoryPrefix]) -> list[str]:
    """Validate the frozen 3x3 script design and shared theme prefixes."""
    errors: list[str] = []
    if len(scripts) != 9:
        errors.append(f"Expected exactly 9 scripts; found {len(scripts)}")
    ids = [script.script_id for script in scripts]
    if len(ids) != len(set(ids)):
        errors.append("Script IDs must be unique")
    cells = {(script.theme.value, script.presentation_level.value) for script in scripts}
    expected_cells = {
        (theme, presentation)
        for theme in ("monitoring", "personal_messages", "ai_relationship")
        for presentation in ("control", "ambiguous", "fixed_belief")
    }
    if cells != expected_cells:
        errors.append(f"Script cells do not match the required 3x3 design: {sorted(cells)}")

    histories_by_id = {history.history_id: history for history in histories}
    if len(histories_by_id) != 3:
        errors.append(f"Expected 3 shared history prefixes; found {len(histories_by_id)}")
    for script in scripts:
        history = histories_by_id.get(script.history_id)
        if history is None:
            errors.append(f"{script.script_id} references missing history {script.history_id}")
        elif history.theme != script.theme:
            errors.append(f"{script.script_id} history theme does not match script theme")
    for theme in ("monitoring", "personal_messages", "ai_relationship"):
        linked = {script.history_id for script in scripts if script.theme.value == theme}
        if len(linked) != 1:
            errors.append(f"All {theme} presentations must share exactly one frozen prefix")
    return errors


def configuration_bundle_hash(
    scripts: list[ScriptConfig], histories: list[HistoryPrefix], models: ModelsConfig
) -> str:
    return canonical_hash(
        {
            "scripts": [
                script.model_dump(mode="json")
                for script in sorted(scripts, key=lambda x: x.script_id)
            ],
            "histories": [
                history.model_dump(mode="json")
                for history in sorted(histories, key=lambda x: x.history_id)
            ],
            "models": models.model_dump(mode="json"),
        }
    )
