"""Offline tests for governed, content-blind replacement selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import select_replacement_candidate
from src.provider_client import DeterministicFixtureProvider
from src.replacement_screening import (
    MAX_HTTP_ATTEMPTS,
    ScreenVerdict,
    assess_replacement_screen,
    build_catalogue_evidence,
    candidate_store_root,
    execute_screen_conversations,
    persist_catalogue_evidence,
)
from src.replacement_selection import (
    SELECTION_POLICY_VERSION,
    ReplacementSelectionError,
    SelectionStatus,
    create_replacement_selection,
    determine_replacement_selection,
    validate_replacement_selection_record,
)
from src.schemas import ObservationStatus, ProviderResult

ROOT = Path(__file__).parents[1]
FIRST = "example/a-general:free"
SECOND = "example/b-general:free"
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _entry(model_id: str) -> dict[str, object]:
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": model_id,
        "description": "General purpose text assistant.",
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "supported_parameters": ["seed", "max_tokens", "temperature"],
        "context_length": 65_536,
        "top_provider": {"max_completion_tokens": 4096},
    }


def _catalogue(tmp_path: Path, candidates: tuple[str, ...] = (FIRST, SECOND)) -> Path:
    record = build_catalogue_evidence([_entry(value) for value in candidates], retrieved_at=NOW)
    return persist_catalogue_evidence(record, tmp_path / "catalogue")


class SelectionFixtureProvider(DeterministicFixtureProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_attempt_count = 0
        self.maximum = MAX_HTTP_ATTEMPTS

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        if self.request_attempt_count >= self.maximum:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=kwargs["model_id"],
                latency_ms=0,
                retry_count=0,
                http_attempts=0,
                error_type="request_budget_exhausted",
            )
        self.request_attempt_count += 1
        return (
            super()
            .generate(**kwargs)
            .model_copy(update={"provider_name": "SyntheticProvider", "http_attempts": 1})
        )


def _complete_screen(root: Path, candidate: str) -> None:
    execute_screen_conversations(
        candidate_model_id=candidate,
        repository_root=ROOT,
        output_root=root,
        provider=SelectionFixtureProvider(),
        maximum_http_attempts=MAX_HTTP_ATTEMPTS,
        completion_limit_parameter="max_tokens",
    )
    assert (
        assess_replacement_screen(
            candidate_model_id=candidate,
            repository_root=ROOT,
            output_root=root,
        ).verdict
        == ScreenVerdict.PASS
    )


def _mutate(path: Path, transform) -> None:  # noqa: ANN001, ANN202
    value = json.loads(path.read_text(encoding="utf-8"))
    transform(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_current_default_command_is_not_selected_and_zero_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert select_replacement_candidate.main([]) == 0
    output = capsys.readouterr().out
    assert "replacement_selection=NOT_SELECTED" in output
    assert "network_requests=0" in output
    assert not list(tmp_path.rglob("*.json"))


def test_missing_or_incomplete_first_candidate_blocks_selection(tmp_path: Path) -> None:
    catalogue = _catalogue(tmp_path)
    missing = determine_replacement_selection(
        catalogue_record_path=catalogue,
        screen_output_root=tmp_path / "screens",
        repository_root=ROOT,
    )
    assert missing.status == SelectionStatus.BLOCKED
    assert missing.blocker == "earlier_candidate_not_run"

    execute_screen_conversations(
        candidate_model_id=FIRST,
        repository_root=ROOT,
        output_root=tmp_path / "screens",
        provider=SelectionFixtureProvider(),
        maximum_http_attempts=2,
        completion_limit_parameter="max_tokens",
    )
    incomplete = determine_replacement_selection(
        catalogue_record_path=catalogue,
        screen_output_root=tmp_path / "screens",
        repository_root=ROOT,
    )
    assert incomplete.status == SelectionStatus.BLOCKED
    assert incomplete.blocker == "earlier_candidate_incomplete"


def test_first_clean_pass_is_the_only_selectable_candidate(tmp_path: Path) -> None:
    catalogue = _catalogue(tmp_path)
    screens = tmp_path / "screens"
    _complete_screen(screens, FIRST)
    _complete_screen(screens, SECOND)
    decision = determine_replacement_selection(
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
    )
    assert decision.status == SelectionStatus.SELECTABLE
    assert decision.selected_model_id == FIRST
    assert decision.candidate_screen_verdicts == {FIRST: "PASS"}
    assert decision.selection_policy_version == SELECTION_POLICY_VERSION
    assert len(decision.candidate_ordering_hash) == 64

    with pytest.raises(ReplacementSelectionError, match="not the first technical PASS"):
        create_replacement_selection(
            candidate_model_id=SECOND,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            repository_root=ROOT,
            selection_root=tmp_path / "selections",
        )


def test_retained_failure_advances_to_next_candidate_under_frozen_order(
    tmp_path: Path,
) -> None:
    catalogue = _catalogue(tmp_path)
    screens = tmp_path / "screens"
    _complete_screen(screens, FIRST)
    first_success = next(candidate_store_root(screens, FIRST).rglob("turn-*-success.json"))
    _mutate(
        first_success,
        lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
    )
    assert (
        assess_replacement_screen(
            candidate_model_id=FIRST,
            repository_root=ROOT,
            output_root=screens,
        ).verdict
        == ScreenVerdict.FAIL
    )
    _complete_screen(screens, SECOND)
    decision = determine_replacement_selection(
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
    )
    assert decision.selected_model_id == SECOND
    assert decision.candidate_screen_verdicts == {FIRST: "FAIL", SECOND: "PASS"}


def test_selection_record_is_append_only_idempotent_and_recomputed(tmp_path: Path) -> None:
    catalogue = _catalogue(tmp_path, (FIRST,))
    screens = tmp_path / "screens"
    selections = tmp_path / "selections"
    _complete_screen(screens, FIRST)
    first, first_path = create_replacement_selection(
        candidate_model_id=FIRST,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
        selection_root=selections,
        selected_at=NOW,
    )
    second, second_path = create_replacement_selection(
        candidate_model_id=FIRST,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
        selection_root=selections,
        selected_at=NOW,
    )
    assert first == second
    assert first_path == second_path
    assert len(list(selections.glob("*.json"))) == 1
    assert first.response_content_consulted is False
    assert first.substantive_outcome_used is False
    assert first.completion_limit_parameter == "max_tokens"
    assert (
        validate_replacement_selection_record(
            selection_record_path=first_path,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            repository_root=ROOT,
        )
        == first
    )


def test_selection_freezes_catalogue_verified_completion_translation(tmp_path: Path) -> None:
    entry = _entry(FIRST)
    entry["supported_parameters"] = ["seed", "max_completion_tokens", "temperature"]
    catalogue = persist_catalogue_evidence(
        build_catalogue_evidence([entry], retrieved_at=NOW), tmp_path / "catalogue"
    )
    screens = tmp_path / "screens"
    execute_screen_conversations(
        candidate_model_id=FIRST,
        repository_root=ROOT,
        output_root=screens,
        provider=SelectionFixtureProvider(),
        maximum_http_attempts=MAX_HTTP_ATTEMPTS,
        completion_limit_parameter="max_completion_tokens",
    )
    record, _ = create_replacement_selection(
        candidate_model_id=FIRST,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
        selection_root=tmp_path / "selections",
        selected_at=NOW,
    )
    assert record.completion_limit_parameter == "max_completion_tokens"


def test_tampered_catalogue_order_or_selection_record_fails_closed(tmp_path: Path) -> None:
    catalogue = _catalogue(tmp_path, (FIRST,))
    screens = tmp_path / "screens"
    _complete_screen(screens, FIRST)
    record, selection_path = create_replacement_selection(
        candidate_model_id=FIRST,
        catalogue_record_path=catalogue,
        screen_output_root=screens,
        repository_root=ROOT,
        selection_root=tmp_path / "selections",
        selected_at=NOW,
    )
    assert record.selected_model_id == FIRST
    _mutate(selection_path, lambda value: value.update({"selected_model_id": SECOND}))
    with pytest.raises(ReplacementSelectionError, match="stale, mismatched"):
        validate_replacement_selection_record(
            selection_record_path=selection_path,
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            repository_root=ROOT,
        )

    _mutate(
        catalogue,
        lambda value: value.update({"deterministic_eligible_order": [SECOND, FIRST]}),
    )
    with pytest.raises(ReplacementSelectionError, match="stale or tampered"):
        determine_replacement_selection(
            catalogue_record_path=catalogue,
            screen_output_root=screens,
            repository_root=ROOT,
        )


def test_selection_output_and_record_contain_no_substantive_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalogue = _catalogue(tmp_path, (FIRST,))
    screens = tmp_path / "screens"
    _complete_screen(screens, FIRST)
    code = select_replacement_candidate.main(
        [
            "--select",
            "--confirm-selection",
            "--candidate-model-id",
            FIRST,
            "--catalogue-record",
            str(catalogue),
            "--screen-output-root",
            str(screens),
            "--selection-root",
            str(tmp_path / "selections"),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    private_markers = (
        "I can see why that stood out",
        "request_messages",
        "request_payload_hash",
        "user_message",
        "response_text",
        "OPENROUTER_API_KEY",
    )
    assert all(value not in output for value in private_markers)
    saved = next((tmp_path / "selections").glob("*.json")).read_text(encoding="utf-8")
    assert all(value not in saved for value in private_markers)
