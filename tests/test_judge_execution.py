"""Offline tests for concurrent, resumable supplementary judging."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

import src.judge_execution as execution
from src.config_loader import canonical_hash, load_rubric
from src.judge import AXIS_IDS, JudgeOutput
from src.judge_execution import (
    JudgeErrorEvent,
    JudgeExecutionError,
    JudgeSuccess,
    JudgeUsage,
    RequestFailure,
    _request_body,
    judge_configuration_hash,
    load_judge_configuration,
    load_successes,
    run_judge_preflight,
    run_judges,
    save_error,
    save_success,
    select_judges,
)
from src.schemas import AxisScores, BlindedAnnotationItem, ChatMessage

ROOT = Path(__file__).parents[1]
CONFIGURATION = ROOT / "config" / "llm-judges.yaml"


def item(number: int = 1) -> BlindedAnnotationItem:
    return BlindedAnnotationItem(
        blinded_item_id=f"item_{number:020d}",
        turn_number=1,
        conversation_context=(ChatMessage(role="user", content="What might this mean?"),),
        response_to_score="There are several possible explanations.",
        source_response_hash=f"{number:064x}",
    )


def output() -> JudgeOutput:
    return JudgeOutput.model_validate(
        {
            "scores": {axis: 0 for axis in AXIS_IDS},
            "rationale": {axis: "Short reason." for axis in AXIS_IDS},
        }
    )


def payload(model_id: str) -> dict[str, object]:
    return {
        "id": "safe-generation-id",
        "model": model_id,
        "provider": "test-provider",
        "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def success(spec, configuration, judged_item: BlindedAnnotationItem) -> JudgeSuccess:  # noqa: ANN001
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    return JudgeSuccess(
        judge_configuration_version=configuration.version,
        judge_configuration_hash=judge_configuration_hash(configuration),
        rubric_version=configuration.rubric_version,
        rubric_hash=canonical_hash(rubric),
        blinded_item_id=judged_item.blinded_item_id,
        source_response_hash=judged_item.source_response_hash,
        request_hash="a" * 64,
        judge_id=spec.judge_id,
        requested_model_id=spec.model_id,
        resolved_model_id=spec.model_id,
        api_provider=spec.api_provider,
        resolved_provider="test-provider",
        scores=AxisScores(A1=0, A2="N/A", A3="N/A", B1=0, B2=0, B3=0, C1=2),
        rationale={axis: "Short reason." for axis in AXIS_IDS},
        timestamp="2026-09-02T00:00:00Z",
        latency_ms=10,
        usage=JudgeUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        request_attempts=1,
        retry_count=0,
        finish_reason="stop",
    )


def test_configuration_freezes_exact_provider_routes_and_concurrency() -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    by_id = {spec.judge_id: spec for spec in configuration.judges}
    assert by_id["deepseek-v4-pro"].base_url == "https://api.deepseek.com"
    assert by_id["deepseek-v4-pro"].concurrency == 8
    assert by_id["deepseek-v4-flash"].concurrency == 10
    assert by_id["glm-5.3-flash"].model_id == "z-ai/glm-5.3-flash"
    assert by_id["glm-5.3-flash"].concurrency == 8


def test_provider_payloads_disable_thinking_and_model_fallbacks() -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    judged_item = item()
    messages = execution.build_blinded_judge_messages(
        conversation_context=judged_item.conversation_context,
        response_to_score=judged_item.response_to_score,
        rubric=rubric,
    )
    pro, _, glm = configuration.judges
    deepseek = _request_body(spec=pro, configuration=configuration, messages=messages)
    assert deepseek["thinking"] == {"type": "disabled"}
    assert deepseek["response_format"] == {"type": "json_object"}
    assert "provider" not in deepseek
    openrouter = _request_body(spec=glm, configuration=configuration, messages=messages)
    assert openrouter["response_format"]["type"] == "json_schema"
    assert openrouter["response_format"]["json_schema"]["strict"] is True
    assert openrouter["response_format"]["json_schema"]["schema"] == execution.judge_json_schema()
    assert openrouter["reasoning"] == {"effort": "low", "exclude": True}
    assert openrouter["max_tokens"] == 4096
    assert openrouter["provider"] == {"allow_fallbacks": True, "require_parameters": True}
    assert "models" not in openrouter


def test_successes_are_immutable_and_separate_by_judge(tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    pro, flash, _ = configuration.judges
    judged_item = item()
    save_success(tmp_path, pro, success(pro, configuration, judged_item))
    save_success(tmp_path, flash, success(flash, configuration, judged_item))
    with pytest.raises(FileExistsError):
        save_success(tmp_path, pro, success(pro, configuration, judged_item))
    assert len(load_successes(judge_root=tmp_path, spec=pro, configuration=configuration)) == 1
    assert len(load_successes(judge_root=tmp_path, spec=flash, configuration=configuration)) == 1


def test_legacy_deepseek_success_is_kept_when_its_request_is_unchanged(tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    spec = configuration.judges[0]
    judged_item = item()
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    messages = execution.build_blinded_judge_messages(
        conversation_context=judged_item.conversation_context,
        response_to_score=judged_item.response_to_score,
        rubric=rubric,
    )
    legacy_hash = canonical_hash(
        {
            "request_body": _request_body(
                spec=spec,
                configuration=configuration,
                messages=messages,
            ),
            "judge_configuration_hash": execution.LEGACY_JUDGE_CONFIGURATION_HASH,
            "rubric_hash": canonical_hash(rubric),
        }
    )
    result = success(spec, configuration, judged_item).model_copy(
        update={
            "judge_configuration_version": execution.LEGACY_JUDGE_VERSION,
            "judge_configuration_hash": execution.LEGACY_JUDGE_CONFIGURATION_HASH,
            "request_hash": legacy_hash,
        }
    )
    save_success(tmp_path, spec, result)
    loaded = load_successes(
        judge_root=tmp_path,
        spec=spec,
        configuration=configuration,
        items=[judged_item],
        rubric=rubric,
    )
    assert loaded[judged_item.blinded_item_id].request_hash == legacy_hash


def test_error_events_are_append_only(tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    spec = configuration.judges[0]
    judged_item = item()
    values = dict(
        judge_configuration_version=configuration.version,
        blinded_item_id=judged_item.blinded_item_id,
        source_response_hash=judged_item.source_response_hash,
        request_hash="b" * 64,
        judge_id=spec.judge_id,
        requested_model_id=spec.model_id,
        api_provider=spec.api_provider,
        timestamp="2026-09-02T00:00:00Z",
        attempt_number=1,
        retryable=True,
        error_type="http_429",
        http_status=429,
        response_status="RETRYABLE_ERROR",
    )
    save_error(tmp_path, spec, JudgeErrorEvent(event_id="one", **values))
    save_error(tmp_path, spec, JudgeErrorEvent(event_id="two", **values))
    assert len(list((tmp_path / spec.judge_id / "errors").glob("*.json"))) == 2


def test_preflight_is_zero_network_and_requires_keys(monkeypatch, tmp_path: Path) -> None:
    attempted: list[str] = []

    def reject_client(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        attempted.append("network")
        raise AssertionError("network client constructed")

    monkeypatch.setattr(httpx, "AsyncClient", reject_client)
    preflight = run_judge_preflight(
        repository_root=ROOT,
        raw_root=ROOT / "data" / "raw" / "study-v2",
        judge_root=tmp_path,
        configuration_path=CONFIGURATION,
        environ={},
    )
    assert preflight.item_count == 432
    assert "judge_api_key_not_available" in preflight.blockers
    assert preflight.network_requests == 0
    assert attempted == []

    smoke_gate = run_judge_preflight(
        repository_root=ROOT,
        raw_root=ROOT / "data" / "raw" / "study-v2",
        judge_root=tmp_path,
        configuration_path=CONFIGURATION,
        environ={"DEEPSEEK_API_KEY": "test", "OPENROUTER_API_KEY": "test"},
        require_smoke_validation=True,
    )
    assert smoke_gate.checks["smoke_validation_complete"] is False
    assert "judge_smoke_validation_not_complete" in smoke_gate.blockers
    assert attempted == []


def test_worker_reservation_blocks_a_second_launch(tmp_path: Path) -> None:
    token = execution.reserve_worker(tmp_path)
    assert execution.worker_is_active(tmp_path) is True
    with pytest.raises(JudgeExecutionError, match="already running"):
        execution.reserve_worker(tmp_path)
    execution.release_worker(tmp_path, token)


def test_worker_lock_rejects_bad_shape_and_expires_unclaimed_reservation(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text("[]", encoding="utf-8")
    with pytest.raises(JudgeExecutionError, match="malformed"):
        execution.read_worker_lock(tmp_path)

    lock_path.write_text(
        json.dumps(
            {
                "token": "stale",
                "pid": 0,
                "created_at": (datetime.now(UTC) - timedelta(minutes=3)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert execution.worker_is_active(tmp_path) is False


def test_safe_stop_is_not_cleared_by_worker_start(monkeypatch, tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    spec = configuration.judges[0]
    calls = 0
    judge_root = tmp_path / "judges"
    monkeypatch.setattr(
        execution,
        "load_blinded_judge_items",
        lambda **kwargs: ([item()], "bundle-hash"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")

    async def unexpected_request(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        return output(), payload(spec.model_id), 10.0

    monkeypatch.setattr(execution, "_make_request", unexpected_request)
    execution.request_safe_stop(judge_root)
    asyncio.run(
        run_judges(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            judge_root=judge_root,
            configuration_path=CONFIGURATION,
            judge_ids=[spec.judge_id],
        )
    )
    assert calls == 0
    assert execution.load_job_state(judge_root).status == "STOPPED"


def test_run_is_concurrent_resumable_and_never_regenerates_success(
    monkeypatch, tmp_path: Path
) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    judged_items = [item(1), item(2)]
    calls: list[tuple[str, str]] = []
    active = 0
    maximum_active = 0

    monkeypatch.setattr(
        execution,
        "load_blinded_judge_items",
        lambda **kwargs: (judged_items, "bundle-hash"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")

    async def fake_request(*, spec, **kwargs):  # noqa: ANN001, ANN003
        nonlocal active, maximum_active
        response_text = json.loads(kwargs["messages"][1].content)["assistant_response_to_score"]
        calls.append((spec.judge_id, response_text))
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return output(), payload(spec.model_id), 10.0

    monkeypatch.setattr(execution, "_make_request", fake_request)
    for _ in range(2):
        asyncio.run(
            run_judges(
                repository_root=ROOT,
                raw_root=tmp_path / "raw",
                judge_root=tmp_path / "judges",
                configuration_path=CONFIGURATION,
            )
        )
    assert len(calls) == 6
    assert maximum_active > 1
    for spec in configuration.judges:
        assert (
            len(
                load_successes(
                    judge_root=tmp_path / "judges",
                    spec=spec,
                    configuration=configuration,
                    items=judged_items,
                )
            )
            == 2
        )


def test_malformed_output_retries_and_permanent_auth_does_not(monkeypatch, tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION).model_copy(
        update={"retry_delays_seconds": (0, 0, 0, 0, 0, 0)}
    )
    spec = select_judges(configuration, ["deepseek-v4-pro"])[0]
    judged_items = [item()]
    attempts = 0
    monkeypatch.setattr(execution, "load_judge_configuration", lambda path: configuration)
    monkeypatch.setattr(
        execution,
        "load_blinded_judge_items",
        lambda **kwargs: (judged_items, "bundle-hash"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")

    async def malformed_once(**kwargs):  # noqa: ANN003
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestFailure("malformed_judge_json", retryable=True)
        return output(), payload(spec.model_id), 10.0

    monkeypatch.setattr(execution, "_make_request", malformed_once)
    asyncio.run(
        run_judges(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            judge_root=tmp_path / "judges",
            configuration_path=CONFIGURATION,
            judge_ids=[spec.judge_id],
        )
    )
    assert attempts == 2

    other_root = tmp_path / "permanent"
    attempts = 0

    async def permanent(**kwargs):  # noqa: ANN003
        nonlocal attempts
        attempts += 1
        raise RequestFailure("http_401", retryable=False, http_status=401)

    monkeypatch.setattr(execution, "_make_request", permanent)
    asyncio.run(
        run_judges(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            judge_root=other_root,
            configuration_path=CONFIGURATION,
            judge_ids=[spec.judge_id],
        )
    )
    assert attempts == 1


def test_resume_counts_saved_attempts_and_stops_a_judge_after_permanent_failure(
    monkeypatch, tmp_path: Path
) -> None:
    configuration = load_judge_configuration(CONFIGURATION).model_copy(
        update={
            "retry_delays_seconds": (0, 0, 0, 0, 0, 0),
            "judges": tuple(
                spec.model_copy(update={"concurrency": 1})
                for spec in load_judge_configuration(CONFIGURATION).judges
            ),
        }
    )
    spec = select_judges(configuration, ["deepseek-v4-pro"])[0]
    judged_items = [item(1), item(2)]
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    request_hash, _ = execution.request_hash_for_item(
        item=judged_items[0],
        rubric=rubric,
        configuration=configuration,
        spec=spec,
    )
    save_error(
        tmp_path,
        spec,
        JudgeErrorEvent(
            event_id="saved",
            judge_configuration_version=configuration.version,
            blinded_item_id=judged_items[0].blinded_item_id,
            source_response_hash=judged_items[0].source_response_hash,
            request_hash=request_hash,
            judge_id=spec.judge_id,
            requested_model_id=spec.model_id,
            api_provider=spec.api_provider,
            timestamp="2026-09-02T00:00:00Z",
            attempt_number=1,
            retryable=True,
            error_type="http_429",
            http_status=429,
            response_status="RETRYABLE_ERROR",
        ),
    )
    calls = 0
    monkeypatch.setattr(execution, "load_judge_configuration", lambda path: configuration)
    monkeypatch.setattr(
        execution,
        "load_blinded_judge_items",
        lambda **kwargs: (judged_items, "bundle-hash"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")

    async def fail_permanently(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        raise RequestFailure("http_401", retryable=False, http_status=401)

    monkeypatch.setattr(execution, "_make_request", fail_permanently)
    asyncio.run(
        run_judges(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            judge_root=tmp_path,
            configuration_path=CONFIGURATION,
            judge_ids=[spec.judge_id],
        )
    )
    assert calls == 1
    errors = execution.load_errors(tmp_path, spec)
    assert sorted(event.attempt_number for event in errors) == [1, 2]
    assert all(event.blinded_item_id == judged_items[0].blinded_item_id for event in errors)


def test_saved_success_with_changed_source_fails_closed(tmp_path: Path) -> None:
    configuration = load_judge_configuration(CONFIGURATION)
    spec = configuration.judges[0]
    judged_item = item()
    save_success(tmp_path, spec, success(spec, configuration, judged_item))
    changed = judged_item.model_copy(update={"source_response_hash": "f" * 64})
    with pytest.raises(JudgeExecutionError, match="does not match blinded source"):
        load_successes(
            judge_root=tmp_path,
            spec=spec,
            configuration=configuration,
            items=[changed],
        )


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_http_statuses_are_retryable(status: int) -> None:
    async def exercise() -> None:
        configuration = load_judge_configuration(CONFIGURATION)
        spec = configuration.judges[0]
        transport = httpx.MockTransport(lambda request: httpx.Response(status, request=request))
        async with httpx.AsyncClient(
            base_url=spec.base_url,
            transport=transport,
        ) as client:
            with pytest.raises(RequestFailure) as caught:
                await execution._make_request(
                    client=client,
                    spec=spec,
                    configuration=configuration,
                    messages=(ChatMessage(role="user", content="json"),),
                    api_key="test-only",
                )
        assert caught.value.retryable is True

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_permanent_http_statuses_are_not_retried(status: int) -> None:
    async def exercise() -> None:
        configuration = load_judge_configuration(CONFIGURATION)
        spec = configuration.judges[0]
        transport = httpx.MockTransport(lambda request: httpx.Response(status, request=request))
        async with httpx.AsyncClient(
            base_url=spec.base_url,
            transport=transport,
        ) as client:
            with pytest.raises(RequestFailure) as caught:
                await execution._make_request(
                    client=client,
                    spec=spec,
                    configuration=configuration,
                    messages=(ChatMessage(role="user", content="json"),),
                    api_key="test-only",
                )
        assert caught.value.retryable is False

    asyncio.run(exercise())


def test_rate_limit_reduces_concurrency() -> None:
    async def exercise() -> None:
        limiter = execution.AdaptiveLimiter(8)
        await limiter.acquire()
        await limiter.release(rate_limited=True, success=False)
        assert limiter.limit == 7

    asyncio.run(exercise())
