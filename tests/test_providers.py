"""OpenRouter response parsing, retry, and credential-safety tests."""

import json

import httpx
import pytest

from src.provider_client import OpenRouterProvider, qualify_catalogue_entry
from src.schemas import (
    ChatMessage,
    GenerationConfig,
    ObservationStatus,
    ReasoningPolicyConfig,
)

GENERATION = GenerationConfig(
    version="test",
    temperature=0.2,
    max_tokens=100,
    top_p=1,
    seed=7,
    timeout_seconds=2,
    max_retries=2,
)
MESSAGES = [ChatMessage(role="user", content="Synthetic ordinary question.")]


def test_catalogue_can_require_generation_v4_envelope_and_parameter() -> None:
    model_id = "example/model:free"
    entry = {
        "id": model_id,
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["seed", "max_tokens"],
        "context_length": 65_536,
        "top_provider": {"max_completion_tokens": 4096},
    }
    result = qualify_catalogue_entry(
        model_id,
        entry,
        minimum_context_tokens=8192,
        required_completion_tokens=4096,
        completion_limit_parameter="max_tokens",
    )
    assert result["required_completion_tokens"] == 4096
    with pytest.raises(RuntimeError, match="completion-token envelope"):
        qualify_catalogue_entry(
            model_id,
            {**entry, "top_provider": {"max_completion_tokens": 2048}},
            minimum_context_tokens=8192,
            required_completion_tokens=4096,
            completion_limit_parameter="max_tokens",
        )


def test_openrouter_success_captures_provenance_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-test-key"
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "user", "content": MESSAGES[0].content}]
        return httpx.Response(
            200,
            headers={"x-request-id": "request-123"},
            json={
                "id": "generation-123",
                "model": "openai/gpt-oss-20b:free",
                "provider": "ExampleProvider",
                "created": 1,
                "choices": [
                    {"message": {"content": "A textual response."}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )

    provider = OpenRouterProvider(
        api_key="secret-test-key", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert result.status == ObservationStatus.RESPONSE
    assert result.generation_id == "generation-123"
    assert result.request_id == "request-123"
    assert result.usage.total_tokens == 14
    assert "secret-test-key" not in result.model_dump_json()


def test_reasoning_usage_and_visible_length_are_separate_without_content_leakage() -> None:
    hidden = "private reasoning that must never enter assistant text"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["reasoning"] == {"exclude": True}
        assert body["max_tokens"] == 4096
        return httpx.Response(
            200,
            json={
                "model": "example/reasoning:free",
                "provider": "ExampleProvider",
                "choices": [
                    {
                        "message": {
                            "content": "Visible answer. It has two sentences.",
                            "reasoning": hidden,
                            "reasoning_details": [{"type": "reasoning.text", "text": hidden}],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 15,
                    "total_tokens": 25,
                    "completion_tokens_details": {"reasoning_tokens": 7},
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
        )

    generation = GenerationConfig(
        version="generation-v4",
        temperature=0.2,
        max_tokens=4096,
        top_p=1.0,
        seed=7,
        timeout_seconds=2,
        max_retries=0,
        reasoning_policy=ReasoningPolicyConfig(
            version="reasoning-policy-v1.0.0",
            reasoning_control_capability="UNKNOWN",
            reasoning_control_requested="NATIVE",
        ),
    )
    result = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    ).generate(model_id="example/reasoning:free", messages=MESSAGES, generation=generation)
    assert result.text == "Visible answer. It has two sentences."
    assert hidden not in result.text
    assert hidden not in result.model_dump_json()
    assert result.usage.reasoning_tokens == 7
    assert result.usage.visible_completion_tokens is None
    assert result.usage.cached_prompt_tokens == 3
    assert result.visible_character_count == len(result.text)
    assert result.visible_word_count == 6
    assert result.visible_sentence_count == 2
    assert result.response_metadata["reasoning_present"] is True
    assert result.response_metadata["reasoning_length"] == len(hidden)


def test_reasoning_disabled_shape_and_missing_usage_remains_null() -> None:
    generation = GENERATION.model_copy(
        update={
            "reasoning_policy": ReasoningPolicyConfig(
                version="test-reasoning",
                reasoning_control_capability="SUPPORTED",
                reasoning_control_requested="DISABLED",
            )
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["reasoning"] == {"exclude": True, "effort": "none"}
        return httpx.Response(
            200,
            json={
                "model": "example/reasoning:free",
                "choices": [{"message": {"content": "Visible only."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    result = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    ).generate(model_id="example/reasoning:free", messages=MESSAGES, generation=generation)
    assert result.usage.reasoning_tokens is None
    assert result.usage.visible_completion_tokens is None
    assert result.reasoning_control_applied is None


def test_rate_limit_honours_retry_after_and_is_bounded() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        if calls < 3:
            return httpx.Response(
                429, headers={"retry-after": "3"}, json={"error": {"message": "wait"}}
            )
        return httpx.Response(
            200,
            json={
                "id": "gen",
                "model": "openai/gpt-oss-20b:free",
                "choices": [{"message": {"content": "Recovered."}, "finish_reason": "stop"}],
            },
        )

    provider = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert result.status == ObservationStatus.RESPONSE
    assert result.retry_count == 2
    assert calls == 3
    assert sleeps == [3.0, 3.0]


def test_rate_limit_can_stop_without_immediate_retry() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(429, json={"error": {"message": "wait"}})

    provider = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=sleeps.append
    )
    provider.set_retry_rate_limits(False)
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )

    assert result.status == ObservationStatus.RATE_LIMITED
    assert result.retry_count == 0
    assert calls == 1
    assert sleeps == []


def test_request_starts_are_paced_without_real_sleep() -> None:
    clock = [0.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    provider = OpenRouterProvider(
        api_key="secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b:free",
                    "choices": [{"message": {"content": "Done."}, "finish_reason": "stop"}],
                },
            )
        ),
        sleep=fake_sleep,
        monotonic=lambda: clock[0],
    )
    provider.set_minimum_request_interval(5.0)

    for _ in range(2):
        provider.generate(
            model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
        )

    assert sleeps == [5.0]


def test_invalid_request_and_embedded_error_are_not_responses_or_retried() -> None:
    calls = 0

    def invalid(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(400, json={"error": {"message": "invalid"}})

    provider = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(invalid), sleep=lambda _: None
    )
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert result.status == ObservationStatus.BLOCKED
    assert calls == 1

    embedded = OpenRouterProvider(
        api_key="secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"error": {"message": "upstream failed"}})
        ),
        sleep=lambda _: None,
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
    assert embedded.status == ObservationStatus.PROVIDER_ERROR
    assert embedded.text is None


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, ObservationStatus.PROVIDER_ERROR),
        (402, ObservationStatus.PROVIDER_ERROR),
        (403, ObservationStatus.BLOCKED),
        (404, ObservationStatus.PROVIDER_ERROR),
        (422, ObservationStatus.BLOCKED),
    ],
)
def test_non_retryable_http_errors_are_called_once(status_code, expected) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(status_code, json={"error": {"message": "rejected"}})

    result = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
    assert result.status == expected
    assert result.http_status == status_code
    assert calls == 1


def test_transient_http_error_retries_and_transport_failure_is_typed() -> None:
    calls = 0

    def transient(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        if calls == 1:
            return httpx.Response(502, json={"error": {"message": "upstream"}})
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-20b:free",
                "choices": [{"message": {"content": "Recovered."}, "finish_reason": "stop"}],
            },
        )

    recovered = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(transient), sleep=lambda _: None
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
    assert recovered.status == ObservationStatus.RESPONSE
    assert recovered.retry_count == 1
    assert calls == 2

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    failure = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(timeout), sleep=lambda _: None
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
    assert failure.status == ObservationStatus.TRANSPORT_ERROR
    assert failure.retry_count == GENERATION.max_retries


def test_refusal_is_a_response_but_choice_error_and_empty_text_are_not() -> None:
    refusal = OpenRouterProvider(
        api_key="secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b:free",
                    "choices": [
                        {
                            "message": {"content": "I cannot help with that action."},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        ),
        sleep=lambda _: None,
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
    assert refusal.status == ObservationStatus.RESPONSE

    for body in (
        {
            "model": "openai/gpt-oss-20b:free",
            "choices": [{"message": {"content": "partial"}, "finish_reason": "error"}],
        },
        {
            "model": "openai/gpt-oss-20b:free",
            "choices": [{"message": {"content": "  "}, "finish_reason": "stop"}],
        },
    ):
        result = OpenRouterProvider(
            api_key="secret",
            transport=httpx.MockTransport(
                lambda request, value=body: httpx.Response(200, json=value)
            ),
            sleep=lambda _: None,
        ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)
        assert result.status == ObservationStatus.PROVIDER_ERROR
        assert result.text is None


def test_empty_response_stores_structure_not_hidden_reasoning() -> None:
    hidden = "private chain of thought"
    result = OpenRouterProvider(
        api_key="secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b:free",
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning": hidden,
                                "reasoning_details": [{"type": "reasoning.text"}],
                            },
                            "finish_reason": "length",
                        }
                    ],
                },
            )
        ),
        sleep=lambda _: None,
    ).generate(model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION)

    assert result.error_type == "empty_response"
    assert result.text is None
    assert result.response_metadata == {
        "choice_count": 1,
        "finish_reason": "length",
        "content_present": False,
        "reasoning_present": True,
        "reasoning_length": len(hidden),
        "reasoning_details_present": True,
        "reasoning_details_count": 1,
    }
    assert hidden not in result.model_dump_json()


def test_catalogue_preflight_requires_exact_configured_slug() -> None:
    provider = OpenRouterProvider(
        api_key="secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-20b:free"}]})
        ),
    )
    provider.validate_exact_model("openai/gpt-oss-20b:free")
    with pytest.raises(RuntimeError, match="no substitute"):
        provider.validate_exact_model("missing/model:free")


def test_catalogue_preflight_checks_multiple_exact_slugs_in_one_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": f"example/model-{letter}:free"} for letter in "abc"]},
        )

    provider = OpenRouterProvider(api_key="secret", transport=httpx.MockTransport(handler))
    provider.validate_exact_models(tuple(f"example/model-{letter}:free" for letter in "abc"))
    assert len(requests) == 1
    assert requests[0].method == "GET"


def test_shared_request_budget_counts_retries_and_blocks_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(503, json={"error": {"message": "retry"}})

    provider = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    provider.set_request_attempt_budget(2)
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert result.error_type == "request_budget_exhausted"
    assert result.http_attempts == 2
    assert calls == 2
    assert provider.request_attempt_count == 2

    again = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert again.error_type == "request_budget_exhausted"
    assert again.http_attempts == 0
    assert calls == 2


def test_hard_48_attempt_budget_never_sends_attempt_49() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(503, json={"error": {"message": "retry"}})

    provider = OpenRouterProvider(
        api_key="secret", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    provider.set_request_attempt_budget(48)
    for _ in range(16):
        result = provider.generate(
            model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
        )
        assert result.error_type == "http_503"

    blocked = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert blocked.error_type == "request_budget_exhausted"
    assert calls == 48
    assert provider.request_attempt_count == 48


def test_resolved_model_mismatch_is_rejected_and_secret_redacted() -> None:
    key = "secret-unique-marker"
    provider = OpenRouterProvider(
        api_key=key,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "different/model",
                    "choices": [
                        {"message": {"content": "Wrong model response."}, "finish_reason": "stop"}
                    ],
                },
            )
        ),
        sleep=lambda _: None,
    )
    result = provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert result.status == ObservationStatus.PROVIDER_ERROR
    assert result.error_type == "resolved_model_mismatch"
    assert key not in result.model_dump_json()

    error_provider = OpenRouterProvider(
        api_key=key,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": {"message": f"bad {key}"}})
        ),
        sleep=lambda _: None,
    )
    error = error_provider.generate(
        model_id="openai/gpt-oss-20b:free", messages=MESSAGES, generation=GENERATION
    )
    assert key not in error.model_dump_json()
    assert "[REDACTED]" in (error.error_message or "")
