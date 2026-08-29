"""Pure construction and validation of exact target-model message payloads."""

from __future__ import annotations

from collections.abc import Sequence

from src.schemas import ChatMessage, ContextCondition, HistoryPrefix

FORBIDDEN_TARGET_TERMS = (
    "you are being evaluated",
    "research benchmark",
    "respond safely",
    "psychosis-related",
    "delusional",
    "vulnerable persona",
    "presentation_level",
    "fixed_belief",
    "scoring rubric",
    "delusion confirmation",
    "harm enablement",
    "safety intervention",
)


def build_target_messages(
    *,
    condition: ContextCondition,
    prefix: HistoryPrefix | None,
    completed_exchanges: Sequence[tuple[str, str]],
    current_user_message: str,
) -> tuple[ChatMessage, ...]:
    """Return prefix + complete live dialogue + current user, with no system cue."""
    if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT and prefix is None:
        raise ValueError("The standardised context condition requires its frozen prefix")
    messages: list[ChatMessage] = []
    if condition == ContextCondition.STANDARDISED_PRELOADED_CONTEXT:
        messages.extend(prefix.messages)  # type: ignore[union-attr]
    for user_message, assistant_response in completed_exchanges:
        messages.extend(
            (
                ChatMessage(role="user", content=user_message),
                ChatMessage(role="assistant", content=assistant_response),
            )
        )
    messages.append(ChatMessage(role="user", content=current_user_message))
    assert_target_payload_clean(messages)
    return tuple(messages)


def assert_target_payload_clean(messages: Sequence[ChatMessage]) -> None:
    """Fail closed if hidden experiment metadata leaks into a target request."""
    if any(message.role == "system" for message in messages):
        raise ValueError("Target requests must not contain a system message in protocol v1")
    joined = "\n".join(message.content for message in messages).casefold()
    leaked = [term for term in FORBIDDEN_TARGET_TERMS if term in joined]
    if leaked:
        raise ValueError(f"Target request contains forbidden experimental cue(s): {leaked}")
