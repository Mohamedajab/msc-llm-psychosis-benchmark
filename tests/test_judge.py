"""The optional judge scaffold is inert, identity-blind, and strict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config_loader import load_rubric
from src.judge import (
    JudgeDisabledError,
    build_blinded_judge_messages,
    parse_judge_output,
    require_judge_configuration,
)
from src.schemas import ChatMessage

ROOT = Path(__file__).parents[1]


def test_judge_is_disabled_without_explicit_switch(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_LLM_JUDGE", raising=False)
    monkeypatch.setenv("OPENROUTER_JUDGE_MODEL", "different/judge:free")
    with pytest.raises(JudgeDisabledError, match="disabled"):
        require_judge_configuration(["target/a:free", "target/b:free"])


def test_blinded_request_has_no_experiment_identity() -> None:
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    messages = build_blinded_judge_messages(
        conversation_context=(ChatMessage(role="user", content="What could this mean?"),),
        response_to_score="There may be several ordinary explanations.",
        rubric=rubric,
    )
    serialised = "\n".join(message.content for message in messages)
    for hidden in ("model_a", "model_b", "openrouter", "context_condition", "repetition"):
        assert hidden not in serialised


def test_judge_json_is_strict_and_requires_every_axis() -> None:
    valid = {
        "scores": {axis: 0 for axis in ("A1", "A2", "A3", "B1", "B2", "B3", "C1")},
        "rationale": {},
    }
    assert parse_judge_output(json.dumps(valid)).scores.complete()
    with pytest.raises(ValueError, match="strict schema"):
        parse_judge_output("not JSON")
    valid["scores"]["A1"] = 3
    with pytest.raises(ValueError, match="strict schema"):
        parse_judge_output(json.dumps(valid))
