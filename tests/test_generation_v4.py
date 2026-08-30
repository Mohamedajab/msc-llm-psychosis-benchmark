"""Prospective generation-v4 protocol and historical compatibility tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import audit_generation_budget
from src.config_loader import load_histories, load_models, load_scripts
from src.generation_budget import audit_generation_budget as build_budget_audit
from src.generation_profiles import (
    GENERATION_V4_MAX_COMPLETION_TOKENS,
    GENERATION_V4_VERSION,
    GENERATION_V4_VISIBLE_RESPONSE_INSTRUCTION,
    require_generation_v4,
)
from src.payloads import FORBIDDEN_TARGET_TERMS, build_target_messages
from src.pilot_qualification import assess_pilot_v5
from src.replacement_screening import GENERATION_VERSION as SCREEN_GENERATION_VERSION
from src.schemas import (
    ContextCondition,
    GenerationConfig,
    ObservationStatus,
    ProviderResult,
    ReasoningPolicyConfig,
)

ROOT = Path(__file__).parents[1]
ARCHIVED_V3_SHA256 = "0289108e98dafaf7d3f2af4de9f6d1533fe1d5f6700662f739aab1c00201e957"
PILOT_V5_SOURCE_HASH = "4b8fed25b622c7cdbabd4483e0484ea9587e7bebfea7ad18deee5386c11647d0"


def test_generation_v3_archive_is_unchanged_and_loadable() -> None:
    path = ROOT / "config" / "archive" / "models-study-v2-generation-v3-nemotron.yaml"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ARCHIVED_V3_SHA256
    archived = load_models(path)
    assert archived.version == "2.1.0"
    assert archived.generation.version == "generation-v3"
    assert archived.generation.max_tokens == 1024
    assert archived.generation.visible_response_instruction is None
    assert archived.generation.reasoning_policy is None
    assert archived.generation.request_parameters()["max_tokens"] == 1024


def test_active_generation_v4_profile_is_complete_and_machine_readable() -> None:
    models = load_models(ROOT / "config" / "models.yaml")
    generation = require_generation_v4(models.generation)
    assert generation.version == GENERATION_V4_VERSION
    assert generation.max_tokens == GENERATION_V4_MAX_COMPLETION_TOKENS == 4096
    assert generation.visible_response_instruction == GENERATION_V4_VISIBLE_RESPONSE_INSTRUCTION
    assert generation.reasoning_policy.reasoning_control_capability == "UNKNOWN"
    assert generation.reasoning_policy.reasoning_control_requested == "NATIVE"
    assert generation.timeout_seconds == 120
    assert generation.completion_limit_parameter is None
    assert {slot.completion_limit_parameter for slot in models.model_slots.values()} == {
        "max_tokens"
    }
    parameters = generation.request_parameters(completion_limit_parameter="max_tokens")
    assert parameters["reasoning"] == {"exclude": True}
    assert parameters["max_tokens"] == 4096


def test_unsupported_explicit_reasoning_control_cannot_pretend_to_apply() -> None:
    with pytest.raises(ValueError, match="requires verified support"):
        ReasoningPolicyConfig(
            version="test",
            reasoning_control_capability="UNSUPPORTED",
            reasoning_control_requested="DISABLED",
        )


def test_generation_v4_adds_no_visible_response_style_instruction() -> None:
    models = load_models(ROOT / "config" / "models.yaml")
    script = load_scripts(ROOT / "config" / "scenarios")[0]
    prefix = next(
        value
        for value in load_histories(ROOT / "config" / "histories")
        if value.history_id == script.history_id
    )
    messages = build_target_messages(
        condition=ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=[],
        current_user_message=script.turns[0],
        visible_response_instruction=models.generation.visible_response_instruction,
    )
    assert GENERATION_V4_VISIBLE_RESPONSE_INSTRUCTION is None
    assert models.generation.visible_response_instruction is None
    assert messages[: len(prefix.messages)] == prefix.messages
    assert all(message.content.strip() for message in messages)
    assert all(
        term not in message.content.casefold()
        for message in messages
        for term in FORBIDDEN_TARGET_TERMS
    )


def test_technical_truncation_is_preserved_as_a_response_outcome() -> None:
    result = ProviderResult(
        status=ObservationStatus.RESPONSE,
        text="A visible but incomplete benchmark response",
        requested_model_id="example/model:free",
        resolved_model_id="example/model:free",
        provider_name="Example",
        finish_reason="length",
        latency_ms=1,
        retry_count=0,
    )
    assert result.truncated is True
    assert result.visible_word_count == 6


def test_old_provider_result_without_new_telemetry_remains_loadable() -> None:
    old = {
        "status": "response",
        "text": "Legacy visible response.",
        "requested_model_id": "example/model:free",
        "resolved_model_id": "example/model:free",
        "provider_name": "Example",
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "latency_ms": 1,
        "retry_count": 0,
    }
    result = ProviderResult.model_validate(old)
    assert result.usage.reasoning_tokens is None
    assert result.usage.visible_completion_tokens is None
    assert result.visible_character_count == len(old["text"])


def test_pilot_v5_stays_failed_under_its_archived_configuration() -> None:
    if not any((ROOT / "data" / "raw" / "runs").glob("technical-pilot-v5_*")):
        pytest.skip("Pilot V5 raw evidence is deliberately excluded from a fresh clone")
    assessment = assess_pilot_v5(output_root=ROOT / "data" / "raw" / "runs", persist=False)
    assert assessment.verdict.value == "FAIL"
    assert assessment.source_evidence_hash == PILOT_V5_SOURCE_HASH
    assert assessment.statistics["truncation_count"] == 11


def test_generation_budget_audit_is_content_free_and_non_mutating(capsys) -> None:  # noqa: ANN001
    if not any((ROOT / "data" / "raw" / "runs").glob("technical-pilot-v5_*")):
        pytest.skip("Pilot V4/V5 raw evidence is deliberately excluded from a fresh clone")
    audit = build_budget_audit(ROOT / "data" / "raw" / "runs")
    assert audit.reasoning_contribution == "INCONCLUSIVE"
    assert all(
        row["reasoning_usage_reporting_status"] == "NOT_REPORTED"
        for pilot in audit.pilots.values()
        for row in pilot["rows"]
    )
    before = sorted((ROOT / "data" / "raw").rglob("*.json"))
    assert audit_generation_budget.main(["--no-persist"]) == 0
    after = sorted((ROOT / "data" / "raw").rglob("*.json"))
    assert before == after
    output = capsys.readouterr().out
    assert "request_messages" not in output
    assert "request_payload" not in output
    assert "substantive_content_printed=no" in output


def test_prospective_screen_and_pilot_use_generation_v4() -> None:
    from src.pilot_v6 import GENERATION_VERSION as PILOT_V6_GENERATION_VERSION

    assert SCREEN_GENERATION_VERSION == GENERATION_V4_VERSION
    assert PILOT_V6_GENERATION_VERSION == GENERATION_V4_VERSION


def test_generation_v4_rejects_parameter_drift() -> None:
    models = load_models(ROOT / "config" / "models.yaml")
    drifted = models.generation.model_copy(update={"max_tokens": 2048})
    with pytest.raises(ValueError, match="does not match"):
        require_generation_v4(drifted)


def test_reasoning_text_cannot_be_a_chat_message_side_channel() -> None:
    generation = GenerationConfig(
        version="test",
        temperature=0.2,
        max_tokens=10,
        top_p=1,
        timeout_seconds=1,
        max_retries=0,
    )
    assert "reasoning" not in generation.request_parameters()
