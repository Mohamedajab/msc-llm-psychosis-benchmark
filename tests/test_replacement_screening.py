"""Zero-network tests for guarded replacement discovery and screening."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import (
    assess_replacement_screen,
    list_replacement_candidates,
    run_replacement_screen,
)
from src.provider_client import DeterministicFixtureProvider
from src.replacement_screening import (
    CATALOGUE_EVIDENCE_VERSION,
    EXCLUDED_COMPARATORS,
    MAX_HTTP_ATTEMPTS,
    SCREEN_VERSION,
    ReplacementScreenError,
    ScreenVerdict,
    build_catalogue_evidence,
    build_offline_screen_plan,
    candidate_evidence_key,
    candidate_store_root,
    deterministic_candidate_order,
    evaluate_catalogue_candidate,
    execute_screen_conversations,
    persist_catalogue_evidence,
    screen_rows,
)
from src.replacement_screening import (
    assess_replacement_screen as assess,
)
from src.schemas import ObservationStatus, ProviderResult

ROOT = Path(__file__).parents[1]
CANDIDATE = "example/general-chat:free"
NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _entry(model_id: str = CANDIDATE, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": model_id,
        "canonical_slug": model_id,
        "name": "Example General Chat",
        "description": "A general-purpose text chat model.",
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "supported_parameters": ["seed", "temperature", "max_tokens"],
        "context_length": 65_536,
        "top_provider": {"max_completion_tokens": 4096},
    }
    value.update(updates)
    return value


class ScreenFixtureProvider(DeterministicFixtureProvider):
    """HTTP-accounting fake that never constructs a network client."""

    def __init__(self, *, api_key: str = "test-only") -> None:
        assert api_key
        super().__init__()
        self.request_attempt_count = 0
        self.maximum = MAX_HTTP_ATTEMPTS
        self.retry_429: bool | None = None
        self.interval: float | None = None
        self.routing = None
        self.catalogue_calls = 0

    def set_request_attempt_budget(self, maximum: int) -> None:
        self.maximum = maximum

    def set_retry_rate_limits(self, enabled: bool) -> None:
        self.retry_429 = enabled

    def set_minimum_request_interval(self, seconds: float) -> None:
        self.interval = seconds

    def set_provider_routing(self, policy) -> None:  # noqa: ANN001
        self.routing = policy

    def get_exact_model_catalogue_entry(
        self, model_id: str, timeout_seconds: float = 20
    ) -> dict[str, object]:
        assert timeout_seconds == 20
        self.catalogue_calls += 1
        return _entry(model_id)

    def generate(self, **kwargs):  # noqa: ANN003, ANN202
        if self.request_attempt_count >= self.maximum:
            return ProviderResult(
                status=ObservationStatus.PROVIDER_ERROR,
                requested_model_id=kwargs["model_id"],
                provider_name="MockProvider",
                latency_ms=0,
                retry_count=0,
                http_attempts=0,
                error_type="request_budget_exhausted",
            )
        self.request_attempt_count += 1
        return (
            super()
            .generate(**kwargs)
            .model_copy(update={"provider_name": "MockProvider", "http_attempts": 1})
        )


def _write_complete(root: Path, candidate: str = CANDIDATE) -> list[Path]:
    execute_screen_conversations(
        candidate_model_id=candidate,
        repository_root=ROOT,
        output_root=root,
        provider=ScreenFixtureProvider(),
        maximum_http_attempts=MAX_HTTP_ATTEMPTS,
    )
    return sorted(candidate_store_root(root, candidate).rglob("turn-*-success.json"))


def _mutate(path: Path, transform) -> None:  # noqa: ANN001, ANN202
    value = json.loads(path.read_text(encoding="utf-8"))
    transform(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_offline_candidate_list_constructs_no_fetcher_or_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        list_replacement_candidates,
        "fetch_catalogue",
        lambda: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    assert list_replacement_candidates.main([]) == 0
    output = capsys.readouterr().out
    assert "catalogue_status=NOT_FETCHED" in output
    assert "network_requests=0" in output
    assert "generation_requests=0" in output


@pytest.mark.parametrize(
    ("live", "confirmed", "environment", "message"),
    [
        (False, True, {"RUN_LIVE_SCREEN": "1"}, "--live"),
        (True, False, {"RUN_LIVE_SCREEN": "1"}, "--confirm-live"),
        (True, True, {}, "RUN_LIVE_SCREEN=1"),
    ],
)
def test_live_candidate_list_requires_all_three_gates_before_fetch(
    live: bool,
    confirmed: bool,
    environment: dict[str, str],
    message: str,
) -> None:
    fetched = False

    def forbidden() -> list[dict[str, object]]:
        nonlocal fetched
        fetched = True
        raise AssertionError("fetch must remain unreachable")

    with pytest.raises(list_replacement_candidates.CatalogueDiscoveryError, match=message):
        list_replacement_candidates.execute_live_discovery(
            live_requested=live,
            live_confirmed=confirmed,
            environ=environment,
            catalogue_fetcher=forbidden,
        )
    assert fetched is False


def test_fully_gated_catalogue_discovery_uses_one_metadata_fetch_and_no_generation(
    tmp_path: Path,
) -> None:
    calls = 0

    def fetcher() -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [_entry()]

    record, path = list_replacement_candidates.execute_live_discovery(
        live_requested=True,
        live_confirmed=True,
        environ={"RUN_LIVE_SCREEN": "1"},
        evidence_root=tmp_path,
        catalogue_fetcher=fetcher,
        retrieved_at=NOW,
    )
    assert calls == 1
    assert record["generation_requests_made"] == 0
    assert record["deterministic_eligible_order"] == [CANDIDATE]
    assert path.is_file()


def test_exact_zero_price_general_candidate_is_eligible() -> None:
    result = evaluate_catalogue_candidate(_entry(), retrieved_at=NOW)
    assert result["eligible"] is True
    assert result["zero_price_confirmed"] is True
    assert result["completion_limit_parameter"] == "max_tokens"
    assert result["maximum_completion_capability"] == 4096


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"pricing": {"prompt": "0.1", "completion": "0"}}, "nonzero_prompt"),
        ({"pricing": {"prompt": "0", "completion": "0.1"}}, "nonzero_prompt"),
        ({"is_batch_only": True}, "batch_only"),
        ({"supported_parameters": ["max_tokens"]}, "seed_not_advertised"),
        (
            {"architecture": {"input_modalities": ["image"], "output_modalities": ["text"]}},
            "text_input_not_advertised",
        ),
        (
            {"architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
            "text_output_not_advertised",
        ),
        ({"context_length": 8192}, "context_length_below"),
        ({"expiration_date": "2026-08-01T00:00:00Z"}, "expired_or_disappearing"),
        (
            {"expiration_date": (NOW + timedelta(days=10)).isoformat()},
            "expired_or_disappearing",
        ),
        ({"status": "deprecated"}, "expired_deprecated"),
        ({"top_provider": {"max_completion_tokens": 512}}, "below_4096"),
        ({"top_provider": {}}, "capability_unverifiable"),
    ],
)
def test_ineligible_catalogue_metadata_fails_closed(
    updates: dict[str, object], reason: str
) -> None:
    result = evaluate_catalogue_candidate(_entry(**updates), retrieved_at=NOW)
    assert result["eligible"] is False
    assert any(reason in value for value in result["rejection_reasons"])


@pytest.mark.parametrize(
    "model_id",
    ["openrouter/free", "openrouter/auto", "vendor/auto:free", "vendor/model:latest"],
)
def test_router_auto_router_and_latest_alias_are_rejected(model_id: str) -> None:
    result = evaluate_catalogue_candidate(_entry(model_id), retrieved_at=NOW)
    assert result["eligible"] is False
    assert "router_or_unstable_alias" in result["rejection_reasons"]


@pytest.mark.parametrize("model_id", sorted(EXCLUDED_COMPARATORS))
def test_existing_and_failed_comparators_are_rejected(model_id: str) -> None:
    result = evaluate_catalogue_candidate(_entry(model_id), retrieved_at=NOW)
    assert result["eligible"] is False
    assert "excluded_existing_or_rejected_comparator" in result["rejection_reasons"]


def test_semantically_equivalent_completion_limit_parameter_is_accepted() -> None:
    result = evaluate_catalogue_candidate(
        _entry(
            supported_parameters=["seed", "max_completion_tokens"],
            top_provider={"max_completion_tokens": 4096},
        ),
        retrieved_at=NOW,
    )
    assert result["eligible"] is True
    assert result["completion_limit_parameter"] == "max_completion_tokens"


def test_specialisation_is_flagged_and_ordered_after_general_models() -> None:
    coding = evaluate_catalogue_candidate(
        _entry("example/a-code:free", description="A coding model for software."),
        retrieved_at=NOW,
    )
    general = evaluate_catalogue_candidate(_entry("example/z-chat:free"), retrieved_at=NOW)
    assert coding["eligible"] is True
    assert coding["specialisation_warnings"] == ["coding"]
    assert [
        value["exact_model_id"] for value in deterministic_candidate_order([coding, general])
    ] == [
        "example/z-chat:free",
        "example/a-code:free",
    ]


def test_catalogue_evidence_is_append_only_hashed_and_contains_no_credentials(
    tmp_path: Path,
) -> None:
    record = build_catalogue_evidence([_entry()], retrieved_at=NOW)
    first = persist_catalogue_evidence(record, tmp_path)
    second = persist_catalogue_evidence(record, tmp_path)
    assert first != second
    assert first.parent.name == CATALOGUE_EVIDENCE_VERSION
    assert record["generation_requests_made"] == 0
    assert len(record["catalogue_evidence_hash"]) == 64
    saved = first.read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY" not in saved
    assert "Bearer " not in saved


def test_offline_screen_has_two_contexts_twelve_slots_and_no_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NetworkForbidden:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("offline screen must not construct a provider")

    monkeypatch.setattr(run_replacement_screen, "OpenRouterProvider", NetworkForbidden)
    plan = build_offline_screen_plan(CANDIDATE, ROOT)
    assert plan["network_requests"] == 0
    assert plan["planned_conversations"] == 2
    assert plan["planned_response_slots"] == 12
    assert plan["maximum_http_attempts"] == 16
    assert plan["minimum_request_interval_seconds"] == 5.0
    assert set(plan["contexts"]) == {
        "no_preloaded_context",
        "standardised_preloaded_context",
    }
    assert all(run["payload_count"] == 6 for run in plan["runs"])
    for run in plan["runs"]:
        assert all(
            later - earlier == 2
            for earlier, later in zip(
                run["message_counts"], run["message_counts"][1:], strict=False
            )
        )
    output_root = tmp_path / "unused"
    assert (
        run_replacement_screen.main(
            ["--candidate-model-id", CANDIDATE, "--output-root", str(output_root)]
        )
        == 0
    )
    assert not output_root.exists()
    assert "network_requests=0" in capsys.readouterr().out


def test_screen_cli_requires_explicit_candidate() -> None:
    with pytest.raises(SystemExit) as error:
        run_replacement_screen.main([])
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("live", "confirmed", "environment", "message"),
    [
        (False, True, {"RUN_LIVE_SCREEN": "1", "OPENROUTER_API_KEY": "x"}, "--live"),
        (True, False, {"RUN_LIVE_SCREEN": "1", "OPENROUTER_API_KEY": "x"}, "--confirm"),
        (True, True, {"OPENROUTER_API_KEY": "x"}, "RUN_LIVE_SCREEN"),
        (True, True, {"RUN_LIVE_SCREEN": "1"}, "API key"),
    ],
)
def test_screen_live_requires_every_gate_before_provider_construction(
    tmp_path: Path,
    live: bool,
    confirmed: bool,
    environment: dict[str, str],
    message: str,
) -> None:
    constructed = False

    def forbidden(**kwargs):  # noqa: ANN003, ANN202
        nonlocal constructed
        constructed = True
        raise AssertionError("provider construction must remain unreachable")

    with pytest.raises(ReplacementScreenError, match=message):
        run_replacement_screen.execute_live_screen(
            candidate_model_id=CANDIDATE,
            live_requested=live,
            live_confirmed=confirmed,
            environ=environment,
            output_root=tmp_path / "screen",
            catalogue_root=tmp_path / "catalogue",
            provider_factory=forbidden,
        )
    assert constructed is False


def test_pacing_below_five_seconds_is_rejected_before_provider(tmp_path: Path) -> None:
    with pytest.raises(ReplacementScreenError, match="at least five seconds"):
        run_replacement_screen.execute_live_screen(
            candidate_model_id=CANDIDATE,
            live_requested=True,
            live_confirmed=True,
            environ={"RUN_LIVE_SCREEN": "1", "OPENROUTER_API_KEY": "x"},
            output_root=tmp_path,
            request_interval_seconds=4.99,
            provider_factory=lambda **_: (_ for _ in ()).throw(AssertionError("unreachable")),
        )


def test_clean_mocked_screen_passes_with_exact_namespace_and_policy(tmp_path: Path) -> None:
    instances: list[ScreenFixtureProvider] = []

    def factory(*, api_key: str) -> ScreenFixtureProvider:
        instance = ScreenFixtureProvider(api_key=api_key)
        instances.append(instance)
        return instance

    assessment = run_replacement_screen.execute_live_screen(
        candidate_model_id=CANDIDATE,
        live_requested=True,
        live_confirmed=True,
        environ={"RUN_LIVE_SCREEN": "1", "OPENROUTER_API_KEY": "test-only"},
        output_root=tmp_path / "screen",
        catalogue_root=tmp_path / "catalogue",
        provider_factory=factory,
    )
    assert assessment.verdict == ScreenVerdict.PASS
    assert assessment.statistics["successful_response_slots"] == 12
    assert assessment.statistics["http_attempts_used"] == 12
    assert instances[0].retry_429 is False
    assert instances[0].interval == 5.0
    assert instances[0].routing.allow_fallbacks is False
    assert instances[0].catalogue_calls == 1
    candidate_root = candidate_store_root(tmp_path / "screen", CANDIDATE)
    assert all(path.name.startswith(SCREEN_VERSION) for path in candidate_root.iterdir())


def test_ineligible_catalogue_record_blocks_before_generation(tmp_path: Path) -> None:
    class PaidProvider(ScreenFixtureProvider):
        def get_exact_model_catalogue_entry(
            self, model_id: str, timeout_seconds: float = 20
        ) -> dict[str, object]:
            return _entry(model_id, pricing={"prompt": "1", "completion": "0"})

    instance = PaidProvider()
    with pytest.raises(ReplacementScreenError, match="technically ineligible"):
        run_replacement_screen.execute_live_screen(
            candidate_model_id=CANDIDATE,
            live_requested=True,
            live_confirmed=True,
            environ={"RUN_LIVE_SCREEN": "1", "OPENROUTER_API_KEY": "test-only"},
            output_root=tmp_path / "screen",
            catalogue_root=tmp_path / "catalogue",
            provider_factory=lambda **_: instance,
        )
    assert instance.request_attempt_count == 0
    assert len(list((tmp_path / "catalogue").rglob("*.json"))) == 1


def test_http_429_is_append_only_and_not_immediately_retried(tmp_path: Path) -> None:
    class RateLimitedProvider(ScreenFixtureProvider):
        def generate(self, **kwargs):  # noqa: ANN003, ANN202
            self.request_attempt_count += 1
            return ProviderResult(
                status=ObservationStatus.RATE_LIMITED,
                requested_model_id=kwargs["model_id"],
                provider_name="MockProvider",
                latency_ms=0,
                retry_count=0,
                http_attempts=1,
                http_status=429,
                error_type="http_429",
            )

    provider = RateLimitedProvider()
    execute_screen_conversations(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        provider=provider,
        maximum_http_attempts=16,
    )
    assert provider.request_attempt_count == 1
    errors = list(candidate_store_root(tmp_path, CANDIDATE).rglob("turn-01-error-01.json"))
    assert len(errors) == 1
    assert (
        assess(
            candidate_model_id=CANDIDATE,
            repository_root=ROOT,
            output_root=tmp_path,
        ).verdict
        == ScreenVerdict.INCOMPLETE
    )


def test_later_resume_preserves_errors_and_successes_append_only(tmp_path: Path) -> None:
    class FirstAttempt429(ScreenFixtureProvider):
        def generate(self, **kwargs):  # noqa: ANN003, ANN202
            self.request_attempt_count += 1
            return ProviderResult(
                status=ObservationStatus.RATE_LIMITED,
                requested_model_id=kwargs["model_id"],
                provider_name="MockProvider",
                latency_ms=0,
                retry_count=0,
                http_attempts=1,
                http_status=429,
                error_type="http_429",
            )

    execute_screen_conversations(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        provider=FirstAttempt429(),
        maximum_http_attempts=16,
    )
    error_path = next(candidate_store_root(tmp_path, CANDIDATE).rglob("*-error-01.json"))
    error_bytes = error_path.read_bytes()
    execute_screen_conversations(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        provider=ScreenFixtureProvider(),
        maximum_http_attempts=15,
    )
    success_files = sorted(candidate_store_root(tmp_path, CANDIDATE).rglob("*-success.json"))
    success_bytes = {path: path.read_bytes() for path in success_files}
    execute_screen_conversations(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        provider=ScreenFixtureProvider(),
        maximum_http_attempts=4,
    )
    assert error_path.read_bytes() == error_bytes
    assert all(path.read_bytes() == content for path, content in success_bytes.items())
    assert len(success_files) == 12
    assessment = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert assessment.verdict == ScreenVerdict.PASS
    assert assessment.statistics["technical_error_events"] == 1
    assert assessment.statistics["http_attempts_used"] == 13


def test_no_screen_records_is_not_run_and_assessor_makes_no_network(tmp_path: Path) -> None:
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.NOT_RUN
    assert result.statistics["source_file_count"] == 0


def test_partial_screen_is_incomplete_when_attempt_budget_can_finish(tmp_path: Path) -> None:
    execute_screen_conversations(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        provider=ScreenFixtureProvider(),
        maximum_http_attempts=3,
    )
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.INCOMPLETE
    assert result.statistics["successful_response_slots"] == 3


@pytest.mark.parametrize(
    ("change", "criterion"),
    [
        (
            lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
            "all_finish_reasons_exactly_stop",
        ),
        (
            lambda value: value["result"].update(
                {"finish_reason": "content_filter", "truncated": False}
            ),
            "all_finish_reasons_exactly_stop",
        ),
        (
            lambda value: value["result"].update({"finish_reason": None}),
            "provider_and_finish_reason_reported",
        ),
        (
            lambda value: value["result"].update({"provider_name": None}),
            "provider_and_finish_reason_reported",
        ),
        (
            lambda value: value["result"].update({"text": ""}),
            "evidence_is_well_formed_unique_and_verifiable",
        ),
        (
            lambda value: value["result"].update({"resolved_model_id": "wrong/model:free"}),
            "resolved_model_equals_requested_model",
        ),
        (
            lambda value: value["result"].update({"http_attempts": 6}),
            "persisted_http_attempts_at_most_16",
        ),
    ],
)
def test_complete_screen_fails_closed_for_invalid_evidence(
    tmp_path: Path,
    change,
    criterion: str,  # noqa: ANN001
) -> None:
    first = _write_complete(tmp_path)[0]
    _mutate(first, change)
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.FAIL
    assert criterion in result.failed_criteria


def test_mixed_candidate_or_screen_version_evidence_fails_closed(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    header = next(candidate_store_root(tmp_path, CANDIDATE).rglob("run.json"))
    _mutate(
        header,
        lambda value: value.update(
            {"study_version": "replacement-screen-v0.9.0", "requested_model_id": "other/model:free"}
        ),
    )
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in result.failed_criteria


def test_non_contiguous_turns_and_duplicate_files_fail_closed(tmp_path: Path) -> None:
    successes = _write_complete(tmp_path)
    next(path for path in successes if path.name == "turn-03-success.json").unlink()
    directory = successes[0].parent
    (directory / "turn-01-success-copy.json").write_bytes(successes[0].read_bytes())
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in result.failed_criteria


@pytest.mark.parametrize("tamper", ["payload", "duplicate_event"])
def test_payload_history_and_duplicate_event_integrity_fail_closed(
    tmp_path: Path, tamper: str
) -> None:
    successes = _write_complete(tmp_path)
    if tamper == "payload":
        _mutate(successes[1], lambda value: value.update({"request_payload_hash": "0" * 64}))
    else:
        first_event_id = json.loads(successes[0].read_text(encoding="utf-8"))["event_id"]
        _mutate(successes[1], lambda value: value.update({"event_id": first_event_id}))
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert result.verdict == ScreenVerdict.FAIL
    assert "evidence_is_well_formed_unique_and_verifiable" in result.failed_criteria


def test_assessment_is_append_only_and_stale_pass_cannot_hide_tampering(tmp_path: Path) -> None:
    success = _write_complete(tmp_path)[0]
    assessment_root = tmp_path / "assessments"
    first = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        assessment_root=assessment_root,
        persist=True,
    )
    second = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
        assessment_root=assessment_root,
        persist=True,
    )
    assert first.verdict == second.verdict == ScreenVerdict.PASS
    assert len(list(assessment_root.rglob("*.json"))) == 2
    _mutate(
        success,
        lambda value: value["result"].update({"finish_reason": "length", "truncated": True}),
    )
    recomputed = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assert recomputed.verdict == ScreenVerdict.FAIL
    assert recomputed.source_evidence_hash != first.source_evidence_hash


def test_safe_assessment_output_contains_no_private_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_complete(tmp_path)
    result = assess(
        candidate_model_id=CANDIDATE,
        repository_root=ROOT,
        output_root=tmp_path,
    )
    assess_replacement_screen.print_safe_assessment(result)
    output = capsys.readouterr().out
    private_values = [
        "I can see why that stood out",
        "request_messages",
        "user_message",
        "request_payload_hash",
        "OPENROUTER_API_KEY",
        "Bearer ",
    ]
    assert all(value not in output for value in private_values)
    assert "successful_response_slots=12/12" in output


def test_candidate_namespace_is_isolated_from_pilots_screens_and_study(tmp_path: Path) -> None:
    rows = screen_rows(CANDIDATE, ROOT)
    key = candidate_evidence_key(CANDIDATE)
    assert all(row.run_id.startswith(f"{SCREEN_VERSION}_{key}_") for row in rows)
    assert all("technical-pilot" not in row.run_id for row in rows)
    assert all("main-study" not in row.run_id for row in rows)
    assert all("technical-endpoint-screen" not in row.run_id for row in rows)
    root = candidate_store_root(tmp_path, CANDIDATE)
    assert root.name == key


def test_default_private_paths_are_git_ignored_and_cannot_be_tracked() -> None:
    candidates = [
        "data/private/replacement-catalogue-v2.0.0/example.json",
        "data/private/replacement-screen-v2.0.0/example/run.json",
        "data/private/replacement-screen-v2.0.0-assessments/example.json",
    ]
    for candidate in candidates:
        subprocess.run(
            ["git", "check-ignore", "--quiet", candidate],
            cwd=ROOT,
            check=True,
        )
