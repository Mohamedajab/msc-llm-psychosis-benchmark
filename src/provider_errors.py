"""Classify provider and transport failures for bounded recovery."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.schemas import ObservationStatus, ProviderResult

TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
TRANSPORT_ERROR_TYPES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "NetworkError",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "WriteError",
        "WriteTimeout",
    }
)
HARD_STOP_ERROR_TYPES = frozenset(
    {
        "configuration_mismatch",
        "duplicate_success",
        "malformed_evidence",
        "resolved_model_mismatch",
    }
)
_HTTP_ERROR = re.compile(r"http_(\d{3})\Z")
_UPSTREAM_ERROR = re.compile(r"upstream_http_(\d{3})\Z")


@dataclass(frozen=True)
class ProviderErrorClassification:
    retryable: bool
    category: str
    reason_code: str
    upstream_error_code: int | None = None
    upstream_error_message: str | None = None
    manual_resume_allowed: bool = False


def _error_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 100 <= value <= 599 else None
    if isinstance(value, str) and re.fullmatch(r"\d{3}", value.strip()):
        code = int(value)
        return code if 100 <= code <= 599 else None
    return None


def _safe_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:240] or None


def _legacy_embedded_error(message: str | None) -> Mapping[str, Any] | None:
    if not message:
        return None
    try:
        value = ast.literal_eval(message)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _embedded_error(result: ProviderResult) -> tuple[int | None, str | None]:
    metadata = result.response_metadata
    code = _error_code(metadata.get("upstream_error_code"))
    message = _safe_message(metadata.get("upstream_error_message"))
    if code is not None:
        return code, message
    legacy = _legacy_embedded_error(result.error_message)
    if legacy is None:
        return None, None
    return _error_code(legacy.get("code")), _safe_message(legacy.get("message"))


def _classify_upstream_error(
    code: int,
    reason: str,
    message: str | None,
) -> ProviderErrorClassification:
    if code == 402:
        return ProviderErrorClassification(
            retryable=False,
            category="operator_recoverable",
            reason_code=reason,
            upstream_error_code=code,
            upstream_error_message=message,
            manual_resume_allowed=True,
        )
    return ProviderErrorClassification(
        retryable=code in TRANSIENT_HTTP_CODES,
        category="upstream_transient" if code in TRANSIENT_HTTP_CODES else "permanent",
        reason_code=reason,
        upstream_error_code=code,
        upstream_error_message=message,
    )


def classify_provider_result(result: ProviderResult) -> ProviderErrorClassification:
    """Classify one result without changing its recorded provenance."""

    finish_reason = (result.finish_reason or "").strip().casefold()
    if result.status == ObservationStatus.RESPONSE:
        if result.truncated or finish_reason != "stop":
            return ProviderErrorClassification(False, "scientific_hard_stop", "incomplete_result")
        return ProviderErrorClassification(False, "success", "response")

    error_type = result.error_type or "unknown_error"
    if error_type in HARD_STOP_ERROR_TYPES:
        return ProviderErrorClassification(False, "scientific_hard_stop", error_type)

    match = _HTTP_ERROR.fullmatch(error_type)
    if match:
        code = int(match.group(1))
        return ProviderErrorClassification(
            code in TRANSIENT_HTTP_CODES,
            "outer_http_transient" if code in TRANSIENT_HTTP_CODES else "permanent",
            error_type,
        )

    match = _UPSTREAM_ERROR.fullmatch(error_type)
    if match:
        code = int(match.group(1))
        return _classify_upstream_error(
            code,
            error_type,
            _safe_message(result.response_metadata.get("upstream_error_message")),
        )

    if error_type == "provider_body_error":
        code, message = _embedded_error(result)
        if code is not None:
            reason = f"upstream_http_{code}"
            return _classify_upstream_error(code, reason, message)
        return ProviderErrorClassification(False, "permanent", error_type)

    if error_type in TRANSPORT_ERROR_TYPES or error_type == "catalogue_preflight_error":
        return ProviderErrorClassification(True, "transport_transient", error_type)
    return ProviderErrorClassification(False, "permanent", error_type)


def classify_error_type(error_type: str) -> ProviderErrorClassification:
    """Classify a worker exception using the same exact error taxonomy."""

    result = ProviderResult(
        status=ObservationStatus.PROVIDER_ERROR,
        requested_model_id="worker",
        latency_ms=0,
        retry_count=0,
        http_attempts=0,
        error_type=error_type,
    )
    return classify_provider_result(result)
