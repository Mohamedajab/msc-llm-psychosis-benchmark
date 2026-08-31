"""Disabled-by-default scaffold for a future independent rubric judge.

This module deliberately performs no provider call.  It freezes the identity-
blind request and strict response contracts so a judge can be added later,
after human annotation exists, without making the Friday demonstration depend
on another model or silently mixing automated and human ratings.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.schemas import AxisScores, ChatMessage, RubricConfig

JUDGE_STATUS = "NOT VALIDATED - DISABLED BY DEFAULT"


class JudgeDisabledError(RuntimeError):
    """Raised when automated judging has not been explicitly enabled."""


class JudgeOutput(BaseModel):
    """Strict machine-readable output; kept separate from human annotations."""

    model_config = ConfigDict(extra="forbid")

    scores: AxisScores
    rationale: dict[str, str] = Field(default_factory=dict)


def judge_enabled() -> bool:
    return os.getenv("ENABLE_LLM_JUDGE", "0").strip() == "1"


def require_judge_configuration(target_model_ids: Sequence[str]) -> str:
    """Return the exact judge slug or fail before any network client is built."""

    if not judge_enabled():
        raise JudgeDisabledError(
            "Automated judging is disabled. Set ENABLE_LLM_JUDGE=1 only for a "
            "separately approved validation exercise."
        )
    judge_model = os.getenv("OPENROUTER_JUDGE_MODEL", "").strip()
    if not judge_model:
        raise JudgeDisabledError("OPENROUTER_JUDGE_MODEL is not configured")
    if judge_model in set(target_model_ids):
        raise JudgeDisabledError("The judge must use a different model family")
    if judge_model in {"openrouter/free", "openrouter/auto"} or "latest" in judge_model:
        raise JudgeDisabledError("The judge requires an exact concrete model slug")
    return judge_model


def build_blinded_judge_messages(
    *,
    conversation_context: Sequence[ChatMessage],
    response_to_score: str,
    rubric: RubricConfig,
) -> tuple[ChatMessage, ...]:
    """Build a rubric request that contains no model or condition identity.

    This is only a serialisable scaffold.  Calling code must store raw judge
    output separately and must never overwrite human annotation events.
    """

    axes = [
        {
            "id": axis.id,
            "name": axis.name,
            "definition": axis.definition,
            "allowed_scores": axis.allowed_scores,
            "allows_na": axis.allows_na,
            "na_guidance": axis.na_guidance,
            "anchors": axis.anchors,
        }
        for axis in rubric.axes
    ]
    instructions = {
        "task": "Score only the supplied assistant response in its prior context.",
        "rubric_version": rubric.version,
        "axes": axes,
        "output_schema": {
            "scores": {
                axis.id: (
                    f"one of {list(axis.allowed_scores)}, or N/A when applicable"
                    if axis.allows_na
                    else f"one of {list(axis.allowed_scores)}"
                )
                for axis in rubric.axes
            },
            "rationale": {axis.id: "short evidence-based explanation" for axis in rubric.axes},
        },
    }
    context = [message.model_dump() for message in conversation_context]
    payload = {
        "conversation_context": context,
        "assistant_response_to_score": response_to_score,
    }
    return (
        ChatMessage(role="system", content=json.dumps(instructions, ensure_ascii=False)),
        ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    )


def parse_judge_output(raw_text: str) -> JudgeOutput:
    """Validate exact JSON; fenced, partial, or prose output is rejected."""

    try:
        parsed = json.loads(raw_text)
        output = JudgeOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"Judge output failed strict schema validation: {error}") from error
    if not output.scores.complete():
        raise ValueError("Judge output must score all seven axes")
    return output


__all__ = [
    "JUDGE_STATUS",
    "JudgeDisabledError",
    "JudgeOutput",
    "build_blinded_judge_messages",
    "judge_enabled",
    "parse_judge_output",
    "require_judge_configuration",
]
