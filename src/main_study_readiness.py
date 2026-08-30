"""Offline, fail-closed readiness evaluation for the final Study V2 protocol."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from src.pilot_v6 import PilotV6Verdict, assess_pilot_v6
from src.replacement_selection import (
    ReplacementSelectionError,
    validate_replacement_selection_record,
)
from src.schemas import StrictModel

READINESS_VERSION = "main-study-readiness-v2.0.0"
GOVERNANCE_VERSION = "main-study-governance-v2.0.0"
ORIGINAL_PAIR_SOURCE = "ORIGINAL_PAIR_V6"
NO_FINAL_PAIR_SOURCE = "NONE"


class ReadinessState(StrEnum):
    NOT_FETCHED = "NOT_FETCHED"
    NOT_RUN = "NOT_RUN"
    NOT_SELECTED = "NOT_SELECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_CREATED = "NOT_CREATED"
    INVALID = "INVALID"
    PASS = "PASS"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"
    READY = "READY"


class MainStudyGovernance(StrictModel):
    version: str = GOVERNANCE_VERSION
    supervisor_review: Literal["PENDING", "CONFIRMED"]
    ethics_status: Literal["PENDING", "NO_FURTHER_REVIEW_REQUIRED", "FAVOURABLE_REVIEW"]
    rubric_status: Literal["DRAFT", "FROZEN"]
    annotation_procedure_status: Literal["DRAFT", "FROZEN"]
    data_management_status: Literal["DRAFT", "CONFIRMED"]
    notes: tuple[str, ...] = ()


class MainStudyReadiness(StrictModel):
    readiness_version: str = READINESS_VERSION
    replacement_catalogue: str
    replacement_screen: str
    replacement_selection: str
    pilot_v6: str
    final_pair_status: str
    final_pair_source: str
    replacement_required: bool
    active_bundle: str
    governance: str
    main_study: str
    blockers: tuple[str, ...] = ()
    network_requests: int = 0
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


def load_governance(path: str | Path) -> MainStudyGovernance:
    source = Path(path)
    if not source.is_file():
        raise ValueError("Main-study governance record is missing")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    governance = MainStudyGovernance.model_validate(raw)
    if governance.version != GOVERNANCE_VERSION:
        raise ValueError("Main-study governance version mismatch")
    return governance


def governance_blockers(governance: MainStudyGovernance) -> tuple[str, ...]:
    blockers: list[str] = []
    if governance.supervisor_review != "CONFIRMED":
        blockers.append("supervisor_review_not_confirmed")
    if governance.ethics_status == "PENDING":
        blockers.append("ethics_determination_pending")
    if governance.rubric_status != "FROZEN":
        blockers.append("rubric_not_frozen")
    if governance.annotation_procedure_status != "FROZEN":
        blockers.append("annotation_procedure_not_frozen")
    if governance.data_management_status != "CONFIRMED":
        blockers.append("data_management_not_confirmed")
    return tuple(blockers)


def evaluate_main_study_readiness(
    *,
    repository_root: str | Path,
    governance_path: str | Path,
    catalogue_record_path: str | Path | None = None,
    selection_record_path: str | Path | None = None,
    screen_output_root: str | Path | None = None,
    pilot_output_root: str | Path | None = None,
    active_bundle_root: str | Path | None = None,
    final_artifact_root: str | Path | None = None,
) -> MainStudyReadiness:
    """Recompute every technical gate without constructing a provider."""

    root = Path(repository_root)
    blockers: list[str] = []
    safe: dict[str, Any] = {}
    catalogue_state = (
        ReadinessState.PASS.value
        if catalogue_record_path is not None and Path(catalogue_record_path).is_file()
        else ReadinessState.NOT_FETCHED.value
    )
    selection_state = ReadinessState.NOT_SELECTED.value
    screen_state = ReadinessState.NOT_RUN.value
    selection = None
    if catalogue_state == ReadinessState.PASS.value and selection_record_path is not None:
        try:
            if screen_output_root is None:
                raise ReplacementSelectionError("Replacement screen evidence root is missing")
            selection = validate_replacement_selection_record(
                selection_record_path=selection_record_path,
                catalogue_record_path=catalogue_record_path,
                screen_output_root=screen_output_root,
                repository_root=root,
            )
            selection_state = ReadinessState.PASS.value
            screen_state = ReadinessState.PASS.value
            safe["selected_model_id"] = selection.selected_model_id
            safe["selection_policy_version"] = selection.selection_policy_version
        except (OSError, RuntimeError, ValueError) as error:
            selection_state = ReadinessState.INVALID.value
            screen_state = ReadinessState.INVALID.value
            safe["selection_error_type"] = type(error).__name__
    pilot_assessment = assess_pilot_v6(
        pilot_output_root=(
            pilot_output_root or root / "data" / "private" / "technical-pilot-v6.0.0"
        ),
        repository_root=root,
        persist=False,
    )
    pilot_state = pilot_assessment.verdict.value
    safe["pilot_v6_source_evidence_hash"] = pilot_assessment.source_evidence_hash
    if pilot_assessment.verdict == PilotV6Verdict.PASS:
        final_pair_status = ReadinessState.QUALIFIED.value
        final_pair_source = ORIGINAL_PAIR_SOURCE
        replacement_required = False
    else:
        final_pair_status = ReadinessState.NOT_QUALIFIED.value
        final_pair_source = NO_FINAL_PAIR_SOURCE
        replacement_required = pilot_assessment.verdict == PilotV6Verdict.FAIL
        blockers.extend(("final_model_pair_not_qualified", "pilot_v6_not_pass"))
    safe["final_pair_source"] = final_pair_source
    safe["replacement_required"] = replacement_required
    if replacement_required and selection_state != ReadinessState.PASS.value:
        blockers.extend(("replacement_endpoint_not_frozen", "replacement_screen_not_pass"))
    elif replacement_required:
        blockers.append("replacement_pair_pilot_v7_not_pass")

    active_state = ReadinessState.NOT_CREATED.value
    if active_bundle_root is not None and Path(active_bundle_root).is_dir():
        try:
            from src.active_study import verify_active_study_bundle

            verify_active_study_bundle(
                bundle_root=active_bundle_root,
                repository_root=root,
                artifact_root=final_artifact_root or root,
                selection_record_path=selection_record_path,
                catalogue_record_path=catalogue_record_path,
                screen_output_root=screen_output_root,
                pilot_output_root=pilot_output_root,
            )
            active_state = ReadinessState.PASS.value
        except (OSError, RuntimeError, ValueError) as error:
            active_state = ReadinessState.INVALID.value
            safe["active_bundle_error_type"] = type(error).__name__
    if active_state != ReadinessState.PASS.value:
        blockers.append(
            "active_bundle_not_created"
            if active_state == ReadinessState.NOT_CREATED.value
            else "active_bundle_invalid"
        )

    try:
        governance = load_governance(governance_path)
        academic_blockers = governance_blockers(governance)
        governance_state = (
            ReadinessState.PASS.value if not academic_blockers else ReadinessState.BLOCKED.value
        )
        blockers.extend(academic_blockers)
    except (OSError, ValueError):
        governance_state = ReadinessState.INVALID.value
        blockers.append("governance_record_invalid")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return MainStudyReadiness(
        replacement_catalogue=catalogue_state,
        replacement_screen=screen_state,
        replacement_selection=selection_state,
        pilot_v6=pilot_state,
        final_pair_status=final_pair_status,
        final_pair_source=final_pair_source,
        replacement_required=replacement_required,
        active_bundle=active_state,
        governance=governance_state,
        main_study=ReadinessState.READY.value if ready else ReadinessState.BLOCKED.value,
        blockers=unique_blockers,
        safe_metadata=safe,
    )
