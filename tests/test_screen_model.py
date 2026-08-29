"""Zero-network tests for the one-attempt endpoint screen."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts import screen_model
from src.provider_client import OpenRouterProvider


def _catalogue_entry(**updates: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": screen_model.TARGET_MODEL_ID,
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "supported_parameters": ["seed", "temperature"],
        "context_length": 262_144,
    }
    entry.update(updates)
    return entry


@pytest.mark.parametrize(
    "model_id", ["openrouter/free", "openrouter/auto", "vendor/model:latest", "other/free:free"]
)
def test_exact_nvidia_slug_is_required_and_aliases_are_rejected(model_id: str) -> None:
    with pytest.raises(screen_model.ScreeningPreflightError, match="Exact NVIDIA"):
        screen_model.validate_catalogue_entry(_catalogue_entry(id=model_id))


@pytest.mark.parametrize(
    "pricing",
    [
        {"prompt": "0.000001", "completion": "0"},
        {"prompt": "0", "completion": "0.000001"},
    ],
)
def test_paid_endpoint_is_rejected(pricing: dict[str, str]) -> None:
    with pytest.raises(screen_model.ScreeningPreflightError, match="Paid"):
        screen_model.validate_catalogue_entry(_catalogue_entry(pricing=pricing))


def test_offline_command_constructs_no_provider_or_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NetworkForbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("Offline endpoint screen must not construct a provider")

    monkeypatch.setattr(screen_model, "OpenRouterProvider", NetworkForbidden)
    assert screen_model.main([]) == 0
    output = capsys.readouterr().out
    assert "NO NETWORK CALLS" in output
    assert screen_model.TARGET_MODEL_ID in output


def test_catalogue_failure_stores_separate_record_and_sends_no_generation(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": [
                    _catalogue_entry(pricing={"prompt": "1", "completion": "0"})
                ]
            },
        )

    def factory(*, api_key: str) -> OpenRouterProvider:
        return OpenRouterProvider(api_key=api_key, transport=httpx.MockTransport(handler))

    with pytest.raises(screen_model.ScreeningPreflightError, match="zero generation"):
        screen_model.execute_live_screen(
            output_root=tmp_path / "screens",
            live_requested=True,
            live_confirmed=True,
            environ={
                "RUN_LIVE_PILOT": "1",
                "OPENROUTER_API_KEY": "synthetic-secret",
            },
            provider_factory=factory,
        )

    assert [request.method for request in requests] == ["GET"]
    records = list((tmp_path / "screens").rglob("*.json"))
    assert len(records) == 1
    saved = records[0].read_text(encoding="utf-8")
    assert screen_model.SCREEN_NAMESPACE in records[0].parts
    assert "technical-pilot" not in records[0].name
    assert "synthetic-secret" not in saved
    assert json.loads(saved)["generation_attempts"] == 0


def test_one_attempt_no_retry_no_fallback_and_no_pilot_mixing(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    pilot_file = tmp_path / "raw" / "runs" / "technical-pilot-v3_example" / "run.json"
    pilot_file.parent.mkdir(parents=True)
    pilot_file.write_bytes(b"immutable-pilot-evidence")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [_catalogue_entry()]})
        body = json.loads(request.content)
        assert body["model"] == screen_model.TARGET_MODEL_ID
        assert body["seed"] == 20260814
        assert body["stream"] is False
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    def factory(*, api_key: str) -> OpenRouterProvider:
        return OpenRouterProvider(
            api_key=api_key, transport=httpx.MockTransport(handler), sleep=lambda _: None
        )

    record, path = screen_model.execute_live_screen(
        output_root=tmp_path / "raw" / "screens",
        live_requested=True,
        live_confirmed=True,
        environ={
            "RUN_LIVE_PILOT": "1",
            "OPENROUTER_API_KEY": "synthetic-secret",
        },
        provider_factory=factory,
    )

    assert [request.method for request in requests] == ["GET", "POST"]
    assert record["generation_attempts"] == 1
    assert record["fallback_enabled"] is False
    assert record["result"]["retry_count"] == 0
    assert record["result"]["error_type"] == "http_429"
    assert path.parent.name == screen_model.SCREEN_NAMESPACE
    assert pilot_file.read_bytes() == b"immutable-pilot-evidence"


def test_summary_never_prints_response_prompt_reasoning_or_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    response_text = "private generated response"
    prompt_text = "private frozen prompt"
    hidden_reasoning = "private hidden reasoning"
    secret = "synthetic-secret"
    record = {
        "requested_model_id": screen_model.TARGET_MODEL_ID,
        "status": "success",
        "generation_attempts": 1,
        "catalogue_verification": {"context_length": 262_144},
        "result": {
            "text": response_text,
            "resolved_model_id": screen_model.TARGET_MODEL_ID,
            "provider_name": "provider",
            "http_status": 200,
            "error_type": None,
            "latency_ms": 12.5,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "response_metadata": {
                "reasoning": hidden_reasoning,
                "prompt": prompt_text,
                "credential": secret,
            },
        },
    }

    screen_model._print_live_summary(record, tmp_path / "record.json")
    output = capsys.readouterr().out
    assert response_text not in output
    assert prompt_text not in output
    assert hidden_reasoning not in output
    assert secret not in output
    assert "Generation attempts: 1" in output
