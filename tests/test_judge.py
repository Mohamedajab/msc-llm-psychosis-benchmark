"""The supplementary judge request is identity-blind and schema-strict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config_loader import load_rubric
from src.judge import AXIS_IDS, build_blinded_judge_messages, judge_json_schema, parse_judge_output
from src.schemas import ChatMessage

ROOT = Path(__file__).parents[1]


def valid_output() -> dict[str, object]:
    return {
        "scores": {axis: 0 for axis in AXIS_IDS},
        "rationale": {axis: "Short reason." for axis in AXIS_IDS},
    }


def test_blinded_request_has_no_experiment_identity() -> None:
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    messages = build_blinded_judge_messages(
        conversation_context=(ChatMessage(role="user", content="What could this mean?"),),
        response_to_score="There may be several ordinary explanations.",
        rubric=rubric,
    )
    serialised = "\n".join(message.content for message in messages)
    for hidden in (
        "model_minimax",
        "model_nemotron",
        "openrouter",
        "context_condition",
        "presentation_level",
        "repetition",
        "GMICloud",
        "Nvidia",
    ):
        assert hidden not in serialised


def test_judge_json_is_strict_and_requires_every_axis_and_rationale() -> None:
    valid = valid_output()
    assert parse_judge_output(json.dumps(valid)).scores.complete()
    with pytest.raises(ValueError, match="strict schema"):
        parse_judge_output("not JSON")
    invalid = valid_output()
    invalid["scores"]["A1"] = 3  # type: ignore[index]
    with pytest.raises(ValueError, match="strict schema"):
        parse_judge_output(json.dumps(invalid))
    invalid = valid_output()
    del invalid["rationale"]["C1"]  # type: ignore[index]
    with pytest.raises(ValueError, match="strict schema"):
        parse_judge_output(json.dumps(invalid))


def test_json_schema_has_exact_frozen_axes() -> None:
    schema = judge_json_schema()
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert set(properties["scores"]["required"]) == set(AXIS_IDS)
    assert set(properties["rationale"]["required"]) == set(AXIS_IDS)
