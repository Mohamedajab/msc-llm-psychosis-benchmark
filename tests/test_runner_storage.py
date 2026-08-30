"""Dry-run, resume, immutable raw evidence, and secret exclusion tests."""

from pathlib import Path

from src.config_loader import (
    configuration_bundle_hash,
    load_histories,
    load_models,
    load_scripts,
)
from src.conversation_runner import ConversationRunner, create_run_header
from src.provider_client import DeterministicFixtureProvider, TargetProvider
from src.schemas import ContextCondition, ObservationStatus, ProviderResult
from src.storage import RawRunStore

ROOT = Path(__file__).parents[1]


def _inputs(tmp_path: Path, run_id: str = "test-run"):
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    script = next(item for item in scripts if item.script_id == "monitoring_control_v1")
    prefix = next(item for item in histories if item.history_id == script.history_id)
    header = create_run_header(
        study_version="test-study",
        run_id=run_id,
        data_status="demo_fixture",
        script=script,
        condition=ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
        model_slot="fixture_safe",
        model_id="fixture/safe",
        repetition=1,
        generation=models.generation.model_copy(
            update={"completion_limit_parameter": "max_tokens"}
        ),
        configuration_version="test-config",
        configuration_hash=configuration_bundle_hash(scripts, histories, models),
    )
    return script, prefix, header, RawRunStore(tmp_path / "raw")


def test_dry_run_makes_no_provider_calls(tmp_path: Path) -> None:
    script, prefix, header, store = _inputs(tmp_path)
    provider = DeterministicFixtureProvider()
    payloads = ConversationRunner(provider, store).dry_run(
        header=header, script=script, prefix=prefix
    )
    assert len(payloads) == 6
    assert provider.calls == []
    assert all(payload["network_called"] is False for payload in payloads)


class FailOnceAfterTwo(TargetProvider):
    provider_name = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.failed = False

    def generate(self, *, model_id, messages, generation):
        del messages, generation
        self.calls += 1
        if self.calls == 3 and not self.failed:
            self.failed = True
            return ProviderResult(
                status=ObservationStatus.TRANSPORT_ERROR,
                requested_model_id=model_id,
                provider_name="test",
                latency_ms=1,
                retry_count=0,
                error_type="forced",
                error_message="forced transient failure",
            )
        return ProviderResult(
            status=ObservationStatus.RESPONSE,
            text=f"answer-{self.calls}",
            requested_model_id=model_id,
            resolved_model_id=model_id,
            provider_name="test",
            latency_ms=1,
            retry_count=0,
        )


def test_resume_does_not_duplicate_successful_turns(tmp_path: Path) -> None:
    script, prefix, header, store = _inputs(tmp_path, "resume-test")
    provider = FailOnceAfterTwo()
    runner = ConversationRunner(provider, store)
    partial = runner.run_or_resume(header=header, script=script, prefix=prefix)
    assert len(partial.turns) == 2
    first_two_paths = [
        store.run_directory(header.run_id) / f"turn-{n:02d}-success.json" for n in (1, 2)
    ]
    before = [path.read_bytes() for path in first_two_paths]
    complete = runner.run_or_resume(header=header, script=script, prefix=prefix)
    assert len(complete.turns) == 6
    assert [path.read_bytes() for path in first_two_paths] == before
    assert provider.calls == 7
    assert len(list(store.run_directory(header.run_id).glob("turn-*-success.json"))) == 6


def test_raw_records_never_contain_api_keys(tmp_path: Path, monkeypatch) -> None:
    secret = "sk-or-secret-marker"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    script, prefix, header, store = _inputs(tmp_path, "secret-test")
    ConversationRunner(DeterministicFixtureProvider(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in store.run_directory(header.run_id).glob("*.json")
    )
    assert secret not in combined


def test_successful_turn_file_cannot_be_overwritten(tmp_path: Path) -> None:
    script, prefix, header, store = _inputs(tmp_path, "immutable-success")
    record = ConversationRunner(DeterministicFixtureProvider(), store).run_or_resume(
        header=header, script=script, prefix=prefix
    )
    first = record.turns[0]
    path = store.run_directory(header.run_id) / "turn-01-success.json"
    original = path.read_bytes()
    try:
        store.append_success(first)
    except FileExistsError:
        pass
    else:  # pragma: no cover - a regression must make this fail loudly
        raise AssertionError("Successful raw evidence was unexpectedly overwritten")
    assert path.read_bytes() == original
