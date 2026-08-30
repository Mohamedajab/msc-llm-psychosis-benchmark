"""Offline tests for the bounded benign generation calibration."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_generation_calibration
from src.generation_calibration import (
    BENIGN_MESSAGES,
    EXACT_MODEL_ID,
    MAX_GENERATION_REQUESTS,
    CalibrationVerdict,
    execute_calibration,
    offline_calibration_plan,
)
from src.schemas import ObservationStatus, ProviderResult, TokenUsage


def _entry(*, paid: bool = False) -> dict[str, object]:
    return {
        "id": EXACT_MODEL_ID,
        "pricing": {"prompt": "0", "completion": "0.1" if paid else "0"},
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "supported_parameters": ["seed", "reasoning", "max_tokens"],
        "context_length": 262_144,
        "reasoning": {
            "mandatory": False,
            "default_enabled": True,
            "supports_max_tokens": True,
            "supported_efforts": ["medium", "low"],
        },
    }


class CalibrationFixture:
    def __init__(self, *, paid_on_call: int | None = None) -> None:
        self.request_attempt_count = 0
        self.catalogue_calls = 0
        self.generated = []
        self.paid_on_call = paid_on_call

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def set_retry_rate_limits(self, enabled: bool) -> None:
        self.retry_429 = enabled

    def set_minimum_request_interval(self, seconds: float) -> None:
        self.interval = seconds

    def set_provider_routing(self, policy) -> None:  # noqa: ANN001
        self.routing = policy

    def get_exact_model_catalogue_entry(self, model_id: str, timeout_seconds: float = 20):
        assert model_id == EXACT_MODEL_ID
        assert timeout_seconds == 20
        self.catalogue_calls += 1
        return _entry(paid=self.catalogue_calls == self.paid_on_call)

    def generate(self, *, model_id, messages, generation):  # noqa: ANN001, ANN202
        assert model_id == EXACT_MODEL_ID
        assert tuple(messages) == BENIGN_MESSAGES
        assert self.request_attempt_count < self.maximum
        self.request_attempt_count += 1
        self.generated.append(generation)
        disabled = generation.reasoning_policy is not None
        native_has_headroom = generation.max_tokens >= 2048
        return ProviderResult(
            status=ObservationStatus.RESPONSE,
            text="Private benign calibration output that must not be printed.",
            requested_model_id=model_id,
            resolved_model_id=model_id,
            provider_name="Nvidia",
            finish_reason="stop" if disabled or native_has_headroom else "length",
            usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=100 if disabled else min(1200, generation.max_tokens),
                total_tokens=200 if disabled else min(1300, generation.max_tokens + 100),
                reasoning_tokens=0 if disabled else 900,
            ),
            latency_ms=10,
            retry_count=0,
            http_attempts=1,
            http_status=200,
        )


def test_offline_default_has_zero_network_calls(monkeypatch, capsys, tmp_path) -> None:  # noqa: ANN001
    class NetworkForbidden:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("offline command constructed a provider")

    monkeypatch.setattr(run_generation_calibration, "OpenRouterProvider", NetworkForbidden)
    assert offline_calibration_plan()["network_requests"] == 0
    assert run_generation_calibration.main(["--output-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "network_requests=0" in output
    assert "substantive_response_text_printed=no" in output


@pytest.mark.parametrize(
    ("live", "confirmed", "environment", "message"),
    [
        (False, True, {"RUN_LIVE_CALIBRATION": "1"}, "--live"),
        (True, False, {"RUN_LIVE_CALIBRATION": "1"}, "--confirm-live"),
        (True, True, {}, "RUN_LIVE_CALIBRATION=1"),
        (True, True, {"RUN_LIVE_CALIBRATION": "1"}, "API key"),
    ],
)
def test_live_gates_fail_before_provider_use(live, confirmed, environment, message) -> None:  # noqa: ANN001
    with pytest.raises(RuntimeError, match=message):
        run_generation_calibration.require_live_gates(
            live_requested=live,
            live_confirmed=confirmed,
            environ=environment,
        )


def test_each_generation_has_fresh_zero_price_check_and_adaptive_stop(tmp_path: Path) -> None:
    provider = CalibrationFixture()
    summary = execute_calibration(provider=provider, output_root=tmp_path)  # type: ignore[arg-type]
    assert summary.verdict == CalibrationVerdict.SUPPORTED
    assert summary.generation_requests == 5
    assert provider.catalogue_calls == provider.request_attempt_count == 5
    assert provider.retry_429 is False
    assert provider.interval == 5.0
    assert provider.routing.allow_fallbacks is False
    assert provider.routing.require_parameters is True
    assert len(list(tmp_path.glob("*.json"))) == 5
    assert all(record["zero_price_confirmed"] for record in summary.records)
    assert all(generation.max_retries == 0 for generation in provider.generated)
    assert provider.generated[0].reasoning_policy is None
    assert provider.generated[1].request_parameters()["reasoning"] == {
        "exclude": True,
        "effort": "none",
    }


def test_paid_recheck_stops_before_next_generation(tmp_path: Path) -> None:
    provider = CalibrationFixture(paid_on_call=2)
    with pytest.raises(RuntimeError, match="Paid prompt or completion pricing"):
        execute_calibration(provider=provider, output_root=tmp_path)  # type: ignore[arg-type]
    assert provider.catalogue_calls == 2
    assert provider.request_attempt_count == 1


def test_persisted_cap_prevents_more_than_six_requests(tmp_path: Path) -> None:
    provider = CalibrationFixture()
    execute_calibration(provider=provider, output_root=tmp_path)  # type: ignore[arg-type]
    second = CalibrationFixture()
    summary = execute_calibration(provider=second, output_root=tmp_path)  # type: ignore[arg-type]
    assert summary.generation_requests == 5
    assert second.request_attempt_count == 0
    assert summary.generation_requests <= MAX_GENERATION_REQUESTS


def test_terminal_summary_never_prints_private_output(capsys) -> None:  # noqa: ANN001
    provider = CalibrationFixture()
    # Use a temporary path supplied by pytest's capture-independent tmp location.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        summary = execute_calibration(provider=provider, output_root=directory)  # type: ignore[arg-type]
    run_generation_calibration._print_summary(summary)
    output = capsys.readouterr().out
    assert "Private benign calibration output" not in output
    assert "substantive_response_text_printed=no" in output
