"""Versioned machine-readable Study V2 replacement-pending status.

The second Study V2 comparator (NVIDIA Nemotron Super) is rejected on technical
generation-suitability grounds only. Until a replacement endpoint passes a
prospective technical screen and is explicitly frozen, the main study remains
blocked. This module is the single source of truth for that fail-closed state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

STATUS_VERSION = "study-v2-status-v1.0.0"
STATUS_PATH = Path(__file__).resolve().parents[1] / "config" / "study-v2-status.yaml"

FROZEN_REPLACEMENT_STATE = "FROZEN"


class StudyV2Status(BaseModel):
    """Replacement-pending state; extra keys are rejected to fail closed."""

    model_config = ConfigDict(extra="forbid")

    version: str
    replacement_endpoint_status: str
    pilot_v6_status: str
    main_study_status: str
    blocker: str
    rejected_comparator: str
    rejection_scope: str
    retained_technically_qualified_candidate: str


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
    """Return True when the main study is blocked by a missing replacement endpoint."""
    current = status if status is not None else load_study_v2_status()
    return current.replacement_endpoint_status != FROZEN_REPLACEMENT_STATE
