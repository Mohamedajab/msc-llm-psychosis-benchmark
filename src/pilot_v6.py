"""Original-pair Pilot V6 planning and fail-closed qualification.

The predetermined minimum subset reuses the established monitoring fixed-belief
technical scenario and crosses both final models with both context conditions.
This yields four six-turn conversations (24 slots), exercising exact model
resolution, context loading and multi-turn history without selecting scenarios
from model behaviour.
"""

from __future__ import annotations

import random
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from src.config_loader import (
    configuration_bundle_hash,
    generation_for_model,
    load_histories,
    load_models,
    load_scripts,
)
from src.conversation_runner import ConversationRunner, create_run_header, payload_hash
from src.generation_profiles import (
    GENERATION_V4_MAX_COMPLETION_TOKENS,
    GENERATION_V4_VERSION,
    require_generation_v4,
)
from src.payloads import build_target_messages
from src.pilot_qualification import _assess_pilot
from src.provider_client import DeterministicFixtureProvider
from src.schemas import (
    ContextCondition,
    ManifestRow,
    ModelsConfig,
    RunStatus,
    StrictModel,
)
from src.storage import RawRunStore, atomic_write_json

PILOT_V6_VERSION = "technical-pilot-v6.0.0"
PILOT_V6_NAMESPACE = "technical-pilot-v6"
PILOT_V6_ASSESSMENT_VERSION = "pilot-v6-qualification-v1.0.0"
FINAL_CONFIGURATION_VERSION = "2.3.0"
FINAL_STUDY_VERSION = "study-v2.1.0"
MINIMAX_MODEL_ID = "minimax/minimax-m3:free"
NEMOTRON_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b:free"
FINAL_PAIR_SOURCE = "ORIGINAL_PAIR_V6"
SCRIPT_ID = "monitoring_fixed_belief_v1"
GENERATION_VERSION = GENERATION_V4_VERSION
MAX_COMPLETION_TOKENS = GENERATION_V4_MAX_COMPLETION_TOKENS
PLANNED_CONVERSATIONS = 4
PLANNED_RESPONSE_SLOTS = 24
MAX_HTTP_ATTEMPTS = 32
FAILURE_ATTEMPT_ALLOWANCE = 8
MINIMUM_REQUEST_INTERVAL_SECONDS = 5.0
PILOT_RANDOM_SEED = 20260814
REPETITION = 1


class PilotV6Verdict(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"
    FAIL = "FAIL"
    PASS = "PASS"


class PilotV6Error(RuntimeError):
    """Pilot V6 cannot be planned, executed or qualified safely."""


class PilotV6Assessment(StrictModel):
    assessment_version: str = PILOT_V6_ASSESSMENT_VERSION
    assessment_id: str
    assessed_at: datetime
    pilot_version: str = PILOT_V6_VERSION
    study_version: str = FINAL_STUDY_VERSION
    configuration_version: str = FINAL_CONFIGURATION_VERSION
    generation_version: str = GENERATION_VERSION
    final_pair_source: str = FINAL_PAIR_SOURCE
    intended_model_ids: dict[str, str] = Field(default_factory=dict)
    verdict: PilotV6Verdict
    failed_criteria: tuple[str, ...] = ()
    statistics: dict[str, Any] = Field(default_factory=dict)
    source_evidence_hash: str
    source_file_hashes: dict[str, str] = Field(default_factory=dict)


def build_original_pair_models_config(*, repository_root: str | Path) -> ModelsConfig:
    """Build the exact prospective MiniMax/Nemotron pair without private evidence."""

    root = Path(repository_root)
    base = load_models(root / "config" / "models.yaml")
    try:
        require_generation_v4(base.generation)
    except ValueError as error:
        raise PilotV6Error("Frozen generation-v4 settings changed") from error
    if base.repetition_seeds != {1: 20260814, 2: 20260815}:
        raise PilotV6Error("Frozen repetition seeds changed")
    expected = {
        "model_minimax": MINIMAX_MODEL_ID,
        "model_nemotron": NEMOTRON_MODEL_ID,
    }
    if {name: slot.default_model_id for name, slot in base.model_slots.items()} != expected:
        raise PilotV6Error("Frozen original-pair model identities changed")
    if any(slot.completion_limit_parameter is None for slot in base.model_slots.values()):
        raise PilotV6Error("Original pair lacks a frozen completion-limit translation")
    payload = base.model_dump(mode="json")
    payload.update(
        {
            "version": FINAL_CONFIGURATION_VERSION,
            "notes": [
                "Prospective final Study V2 original pair: MiniMax M3 and NVIDIA Nemotron 3 Super.",
                "Pilot V6 jointly requalifies both endpoints under generation-v4.",
                "Historical Pilot V4/V5 failures remain immutable under generation-v2/v3.",
                "Provider identity is recorded; automatic fallback remains disabled.",
            ],
        }
    )
    return ModelsConfig.model_validate(payload)


def load_pilot_v6_configuration(
    *,
    repository_root: str | Path,
    selection_record_path: str | Path | None = None,
    catalogue_record_path: str | Path | None = None,
    screen_output_root: str | Path | None = None,
) -> tuple[None, Any, Any, ModelsConfig, list[Any], list[Any]]:
    # Legacy replacement arguments are intentionally non-authoritative. Keeping
    # them as ignored keyword-only inputs avoids turning an API transition into
    # permission to alter the frozen original-pair V6 design.
    del selection_record_path, catalogue_record_path, screen_output_root
    root = Path(repository_root)
    scripts = load_scripts(root / "config" / "scenarios")
    histories = load_histories(root / "config" / "histories")
    script = next((value for value in scripts if value.script_id == SCRIPT_ID), None)
    if script is None or script.presentation_level.value != "fixed_belief":
        raise PilotV6Error("Frozen Pilot V6 scenario is unavailable")
    prefix = next((value for value in histories if value.history_id == script.history_id), None)
    if prefix is None:
        raise PilotV6Error("Frozen Pilot V6 history is unavailable")
    models = build_original_pair_models_config(repository_root=root)
    return None, script, prefix, models, scripts, histories


def pilot_v6_rows(
    *,
    repository_root: str | Path,
    selection_record_path: str | Path | None = None,
    catalogue_record_path: str | Path | None = None,
    screen_output_root: str | Path | None = None,
) -> list[ManifestRow]:
    _, script, _, models, _, _ = load_pilot_v6_configuration(
        repository_root=repository_root,
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
    )
    cells = [(slot, condition) for slot in models.model_slots for condition in ContextCondition]
    random.Random(PILOT_RANDOM_SEED).shuffle(cells)
    rows = [
        ManifestRow(
            study_version=PILOT_V6_VERSION,
            run_id=(f"{PILOT_V6_NAMESPACE}_{script.script_id}_{slot}_{condition.value}_r1"),
            script_id=script.script_id,
            theme=script.theme,
            presentation_level=script.presentation_level,
            model_slot=slot,
            requested_model_id=models.model_slots[slot].default_model_id,
            context_condition=condition,
            repetition=REPETITION,
            generation_config_version=models.generation.version,
            planned_seed=models.repetition_seeds[REPETITION],
            execution_order=order,
            status=RunStatus.PLANNED,
        )
        for order, (slot, condition) in enumerate(cells, start=1)
    ]
    if len(rows) != PLANNED_CONVERSATIONS or len(rows) * 6 != PLANNED_RESPONSE_SLOTS:
        raise PilotV6Error("Pilot V6 shape must remain 4 conversations / 24 response slots")
    return rows


def build_pilot_v6_offline_plan(
    *,
    repository_root: str | Path,
    selection_record_path: str | Path | None = None,
    catalogue_record_path: str | Path | None = None,
    screen_output_root: str | Path | None = None,
) -> dict[str, Any]:
    _, script, prefix, models, scripts, histories = load_pilot_v6_configuration(
        repository_root=repository_root,
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
    )
    rows = pilot_v6_rows(repository_root=repository_root)
    configuration_hash = configuration_bundle_hash(scripts, histories, models)
    with tempfile.TemporaryDirectory(prefix="pilot-v6-offline-") as temporary:
        provider = DeterministicFixtureProvider()
        runner = ConversationRunner(provider, RawRunStore(temporary))
        runs = []
        for row in rows:
            generation = generation_for_model(models, row.model_slot, REPETITION)
            header = create_run_header(
                study_version=PILOT_V6_VERSION,
                run_id=row.run_id,
                data_status="technical_pilot",
                script=script,
                condition=row.context_condition,
                model_slot=row.model_slot,
                model_id=row.requested_model_id,
                repetition=REPETITION,
                generation=generation,
                configuration_version=models.version,
                configuration_hash=configuration_hash,
            )
            payloads = runner.dry_run(header=header, script=script, prefix=prefix)
            runs.append(
                {
                    "execution_order": row.execution_order,
                    "run_id": row.run_id,
                    "model_slot": row.model_slot,
                    "requested_model_id": row.requested_model_id,
                    "context_condition": row.context_condition.value,
                    "payload_count": len(payloads),
                }
            )
        if provider.calls:
            raise PilotV6Error("Offline Pilot V6 unexpectedly called a provider")
    return {
        "pilot_version": PILOT_V6_VERSION,
        "status": "offline_preflight",
        "network_called": False,
        "network_requests": 0,
        "final_pair_source": FINAL_PAIR_SOURCE,
        "model_ids": {name: slot.default_model_id for name, slot in models.model_slots.items()},
        "configuration_version": models.version,
        "configuration_hash": configuration_hash,
        "generation_version": models.generation.version,
        "max_tokens": models.generation.max_tokens,
        "planned_conversations": PLANNED_CONVERSATIONS,
        "planned_response_slots": PLANNED_RESPONSE_SLOTS,
        "maximum_http_attempts": MAX_HTTP_ATTEMPTS,
        "failure_attempt_allowance": FAILURE_ATTEMPT_ALLOWANCE,
        "minimum_request_interval_seconds": MINIMUM_REQUEST_INTERVAL_SECONDS,
        "runs": runs,
    }


def assess_pilot_v6(
    *,
    pilot_output_root: str | Path,
    repository_root: str | Path,
    selection_record_path: str | Path | None = None,
    catalogue_record_path: str | Path | None = None,
    screen_output_root: str | Path | None = None,
    assessment_root: str | Path | None = None,
    persist: bool = False,
    assessed_at: datetime | None = None,
) -> PilotV6Assessment:
    _, script, prefix, models, scripts, histories = load_pilot_v6_configuration(
        repository_root=repository_root,
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
    )
    rows = pilot_v6_rows(repository_root=repository_root)

    def configuration_loader():  # noqa: ANN202
        return None, None, models, scripts, histories

    base = _assess_pilot(
        output_root=pilot_output_root,
        pilot_version=PILOT_V6_VERSION,
        pilot_namespace=PILOT_V6_NAMESPACE,
        assessment_version=PILOT_V6_ASSESSMENT_VERSION,
        assessment_directory="pilot-v6-qualification",
        configuration_loader=configuration_loader,
        rows_loader=lambda: rows,
        persist=False,
        assessed_at=assessed_at,
    )
    verdict = PilotV6Verdict(base.verdict.value)
    request_integrity_failures: set[str] = set()
    store = RawRunStore(pilot_output_root)
    event_ids: set[str] = set()
    for row in rows:
        generation = generation_for_model(models, row.model_slot, REPETITION)
        if not (store.run_directory(row.run_id) / "run.json").is_file():
            continue
        try:
            record = store.load(row.run_id)
        except (OSError, ValueError):
            continue
        expected_history_id = (
            prefix.history_id
            if row.context_condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT
            else None
        )
        if record.header.history_id != expected_history_id:
            request_integrity_failures.add("pilot_v6_header_integrity")
        for event in (*record.turns, *record.errors):
            if event.event_id in event_ids:
                request_integrity_failures.add("pilot_v6_duplicate_event_id")
            event_ids.add(event.event_id)
            expected_messages = build_target_messages(
                condition=row.context_condition,
                prefix=prefix,
                completed_exchanges=[
                    (prior.user_message, prior.result.text or "")
                    for prior in record.turns
                    if prior.turn_number < event.turn_number
                ],
                current_user_message=script.turns[event.turn_number - 1],
                visible_response_instruction=generation.visible_response_instruction,
            )
            expected_parameters = generation.request_parameters()
            if (
                event.request_messages != expected_messages
                or event.request_parameters != expected_parameters
                or event.request_stream is not False
                or event.request_payload_hash
                != payload_hash(
                    model_id=row.requested_model_id,
                    messages=expected_messages,
                    parameters=expected_parameters,
                )
            ):
                request_integrity_failures.add("pilot_v6_request_payload_integrity")
            if (
                event.event_type == "turn_success"
                and event.user_message != script.turns[event.turn_number - 1]
            ):
                request_integrity_failures.add("pilot_v6_request_payload_integrity")
    if request_integrity_failures:
        request_integrity_failures.add("evidence_is_well_formed_unique_and_verifiable")
        verdict = PilotV6Verdict.FAIL
    failed_criteria = tuple(sorted(set(base.failed_criteria) | request_integrity_failures))
    assessment = PilotV6Assessment(
        assessment_id=base.assessment_id,
        assessed_at=base.assessed_at,
        intended_model_ids={
            name: slot.default_model_id for name, slot in models.model_slots.items()
        },
        verdict=verdict,
        failed_criteria=failed_criteria,
        statistics=base.statistics,
        source_evidence_hash=base.source_evidence_hash,
        source_file_hashes=base.source_file_hashes,
    )
    if persist:
        destination_root = (
            Path(assessment_root)
            if assessment_root is not None
            else Path(pilot_output_root).parent / "pilot-v6-qualification"
        )
        timestamp = assessment.assessed_at.strftime("%Y%m%dT%H%M%S%fZ")
        atomic_write_json(
            destination_root / f"{timestamp}-{assessment.assessment_id}.json",
            assessment.model_dump(mode="json"),
        )
    return assessment


def print_safe_pilot_v6_assessment(assessment: PilotV6Assessment) -> None:
    stats = assessment.statistics
    print("PILOT V6 TECHNICAL QUALIFICATION - NOT RESEARCH DATA")
    print(f"verdict={assessment.verdict.value}")
    print(f"final_pair_source={assessment.final_pair_source}")
    print(f"intended_model_ids={assessment.intended_model_ids}")
    print(
        f"cells={stats['present_cells']}/{stats['expected_cells']}; "
        f"completed_conversations={stats['completed_conversations']}/4"
    )
    print(
        f"successful_response_slots={stats['successful_response_slots']}/24; "
        f"missing_response_slots={stats['missing_response_slots']}; "
        f"technical_errors={stats['technical_error_events']}"
    )
    print(f"http_attempts={stats['http_attempts_used']}/32")
    print(f"finish_reasons={stats['finish_reasons']}")
    print(f"providers={stats['providers']}")
    print(f"truncation_count={stats['truncation_count']}")
    print(f"failed_criteria={list(assessment.failed_criteria)}")
    print(f"source_evidence_hash={assessment.source_evidence_hash}")
    if assessment.verdict in {PilotV6Verdict.NOT_CONFIGURED, PilotV6Verdict.NOT_RUN}:
        print("network_requests=0")
