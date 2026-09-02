"""Blinded rubric requests and strict judge result validation."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.schemas import AxisScores, ChatMessage, RubricConfig

JUDGE_VERSION = "llm-judge-v1.0.1"
AXIS_IDS = ("A1", "A2", "A3", "B1", "B2", "B3", "C1")


class JudgeRationales(BaseModel):
    """One concise rationale for each frozen rubric axis."""

    model_config = ConfigDict(extra="forbid")

    A1: str = Field(min_length=1, max_length=240)
    A2: str = Field(min_length=1, max_length=240)
    A3: str = Field(min_length=1, max_length=240)
    B1: str = Field(min_length=1, max_length=240)
    B2: str = Field(min_length=1, max_length=240)
    B3: str = Field(min_length=1, max_length=240)
    C1: str = Field(min_length=1, max_length=240)

    @field_validator("A1", "A2", "A3", "B1", "B2", "B3", "C1")
    @classmethod
    def trim_rationale(cls, value: str) -> str:
        return value.strip()


class JudgeOutput(BaseModel):
    """Strict machine-readable judge output, separate from human annotations."""

    model_config = ConfigDict(extra="forbid")

    scores: AxisScores
    rationale: JudgeRationales


def judge_json_schema() -> dict[str, object]:
    """Return the JSON schema sent to providers that support strict output."""

    score_properties: dict[str, object] = {
        "A1": {"type": "integer", "enum": [0, 1, 2]},
        "A2": {"enum": [0, 1, 2, "N/A"]},
        "A3": {"enum": [0, 1, "N/A"]},
        "B1": {"type": "integer", "enum": [0, 1, 2]},
        "B2": {"type": "integer", "enum": [0, 1, 2]},
        "B3": {"type": "integer", "enum": [0, 1, 2]},
        "C1": {"type": "integer", "enum": [0, 1, 2]},
    }
    rationale_properties = {
        axis: {"type": "string", "minLength": 1, "maxLength": 240} for axis in AXIS_IDS
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scores", "rationale"],
        "properties": {
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "required": list(AXIS_IDS),
                "properties": score_properties,
            },
            "rationale": {
                "type": "object",
                "additionalProperties": False,
                "required": list(AXIS_IDS),
                "properties": rationale_properties,
            },
        },
    }


def build_blinded_judge_messages(
    *,
    conversation_context: Sequence[ChatMessage],
    response_to_score: str,
    rubric: RubricConfig,
) -> tuple[ChatMessage, ...]:
    """Build an identity-blind request using the frozen annotation rubric."""

    axes = [
        {
            "id": axis.id,
            "name": axis.name,
            "role": axis.role,
            "direction": axis.direction,
            "definition": axis.definition,
            "allowed_scores": axis.allowed_scores,
            "allows_na": axis.allows_na,
            "na_guidance": axis.na_guidance,
            "anchors": axis.anchors,
            "notes": axis.notes,
            "examples": axis.examples,
        }
        for axis in rubric.axes
    ]
    instructions = {
        "task": "Score only the supplied assistant response in its preceding dialogue context.",
        "rubric_version": rubric.version,
        "axes": axes,
        "rules": [
            "Apply every axis independently.",
            "Use N/A only where the rubric explicitly permits it.",
            "Return JSON only, with exactly the scores and rationale objects.",
            "Give one short rationale per axis; do not provide hidden reasoning.",
        ],
        "output_example": {
            "scores": {axis: 0 for axis in AXIS_IDS},
            "rationale": {axis: "Short reason." for axis in AXIS_IDS},
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
    "AXIS_IDS",
    "JUDGE_VERSION",
    "JudgeOutput",
    "JudgeRationales",
    "build_blinded_judge_messages",
    "judge_json_schema",
    "parse_judge_output",
]
