"""Versioned machine-readable Study V2 pre-qualification status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

STATUS_VERSION = "study-v2-status-v2.1.0"
STATUS_PATH = Path(__file__).resolve().parents[1] / "config" / "study-v2-status.yaml"


class StudyV2Status(BaseModel):
    """Prospective final-pair state; extra keys are rejected to fail closed."""

    model_config = ConfigDict(extra="forbid")

    version: str
    replacement_endpoint_status: str
    pilot_v6_status: str
    final_pair_status: str
    final_pair_source: str
    replacement_required: bool
    main_study_status: str
    blocker: str
    intended_model_a: str
    intended_model_b: str


def load_study_v2_status(path: str | Path = STATUS_PATH) -> StudyV2Status:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Study V2 status file not found: {file_path}")
    raw: Any = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    status = StudyV2Status.model_validate(raw)
    if status.version != STATUS_VERSION:
        raise ValueError(
            f"Study V2 status version mismatch: expected {STATUS_VERSION}, got {status.version}"
        )
    return status


def replacement_endpoint_not_frozen(status: StudyV2Status | None = None) -> bool:
    """Return whether the fallback path requires an unresolved replacement."""
    current = status if status is not None else load_study_v2_status()
    return current.replacement_required and current.replacement_endpoint_status != "FROZEN"


def final_model_pair_not_qualified(status: StudyV2Status | None = None) -> bool:
    """Return True until a frozen technical-pilot path qualifies the exact pair."""

    current = status if status is not None else load_study_v2_status()
    return current.final_pair_status != "QUALIFIED"
