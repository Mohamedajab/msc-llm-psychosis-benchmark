"""Offline tests for main-study provider error classification."""

from __future__ import annotations

import pytest

from src.provider_errors import classify_provider_result
from src.schemas import ObservationStatus, ProviderResult


def _error(
    error_type: str,
    *,
    message: str | None = None,
    http_status: int | None = None,
    metadata: dict | None = None,
) -> ProviderResult:
    return ProviderResult(
        status=ObservationStatus.PROVIDER_ERROR,
        requested_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        provider_name="openrouter",
        latency_ms=1,
        retry_count=0,
        http_attempts=1,
        http_status=http_status,
        error_type=error_type,
        error_message=message,
        response_metadata=metadata or {},
    )


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_outer_transient_http_codes_are_retryable(code: int) -> None:
    classification = classify_provider_result(_error(f"http_{code}", http_status=code))
    assert classification.retryable is True
    assert classification.category == "outer_http_transient"
    assert classification.upstream_error_code is None


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
@pytest.mark.parametrize("stored_code", ["integer", "string"])
def test_embedded_transient_codes_are_retryable(code: int, stored_code: str) -> None:
    value: int | str = code if stored_code == "integer" else str(code)
    result = _error(
        "provider_body_error",
        message=repr({"message": "Service temporarily overloaded", "code": value}),
        http_status=200,
    )
    classification = classify_provider_result(result)
    assert classification.retryable is True
    assert classification.reason_code == f"upstream_http_{code}"
    assert classification.upstream_error_code == code
    assert classification.upstream_error_message == "Service temporarily overloaded"
    assert result.http_status == 200


@pytest.mark.parametrize("code", [400, 401, 402, 403])
def test_embedded_permanent_codes_are_not_retryable(code: int) -> None:
    classification = classify_provider_result(
        _error("provider_body_error", message=repr({"message": "Rejected", "code": code}))
    )
    assert classification.retryable is False
    assert classification.category == "permanent"
    assert classification.reason_code == f"upstream_http_{code}"


@pytest.mark.parametrize(
    "message",
    [
        "not a mapping",
        "{'message': 'mentions 502 but has no code'}",
        "{'message': 'bad', 'code': 'not-502'}",
        "arbitrary text containing 502",
        "missing choices",
    ],
)
def test_malformed_or_unstructured_body_errors_are_not_retryable(message: str) -> None:
    classification = classify_provider_result(_error("provider_body_error", message=message))
    assert classification.retryable is False
    assert classification.reason_code == "provider_body_error"


@pytest.mark.parametrize(
    "error_type",
    [
        "ConnectError",
        "ConnectTimeout",
        "NetworkError",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "WriteError",
        "WriteTimeout",
    ],
)
def test_transport_errors_are_retryable(error_type: str) -> None:
    assert classify_provider_result(_error(error_type)).retryable is True


def test_structured_upstream_metadata_is_supported_without_changing_outer_status() -> None:
    result = _error(
        "upstream_http_502",
        http_status=200,
        metadata={
            "upstream_error_code": 502,
            "upstream_error_message": "Service temporarily overloaded",
        },
    )
    classification = classify_provider_result(result)
    assert classification.retryable is True
    assert classification.upstream_error_code == 502
    assert result.http_status == 200


def test_truncation_and_model_mismatch_are_hard_stops() -> None:
    truncated = ProviderResult(
        status=ObservationStatus.RESPONSE,
        text="Incomplete",
        requested_model_id="example/model:free",
        resolved_model_id="example/model:free",
        provider_name="fixture",
        finish_reason="length",
        latency_ms=1,
        retry_count=0,
        http_attempts=1,
    )
    mismatch = _error("resolved_model_mismatch")
    assert classify_provider_result(truncated).category == "scientific_hard_stop"
    assert classify_provider_result(truncated).retryable is False
    assert classify_provider_result(mismatch).category == "scientific_hard_stop"
    assert classify_provider_result(mismatch).retryable is False
