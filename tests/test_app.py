"""Streamlit smoke and interaction tests for the seven-view research dashboard."""

from __future__ import annotations

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from src.provider_client import OpenRouterProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
EXPECTED_VIEWS = (
    "Study Overview",
    "Experiment Runner",
    "Transcript & Provenance",
    "Blinded Annotation",
    "NLP Explorer",
    "Trajectory Analysis",
    "Reproducibility & QA",
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
    _navigate(app, "Experiment Runner")

    _button(app, "Preview exact six payloads").click()
    app.run(timeout=60)
    _assert_no_exceptions(app)

    payloads = app.session_state["dry_run_payloads"]
    assert len(payloads) == 6
    assert [payload["turn_number"] for payload in payloads] == [1, 2, 3, 4, 5, 6]
    assert [len(payload["messages"]) for payload in payloads] == [2, 4, 6, 8, 10, 12]
    assert all(payload["messages"][0]["role"] == "system" for payload in payloads)
    assert all(payload["network_called"] is False for payload in payloads)
    assert network_attempts == []


def test_dashboard_exposes_no_live_execution_control(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Experiment Runner")
    modes = tuple(_selectbox(app, "Execution mode").options)
    assert modes == (
        "Dry run (offline payload preview)",
        "Deterministic fixture (offline execution)",
    )
    assert all("live" not in button.label.casefold() for button in app.button)
    assert network_attempts == []


def test_fixture_annotation_nlp_and_trajectory_flow(monkeypatch, tmp_path) -> None:
    app, network_attempts = _offline_app(monkeypatch, tmp_path)
    _navigate(app, "Experiment Runner")
    _selectbox(app, "Execution mode").set_value("Deterministic fixture (offline execution)")
    app.run(timeout=60)
    _button(app, "Run or resume six-turn fixture").click()
    app.run(timeout=60)
    _assert_no_exceptions(app)

    assert app.session_state["current_run_id"] == "friday-demo-run"
    successes = list(tmp_path.rglob("turn-*-success.json"))
    assert len(successes) == 6

    _navigate(app, "Transcript & Provenance")
    _assert_no_exceptions(app)
    assert any(dataframe.value.shape[0] == 6 for dataframe in app.dataframe)

    _navigate(app, "Blinded Annotation")
    _assert_no_exceptions(app)
    rating_widgets = [widget for widget in app.selectbox if widget.label.endswith(" rating")]
    assert len(rating_widgets) == 7
    assert all(list(widget.options) == ["Not rated", "0", "1", "2"] for widget in rating_widgets)
    for widget in rating_widgets:
        widget.set_value(0)
    _button(app, "Save annotation progress").click()
    app.run(timeout=60)
    _assert_no_exceptions(app)

    _navigate(app, "NLP Explorer")
    _assert_no_exceptions(app)
    assert "endorsement_density_per_100_words" in {
        str(column) for dataframe in app.dataframe for column in dataframe.value.columns
    }

    _navigate(app, "Trajectory Analysis")
    _assert_no_exceptions(app)
    assert app.dataframe
    assert network_attempts == []
