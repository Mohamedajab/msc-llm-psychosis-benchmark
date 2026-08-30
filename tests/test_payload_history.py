"""Exact provider-bound history manipulation tests."""

from pathlib import Path

import pytest

from src.config_loader import (
    configuration_bundle_hash,
    load_histories,
    load_models,
    load_scripts,
)
from src.conversation_runner import ConversationRunner, create_run_header
from src.payloads import build_target_messages
from src.provider_client import DeterministicFixtureProvider
from src.schemas import ContextCondition, GenerationConfig
from src.storage import RawRunStore

ROOT = Path(__file__).parents[1]


def _fixture():
    script = next(
        item
        for item in load_scripts(ROOT / "config" / "scenarios")
        if item.script_id == "monitoring_fixed_belief_v1"
    )
    prefix = next(
        item
        for item in load_histories(ROOT / "config" / "histories")
        if item.history_id == script.history_id
    )
    return script, prefix


def test_no_context_turn_one_contains_only_user_turn_one() -> None:
    script, prefix = _fixture()
    messages = build_target_messages(
        condition=ContextCondition.NO_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=[],
        current_user_message=script.turns[0],
    )
    assert [(item.role, item.content) for item in messages] == [("user", script.turns[0])]


def test_standardised_context_turn_one_is_exact_prefix_then_user() -> None:
    script, prefix = _fixture()
    messages = build_target_messages(
        condition=ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=[],
        current_user_message=script.turns[0],
    )
    assert messages == (
        *prefix.messages,
        type(prefix.messages[0])(role="user", content=script.turns[0]),
    )


def test_turn_two_and_later_contain_complete_ordered_dialogue() -> None:
    script, prefix = _fixture()
    first_response = "Exact assistant response one."
    turn_two = build_target_messages(
        condition=ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=[(script.turns[0], first_response)],
        current_user_message=script.turns[1],
    )
    assert turn_two[-3].content == script.turns[0]
    assert turn_two[-2].content == first_response
    assert turn_two[-1].content == script.turns[1]
    assert turn_two[: len(prefix.messages)] == prefix.messages

    exchanges = [(script.turns[index], f"response-{index + 1}") for index in range(5)]
    turn_six = build_target_messages(
        condition=ContextCondition.NO_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=exchanges,
        current_user_message=script.turns[5],
    )
    assert len(turn_six) == 11
    assert [message.role for message in turn_six] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]


def test_mock_provider_captures_exact_payload_and_is_deterministic() -> None:
    script, prefix = _fixture()
    messages = build_target_messages(
        condition=ContextCondition.NO_PRELOADED_CONTEXT,
        prefix=prefix,
        completed_exchanges=[],
        current_user_message=script.turns[0],
    )
    provider = DeterministicFixtureProvider("safe")
    generation = GenerationConfig(
        version="test",
        temperature=0.2,
        max_tokens=50,
        top_p=1,
        seed=1,
        timeout_seconds=5,
        max_retries=0,
    )
    one = provider.generate(model_id="fixture-safe", messages=messages, generation=generation)
    provider_two = DeterministicFixtureProvider("safe")
    two = provider_two.generate(model_id="fixture-safe", messages=messages, generation=generation)
    assert provider.calls == [messages]
    assert one.text == two.text


@pytest.mark.parametrize("condition", list(ContextCondition))
def test_runner_sends_complete_exact_history_to_provider_each_turn(
    condition: ContextCondition, tmp_path: Path
) -> None:
    script, prefix = _fixture()
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    header = create_run_header(
        study_version="history-boundary-test",
        run_id=f"history-{condition.value}",
        data_status="demo_fixture",
        script=script,
        condition=condition,
        model_slot="fixture_safe",
        model_id="fixture/safe",
        repetition=1,
        generation=models.generation.model_copy(
            update={"completion_limit_parameter": "max_tokens"}
        ),
        configuration_version="test",
        configuration_hash=configuration_bundle_hash(scripts, histories, models),
    )
    provider = DeterministicFixtureProvider("safe")
    record = ConversationRunner(provider, RawRunStore(tmp_path / "raw")).run_or_resume(
        header=header, script=script, prefix=prefix
    )

    contextual_prefix_length = (
        len(prefix.messages) if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT else 0
    )
    prefix_length = contextual_prefix_length
    assert len(provider.calls) == 6
    assert [len(payload) for payload in provider.calls] == [
        prefix_length + (2 * turn_number) - 1 for turn_number in range(1, 7)
    ]
    for index, payload in enumerate(provider.calls):
        assert tuple(payload) == record.turns[index].request_messages
        assert all(message.role != "system" for message in payload)
        assert models.generation.visible_response_instruction is None
        for previous in range(index):
            offset = prefix_length + (2 * previous)
            assert payload[offset].content == script.turns[previous]
            assert payload[offset + 1].content == record.turns[previous].result.text
        assert payload[-1].content == script.turns[index]
