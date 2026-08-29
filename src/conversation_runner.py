"""Dry-run, execute, and resume exact six-turn conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from src.config_loader import canonical_hash
from src.payloads import build_target_messages
from src.provider_client import TargetProvider
from src.schemas import (
    ContextCondition,
    ErrorEvent,
    GenerationConfig,
    HistoryPrefix,
    ObservationStatus,
    RunHeader,
    ScriptConfig,
    TurnEvent,
)
from src.storage import RawRunStore, atomic_write_json


def utc_now() -> datetime:
    return datetime.now(UTC)


def payload_hash(*, model_id: str, messages: tuple, parameters: dict, stream: bool = False) -> str:
    value = {
        "model": model_id,
        "messages": [message.model_dump(mode="json") for message in messages],
        "parameters": parameters,
        "stream": stream,
    }
    return canonical_hash(value)


def create_run_header(
    *,
    study_version: str,
    run_id: str,
    data_status: Literal[
        "demo_fixture", "technical_pilot", "planned_study", "main_study"
    ],
    script: ScriptConfig,
    condition: ContextCondition,
    model_slot: str,
    model_id: str,
    repetition: int,
    generation: GenerationConfig,
    configuration_version: str,
    configuration_hash: str,
) -> RunHeader:
    return RunHeader(
        study_version=study_version,
        run_id=run_id,
        data_status=data_status,
        script_id=script.script_id,
        script_version=script.script_version,
        theme=script.theme,
        presentation_level=script.presentation_level,
        context_condition=condition,
        history_id=(
            script.history_id
            if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT
            else None
        ),
        model_slot=model_slot,
        requested_model_id=model_id,
        provider=("deterministic_fixture" if data_status == "demo_fixture" else "openrouter"),
        provider_endpoint=(
            None
            if data_status == "demo_fixture"
            else "https://openrouter.ai/api/v1/chat/completions"
        ),
        repetition=repetition,
        generation_config=generation,
        configuration_version=configuration_version,
        configuration_hash=configuration_hash,
        created_at=utc_now(),
    )


class ConversationRunner:
    """Execute from the first missing turn while preserving all successful evidence."""

    def __init__(self, provider: TargetProvider, store: RawRunStore) -> None:
        self.provider = provider
        self.store = store

    def dry_run(
        self,
        *,
        header: RunHeader,
        script: ScriptConfig,
        prefix: HistoryPrefix,
        destination: str | Path | None = None,
        placeholder_responses: tuple[str, ...] | None = None,
    ) -> list[dict]:
        """Build six auditable payloads without calling the provider."""
        responses = placeholder_responses or tuple(
            f"<assistant response {turn}>" for turn in range(1, 7)
        )
        if len(responses) != 6:
            raise ValueError("Dry-run placeholder responses must contain six entries")
        exchanges: list[tuple[str, str]] = []
        payloads: list[dict] = []
        parameters = header.generation_config.request_parameters()
        for turn_number, user_message in enumerate(script.turns, start=1):
            messages = build_target_messages(
                condition=header.context_condition,
                prefix=prefix,
                completed_exchanges=exchanges,
                current_user_message=user_message,
            )
            payloads.append(
                {
                    "run_id": header.run_id,
                    "turn_number": turn_number,
                    "requested_model_id": header.requested_model_id,
                    "messages": [message.model_dump() for message in messages],
                    "parameters": parameters,
                    "payload_hash": payload_hash(
                        model_id=header.requested_model_id,
                        messages=messages,
                        parameters=parameters,
                    ),
                    "network_called": False,
                }
            )
            exchanges.append((user_message, responses[turn_number - 1]))
        if destination is not None:
            atomic_write_json(Path(destination), payloads)
        return payloads

    def run_or_resume(
        self,
        *,
        header: RunHeader,
        script: ScriptConfig,
        prefix: HistoryPrefix,
    ):
        self._validate_inputs(header, script, prefix)
        self.store.initialise(header)
        previous = self.store.successful_turns(header.run_id)
        if len(previous) == 6:
            return self.store.load(header.run_id)
        exchanges = [(event.user_message, event.result.text or "") for event in previous]
        for turn_number in range(len(previous) + 1, 7):
            user_message = script.turns[turn_number - 1]
            messages = build_target_messages(
                condition=header.context_condition,
                prefix=prefix,
                completed_exchanges=exchanges,
                current_user_message=user_message,
            )
            parameters = header.generation_config.request_parameters()
            request_time = utc_now()
            result = self.provider.generate(
                model_id=header.requested_model_id,
                messages=messages,
                generation=header.generation_config,
            )
            response_time = utc_now()
            digest = payload_hash(
                model_id=header.requested_model_id,
                messages=messages,
                parameters=parameters,
            )
            if result.status != ObservationStatus.RESPONSE:
                error_event = ErrorEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=header.run_id,
                    turn_number=turn_number,
                    timestamp=response_time,
                    request_model_id=header.requested_model_id,
                    request_messages=messages,
                    request_parameters=parameters,
                    request_payload_hash=digest,
                    result=result,
                )
                self.store.append_error(error_event)
                return self.store.load(header.run_id)
            event = TurnEvent(
                event_id=uuid.uuid4().hex,
                run_id=header.run_id,
                turn_number=turn_number,
                request_timestamp=request_time,
                response_timestamp=response_time,
                request_model_id=header.requested_model_id,
                request_messages=messages,
                request_parameters=parameters,
                request_payload_hash=digest,
                user_message=user_message,
                result=result,
            )
            self.store.append_success(event)
            exchanges.append((user_message, result.text or ""))
        return self.store.load(header.run_id)

    @staticmethod
    def _validate_inputs(header: RunHeader, script: ScriptConfig, prefix: HistoryPrefix) -> None:
        if header.script_id != script.script_id:
            raise ValueError("Run header script does not match requested script")
        if prefix.history_id != script.history_id or prefix.theme != script.theme:
            raise ValueError("Frozen prefix does not match the script theme/history ID")
        if (
            header.context_condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT
            and header.history_id != prefix.history_id
        ):
            raise ValueError("Run header does not identify the exact standardised prefix")
