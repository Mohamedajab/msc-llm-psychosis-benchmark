"""Streamlit smoke and interaction tests for the research dashboard."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import dotenv
import httpx
import pytest
from streamlit.testing.v1 import AppTest

from src.config_loader import configuration_bundle_hash, generation_for_model
from src.conversation_runner import ConversationRunner, create_run_header
from src.main_study import JobStatus, StudyJobState, planned_study, save_job_state
from src.provider_client import OpenRouterProvider, TargetProvider
from src.schemas import ObservationStatus, ProviderResult
from src.storage import RawRunStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
EXPECTED_VIEWS = (
    "Overview",
    "Collection",
    "Annotation",
    "LLM Judges",
    "Analysis",
    "Evidence & QA",
)


class RecoverableInterruptionProvider(TargetProvider):
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model_id, messages, generation):  # noqa: ANN001
        del messages, generation
        self.calls += 1
        if self.calls == 4:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=model_id,
                provider_name="openrouter",
                latency_ms=1,
                retry_count=0,
                http_attempts=1,
                http_status=200,
                error_type="provider_body_error",
                error_message=repr(
                    {
                        "message": "Upstream error from Nvidia: Service temporarily overloaded",
                        "code": 502,
                    }
                ),
            )
        return ProviderResult(
            status=ObservationStatus.RESPONSE,
            text=f"fixture response {self.calls}",
            requested_model_id=model_id,
            resolved_model_id=model_id,
            provider_name="fixture",
            finish_reason="stop",
            latency_ms=1,
            retry_count=0,
            http_attempts=1,
        )


class Manual402Provider(TargetProvider):
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model_id, messages, generation):  # noqa: ANN001
        del messages, generation
        self.calls += 1
        if self.calls == 1:
            return ProviderResult(
                status=ObservationStatus.RESPONSE,
                text="saved first response",
                requested_model_id=model_id,
                resolved_model_id=model_id,
                provider_name="fixture",
                finish_reason="stop",
                latency_ms=1,
                retry_count=0,
                http_attempts=1,
            )
        return ProviderResult(
            status=ObservationStatus.PROVIDER_ERROR,
            requested_model_id=model_id,
            provider_name="openrouter",
            latency_ms=1,
            retry_count=0,
            http_attempts=1,
            http_status=200,
            error_type="provider_body_error",
            error_message=repr({"message": "Payment required", "code": 402}),
        )


def _assert_no_exceptions(app: AppTest) -> None:
    assert not app.exception, [exception.message for exception in app.exception]


def _offline_app(monkeypatch, tmp_path: Path) -> tuple[AppTest, list[str]]:
    network_attempts: list[str] = []

    def reject_request(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        network_attempts.append("httpx")
        raise AssertionError("The dashboard attempted a network request")

    def reject_openrouter(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        network_attempts.append("openrouter")
        raise AssertionError("OpenRouter was constructed without explicit execution")

    monkeypatch.setenv("BENCHMARK_DATA_DIR", str(tmp_path))
    # An empty value keeps tests isolated from the developer's local .env file.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr(httpx.Client, "request", reject_request)
    monkeypatch.setattr(OpenRouterProvider, "__init__", reject_openrouter)
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    return app, network_attempts


def _navigate(app: AppTest, view: str) -> AppTest:
    app.sidebar.radio[0].set_value(view)
    return app.run(timeout=60)


def _button(app: AppTest, label: str):  # noqa: ANN202
    return next(button for button in app.button if button.label == label)


def _selectbox(app: AppTest, label: str):  # noqa: ANN202
    return next(selectbox for selectbox in app.selectbox if selectbox.label == label)


def test_startup_loads_project_env_once_without_override(monkeypatch, tmp_path) -> None:
    calls: list[tuple[Path, bool]] = []

    def record_load(path: Path, *, override: bool) -> bool:
        calls.append((Path(path), override))
        return True

    monkeypatch.setattr(dotenv, "load_dotenv", record_load)
    app, network_attempts = _offline_app(monkeypatch, tmp_path)

    _assert_no_exceptions(app)
    assert calls == [(PROJECT_ROOT / ".env", False)]
    assert network_attempts == []


def test_startup_is_offline_and_every_sidebar_view_renders(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)

    _assert_no_exceptions(app)
    assert len(app.sidebar.radio) == 1
    assert tuple(app.sidebar.radio[0].options) == EXPECTED_VIEWS

    for view in EXPECTED_VIEWS:
        _navigate(app, view)
        _assert_no_exceptions(app)

    assert network_attempts == []


def test_llm_judges_page_starts_empty_and_does_not_construct_provider(
    monkeypatch, tmp_path
) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "LLM Judges")
    _assert_no_exceptions(app)

    values = {metric.label: metric.value for metric in app.metric}
    assert values["DeepSeek V4 Pro"] == "0 / 432"
    assert values["DeepSeek V4 Flash"] == "0 / 432"
    assert values["GLM-5.3-Flash"] == "0 / 432"
    assert values["Total"] == "0 / 1296"
    assert next(button for button in app.button if button.label == "Safe Stop").disabled
    assert any("Detailed judge scores remain hidden" in info.value for info in app.info)
    assert network_attempts == []


def test_dry_run_previews_exactly_six_offline_payloads(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Evidence & QA")

    _button(app, "Preview exact six payloads").click()
    app.run(timeout=60)
    _assert_no_exceptions(app)

    payloads = app.session_state["dry_run_payloads"]
    assert len(payloads) == 6
    assert [payload["turn_number"] for payload in payloads] == [1, 2, 3, 4, 5, 6]
    assert [len(payload["messages"]) for payload in payloads] == [1, 3, 5, 7, 9, 11]
    assert all(payload["messages"][0]["role"] == "user" for payload in payloads)
    assert all(payload["network_called"] is False for payload in payloads)
    assert network_attempts == []


def test_dashboard_exposes_no_live_execution_control(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Evidence & QA")
    modes = tuple(_selectbox(app, "Execution mode").options)
    assert modes == (
        "Dry run (offline payload preview)",
        "Deterministic fixture (offline execution)",
    )
    assert all("live" not in button.label.casefold() for button in app.button)
    assert network_attempts == []


def test_main_study_page_reads_zero_progress_without_network(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Collection")
    _assert_no_exceptions(app)
    assert any(metric.label == "Responses" and metric.value == "0 / 432" for metric in app.metric)
    assert any("Study status: NOT READY" in warning.value for warning in app.warning)
    assert any(
        metric.label == "Current conversation" and metric.value == "—" for metric in app.metric
    )
    assert any(metric.label == "Current turn" and metric.value == "—" for metric in app.metric)
    assert any(metric.label == "Current model" and metric.value == "—" for metric in app.metric)
    assert not any("DEMO FIXTURE" in warning.value for warning in app.warning)
    assert not any("TECHNICAL PILOT" in info.value for info in app.info)
    assert not any(
        "Active study bundle has not been created." in markdown.value for markdown in app.markdown
    )
    assert any(
        "OpenRouter API key is not available to the app process." in markdown.value
        for markdown in app.markdown
    )
    assert not any("Supervisor review" in markdown.value for markdown in app.markdown)
    assert not any("Ethics determination" in markdown.value for markdown in app.markdown)
    assert not any("_not_" in markdown.value for markdown in app.markdown)
    assert any(
        "Start is disabled until all preflight requirements are complete." in caption.value
        for caption in app.caption
    )
    assert _button(app, "Start Main Study").disabled is True
    assert network_attempts == []


def test_collection_page_offers_resume_for_embedded_upstream_failure(monkeypatch, tmp_path) -> None:
    scripts, histories, models, rows = planned_study(PROJECT_ROOT)
    row = rows[0]
    script = next(item for item in scripts if item.script_id == row.script_id)
    prefix = next(item for item in histories if item.history_id == script.history_id)
    generation = generation_for_model(models, row.model_slot, row.repetition)
    header = create_run_header(
        study_version=row.study_version,
        run_id=row.run_id,
        data_status="main_study",
        script=script,
        condition=row.context_condition,
        model_slot=row.model_slot,
        model_id=row.requested_model_id,
        repetition=row.repetition,
        generation=generation,
        configuration_version=models.version,
        configuration_hash=configuration_bundle_hash(scripts, histories, models),
    )
    store = RawRunStore(tmp_path / "raw" / "study-v2")
    ConversationRunner(RecoverableInterruptionProvider(), store).run_or_resume(
        header=header,
        script=script,
        prefix=prefix,
    )
    save_job_state(
        tmp_path / "private" / "main-study-job" / "state.json",
        StudyJobState(
            status=JobStatus.BLOCKED,
            message="Collection stopped after non-retryable error: provider_body_error.",
        ),
    )

    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Collection")
    _assert_no_exceptions(app)
    assert any("Study status: RESUMABLE" in warning.value for warning in app.warning)
    assert any(
        "Temporary upstream provider failure (502)" in warning.value for warning in app.warning
    )
    assert _button(app, "Resume Main Study").disabled is True
    assert not any(button.label == "Start Main Study" for button in app.button)
    assert network_attempts == []


def test_collection_page_requires_confirmation_for_upstream_402(monkeypatch, tmp_path) -> None:
    scripts, histories, models, rows = planned_study(PROJECT_ROOT)
    row = rows[0]
    script = next(item for item in scripts if item.script_id == row.script_id)
    prefix = next(item for item in histories if item.history_id == script.history_id)
    store = RawRunStore(tmp_path / "raw" / "study-v2")
    ConversationRunner(Manual402Provider(), store).run_or_resume(
        header=create_run_header(
            study_version=row.study_version,
            run_id=row.run_id,
            data_status="main_study",
            script=script,
            condition=row.context_condition,
            model_slot=row.model_slot,
            model_id=row.requested_model_id,
            repetition=row.repetition,
            generation=generation_for_model(models, row.model_slot, row.repetition),
            configuration_version=models.version,
            configuration_hash=configuration_bundle_hash(scripts, histories, models),
        ),
        script=script,
        prefix=prefix,
    )
    save_job_state(
        tmp_path / "private" / "main-study-job" / "state.json",
        StudyJobState(
            status=JobStatus.BLOCKED,
            message="Collection stopped after non-retryable error: upstream_http_402.",
        ),
    )

    monkeypatch.setattr(
        "src.main_study.evaluate_main_study_readiness",
        lambda **_: SimpleNamespace(
            blockers=(),
            active_bundle="PASS",
            governance="PASS",
            main_study="READY",
        ),
    )
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    _navigate(app, "Collection")
    _assert_no_exceptions(app)
    assert any("upstream provider returned HTTP 402" in warning.value for warning in app.warning)
    confirmation = next(
        checkbox for checkbox in app.checkbox if "first missing response" in checkbox.label
    )
    assert _button(app, "Resume Main Study").disabled is True
    confirmation.set_value(True)
    app.run(timeout=60)
    assert _button(app, "Resume Main Study").disabled is False
    assert network_attempts == []


def test_collection_page_reports_approved_finish_metadata_anomaly(monkeypatch, tmp_path) -> None:
    run_id = "study-v2.1.0_monitoring_ambiguous_v1_model_minimax_no_preloaded_context_r2"
    source = PROJECT_ROOT / "data" / "raw" / "study-v2" / run_id
    if not source.is_dir():
        pytest.skip("Private Study V2 evidence is not present in this checkout")
    destination = tmp_path / "raw" / "study-v2" / run_id
    shutil.copytree(source, destination)

    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Collection")
    _assert_no_exceptions(app)
    assert any(
        metric.label == "Approved metadata anomalies" and metric.value == "1"
        for metric in app.metric
    )
    assert any("preserved as unreported/unknown" in warning.value for warning in app.warning)
    assert network_attempts == []


def test_offline_fixture_and_provenance_flow(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Evidence & QA")
    _selectbox(app, "Execution mode").set_value("Deterministic fixture (offline execution)")
    app.run(timeout=60)
    _button(app, "Run or resume six-turn fixture").click()
    app.run(timeout=60)
    _assert_no_exceptions(app)

    assert app.session_state["current_run_id"] == "friday-demo-run"
    successes = list(tmp_path.rglob("turn-*-success.json"))
    assert len(successes) == 6

    app.run(timeout=60)
    assert any(dataframe.value.shape[0] == 6 for dataframe in app.dataframe)

    _navigate(app, "Annotation")
    _assert_no_exceptions(app)
    assert any("Annotation becomes available" in info.value for info in app.info)

    _navigate(app, "Analysis")
    _assert_no_exceptions(app)
    assert any("Results will appear" in info.value for info in app.info)
    assert network_attempts == []
