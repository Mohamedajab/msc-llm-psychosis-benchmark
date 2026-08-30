"""Write the compact raw/derived data dictionary used in meeting materials."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[1]
ROWS = [
    ("manifest", "run_id", "string", "Stable unique conversation-run identifier"),
    ("manifest", "script_id", "string", "Frozen six-turn script identifier"),
    ("manifest", "theme", "enum", "monitoring, personal_messages, or ai_relationship"),
    (
        "manifest",
        "presentation_level",
        "enum",
        "control, ambiguous, or fixed_belief; hidden from target",
    ),
    ("manifest", "model_slot", "string", "Configuration-defined target-model slot"),
    ("manifest", "requested_model_id", "string", "Exact configured OpenRouter slug"),
    (
        "manifest",
        "context_condition",
        "enum",
        "no_preloaded_context or standardised_preloaded_context",
    ),
    ("manifest", "repetition", "integer", "Planned repetition 1 or 2"),
    ("manifest", "execution_order", "integer", "Seeded randomised planned order"),
    (
        "raw_run",
        "configuration_hash",
        "sha256",
        "Canonical content hash of frozen configuration bundle",
    ),
    ("raw_run", "provider_endpoint", "string|null", "Frozen provider endpoint for real calls"),
    (
        "raw_run",
        "generation_config.visible_response_instruction",
        "string|null",
        "Versioned common visible-response contract; null for historical profiles",
    ),
    (
        "raw_run",
        "generation_config.reasoning_policy",
        "object|null",
        "Requested reasoning capability/control policy; null for historical profiles",
    ),
    ("raw_turn", "request_model_id", "string", "Exact model slug sent for this request"),
    ("raw_turn", "request_messages", "array", "Exact ordered messages sent for that generation"),
    (
        "raw_turn",
        "request_payload_hash",
        "sha256",
        "Hash of exact messages and generation parameters",
    ),
    (
        "raw_turn",
        "result.text",
        "string|null",
        "Raw textual model response; null for error/missing observation",
    ),
    (
        "raw_turn",
        "result.status",
        "enum",
        "response or typed transport/provider/rate/block/missing state",
    ),
    ("raw_turn", "result.usage", "object|null", "Provider token usage when returned"),
    ("raw_turn", "result.usage.prompt_tokens", "integer|null", "Reported input-token usage"),
    (
        "raw_turn",
        "result.usage.completion_tokens",
        "integer|null",
        "Reported combined completion-token usage",
    ),
    (
        "raw_turn",
        "result.usage.reasoning_tokens",
        "integer|null",
        "Reported reasoning tokens; never inferred from completion usage",
    ),
    (
        "raw_turn",
        "result.usage.visible_completion_tokens",
        "integer|null",
        "Separately reported visible tokens; null when unavailable",
    ),
    (
        "raw_turn",
        "result.usage.cached_prompt_tokens",
        "integer|null",
        "Reported cached input tokens when available",
    ),
    (
        "raw_turn",
        "result.resolved_model_id",
        "string|null",
        "Exact returned model ID when supplied",
    ),
    ("raw_turn", "result.provider_name", "string|null", "Resolved provider when supplied"),
    ("raw_turn", "result.finish_reason", "string|null", "Provider completion reason"),
    (
        "raw_turn",
        "result.truncated",
        "boolean",
        "Derived true exactly when finish_reason is length",
    ),
    ("raw_turn", "result.retry_count", "integer", "Retries before final observation"),
    (
        "raw_turn",
        "result.http_attempts",
        "integer|null",
        "HTTP POST attempts represented by this event; zero for a request blocked before POST",
    ),
    ("raw_turn", "result.http_status", "integer|null", "Final HTTP status when available"),
    ("raw_turn", "result.error_type", "string|null", "Typed provider or transport error"),
    (
        "raw_turn",
        "result.visible_character_count",
        "integer|null",
        "Deterministic character count of user-visible response text",
    ),
    (
        "raw_turn",
        "result.visible_word_count",
        "integer|null",
        "Deterministic word count of user-visible response text",
    ),
    (
        "raw_turn",
        "result.visible_sentence_count",
        "integer|null",
        "Deterministic sentence count of user-visible response text",
    ),
    (
        "raw_turn",
        "result.reasoning_control_applied",
        "string|null",
        "Safe provider-reporting status; does not contain reasoning text",
    ),
    (
        "annotation",
        "blinded_item_id",
        "string",
        "Annotator-facing ID with experimental factors removed",
    ),
    ("annotation", "A1..C1", "integer|null", "Seven separate draft rubric axes, each 0-2"),
    ("annotation", "uncertain_adjudication_needed", "boolean", "Annotator uncertainty flag"),
    ("annotation", "source_response_hash", "sha256", "Hash binding rating to exact response"),
    (
        "annotation_preparation",
        "primary_scorability",
        "derived enum",
        "complete_pre_truncation, truncated, or downstream_of_truncation",
    ),
    ("nlp", "*_density", "float", "Exploratory lexicon matches per response word"),
    (
        "trajectory",
        "first_A1_2_turn",
        "integer|null",
        "First high-confirmation onset at conversation level",
    ),
]


def main() -> None:
    output = ROOT / "outputs" / "data_dictionary.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ROWS, columns=["table", "field", "type", "description"]).to_csv(
        output, index=False, lineterminator="\n"
    )
    print(output)


if __name__ == "__main__":
    main()
