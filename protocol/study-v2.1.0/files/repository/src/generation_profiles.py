"""Versioned, model-agnostic generation profiles for prospective collection."""

from __future__ import annotations

from src.schemas import GenerationConfig

GENERATION_V4_VERSION = "generation-v4"
GENERATION_V4_MAX_COMPLETION_TOKENS = 4096
GENERATION_V4_TIMEOUT_SECONDS = 120
# Generation-v4 deliberately adds no style or length intervention. The experimental
# conversation itself is the target-facing stimulus.
GENERATION_V4_VISIBLE_RESPONSE_INSTRUCTION = None
GENERATION_V4_REASONING_POLICY_VERSION = "reasoning-policy-v1.0.0"


def require_generation_v4(generation: GenerationConfig) -> GenerationConfig:
    """Fail closed unless every prospective generation-v4 field is frozen."""

    reasoning = generation.reasoning_policy
    if (
        generation.version != GENERATION_V4_VERSION
        or generation.temperature != 0.2
        or generation.top_p != 1.0
        or generation.max_tokens != GENERATION_V4_MAX_COMPLETION_TOKENS
        or generation.completion_limit_parameter is not None
        or generation.timeout_seconds != GENERATION_V4_TIMEOUT_SECONDS
        or generation.max_retries != 3
        or generation.visible_response_instruction != GENERATION_V4_VISIBLE_RESPONSE_INSTRUCTION
        or reasoning is None
        or reasoning.version != GENERATION_V4_REASONING_POLICY_VERSION
        or reasoning.reasoning_control_capability != "UNKNOWN"
        or reasoning.reasoning_control_requested != "NATIVE"
        or reasoning.exclude_reasoning_trace is not True
    ):
        raise ValueError("Frozen generation-v4 profile does not match the prospective protocol")
    return generation
