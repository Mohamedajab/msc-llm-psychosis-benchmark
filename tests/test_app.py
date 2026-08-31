"""Streamlit smoke and interaction tests for the research dashboard."""

from __future__ import annotations

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from src.provider_client import OpenRouterProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
EXPECTED_VIEWS = (
    "Overview",
    "Collection",
    "Annotation",
    "Analysis",
    "Evidence & QA",
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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
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


def test_startup_is_offline_and_every_sidebar_view_renders(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)

    _assert_no_exceptions(app)
    assert len(app.sidebar.radio) == 1
    assert tuple(app.sidebar.radio[0].options) == EXPECTED_VIEWS

    for view in EXPECTED_VIEWS:
        _navigate(app, view)
        _assert_no_exceptions(app)

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
