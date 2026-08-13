"""Generate deterministic, offline demo conversations and annotation fixtures.

The generator deliberately exercises the production ``ConversationRunner`` with
the production ``DeterministicFixtureProvider``.  Runtime-only values (UUIDs,
timestamps and measured local latency) are then canonicalised so the tracked
fixture is byte-for-byte reproducible.  Every output is labelled
``DEMO FIXTURE - NOT RESEARCH DATA``.
"""

# The executable-path bootstrap must precede local ``src`` imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.annotation import build_blinded_items, save_blinded_items, save_blinding_map
from src.config_loader import canonical_hash, load_histories, load_models, load_scripts
from src.conversation_runner import ConversationRunner, create_run_header
from src.provider_client import DeterministicFixtureProvider
from src.schemas import AnnotationEvent, AxisScores, ContextCondition
from src.storage import RawRunStore, atomic_write_json

DEMO_BANNER = "DEMO FIXTURE - NOT RESEARCH DATA"
DEMO_VERSION = "demo-fixture-v1.0.0"
DEMO_SCRIPT_ID = "monitoring_fixed_belief_v1"
DEMO_BASE_TIME = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
DEMO_BLINDING_KEY = "local-deterministic-demo-blinding-key-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "demo"

FIXTURE_MODELS: tuple[tuple[str, str, str], ...] = (
    ("fixture_safe", "fixture/safe-v1", "safe"),
    ("fixture_risk_prone", "fixture/risk-prone-v1", "risk_prone"),
)
DEMO_CONDITIONS: tuple[ContextCondition, ...] = (
    ContextCondition.NO_PRELOADED_CONTEXT,
    ContextCondition.STANDARDISED_PRELOADED_CONTEXT,
)


def _stable_digest(*parts: object, length: int = 24) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def _atomic_write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _load_demo_configuration() -> tuple[Any, Any, Any, str]:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    script = next(item for item in scripts if item.script_id == DEMO_SCRIPT_ID)
    prefix = next(item for item in histories if item.history_id == script.history_id)
    digest = canonical_hash(
        {
            "demo_version": DEMO_VERSION,
            "script": script.model_dump(mode="json"),
            "prefix": prefix.model_dump(mode="json"),
            "generation": models.generation.model_dump(mode="json"),
            "fixture_models": FIXTURE_MODELS,
        }
    )
    return script, prefix, models, digest


def _run_id(model_slot: str, condition: ContextCondition) -> str:
    return f"{DEMO_VERSION}_{DEMO_SCRIPT_ID}_{model_slot}_{condition.value}"


def _canonical_record(record: Any, *, run_index: int) -> Any:
    """Remove nondeterministic machine-runtime values from a fixture record."""

    run_time = DEMO_BASE_TIME + timedelta(minutes=run_index)
    header = record.header.model_copy(update={"created_at": run_time})
    turns = []
    for event in record.turns:
        request_time = run_time + timedelta(seconds=(event.turn_number * 2) - 1)
        response_time = request_time + timedelta(milliseconds=100)
        result = event.result.model_copy(update={"latency_ms": 0.0})
        turns.append(
            event.model_copy(
                update={
                    "event_id": "demo_" + _stable_digest(record.header.run_id, event.turn_number),
                    "request_timestamp": request_time,
                    "response_timestamp": response_time,
                    "result": result,
                }
            )
        )
    completed_at = turns[-1].response_timestamp if turns else None
    return record.model_copy(
        update={"header": header, "turns": tuple(turns), "completed_at": completed_at}
    )


def _write_raw_layout(root: Path, record: Any) -> None:
    run_root = root / "raw" / record.header.run_id
    atomic_write_json(run_root / "run.json", record.header.model_dump(mode="json"), overwrite=True)
    for event in record.turns:
        atomic_write_json(
            run_root / f"turn-{event.turn_number:02d}-success.json",
            event.model_dump(mode="json"),
            overwrite=True,
        )


def _scores(profile: str, turn_number: int) -> AxisScores:
    index = turn_number - 1
    if profile == "safe":
        safety = (1, 1, 1, 2, 2, 2)[index]
        return AxisScores(
            A1=0,
            A2=0,
            A3=safety,
            B1=0,
            B2=0,
            B3=0,
            C1=safety,
        )
    return AxisScores(
        A1=(1, 1, 2, 2, 2, 2)[index],
        A2=(0, 0, 0, 1, 1, 2)[index],
        A3=0,
        B1=(1, 1, 2, 2, 2, 2)[index],
        B2=(0, 1, 1, 2, 2, 2)[index],
        B3=(0, 0, 1, 1, 1, 2)[index],
        C1=0,
    )


def _annotation_fixtures(
    output_root: Path,
    records: list[Any],
    profiles_by_run: dict[str, str],
) -> tuple[list[AnnotationEvent], list[dict[str, Any]]]:
    items, mapping = build_blinded_items(records, blinding_key=DEMO_BLINDING_KEY)
    save_blinded_items(output_root / "blinded_items.json", items, overwrite=True)
    save_blinding_map(output_root / "blinding_map.json", mapping, overwrite=True)

    item_by_id = {item.blinded_item_id: item for item in items}
    record_by_id = {record.header.run_id: record for record in records}
    events: list[AnnotationEvent] = []
    trajectory_rows: list[dict[str, Any]] = []
    for position, entry in enumerate(mapping, start=1):
        item = item_by_id[entry.blinded_item_id]
        record = record_by_id[entry.run_id]
        profile = profiles_by_run[entry.run_id]
        scores = _scores(profile, entry.turn_number)
        event = AnnotationEvent(
            annotation_id="demo_ann_" + _stable_digest(entry.blinded_item_id),
            blinded_item_id=entry.blinded_item_id,
            annotator_id="demo_fixture_annotator",
            scores=scores,
            notes=f"{DEMO_BANNER}; deterministic synthetic annotation fixture.",
            uncertain_adjudication_needed=False,
            source_response_hash=item.source_response_hash,
            saved_at=DEMO_BASE_TIME + timedelta(hours=2, seconds=position),
        )
        events.append(event)
        turn = next(value for value in record.turns if value.turn_number == entry.turn_number)
        trajectory_rows.append(
            {
                "data_status": "demo_fixture",
                "display_label": DEMO_BANNER,
                "run_id": entry.run_id,
                "script_id": record.header.script_id,
                "theme": record.header.theme.value,
                "presentation_level": record.header.presentation_level.value,
                "model_slot": record.header.model_slot,
                "fixture_profile": profile,
                "context_condition": record.header.context_condition.value,
                "repetition": record.header.repetition,
                "turn_number": entry.turn_number,
                "response_text": turn.result.text,
                "source_response_hash": item.source_response_hash,
                **scores.model_dump(),
            }
        )

    jsonl = "".join(event.model_dump_json() + "\n" for event in events)
    _atomic_write_text(output_root / "annotations.jsonl", jsonl)

    columns = list(trajectory_rows[0]) if trajectory_rows else []
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trajectory_rows)
        handle.seek(0)
        csv_text = handle.read()
    _atomic_write_text(output_root / "trajectory_annotations.csv", csv_text)
    return events, trajectory_rows


def generate_demo(output_root: str | Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    """Generate four complete offline fixture conversations and annotations."""

    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    script, prefix, models, configuration_hash = _load_demo_configuration()

    records: list[Any] = []
    profiles_by_run: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="msc-demo-runner-") as temporary:
        temporary_store = RawRunStore(Path(temporary) / "raw")
        for run_index, (model_slot, model_id, profile, condition) in enumerate(
            ((*model, condition) for model in FIXTURE_MODELS for condition in DEMO_CONDITIONS),
            start=1,
        ):
            run_id = _run_id(model_slot, condition)
            header = create_run_header(
                study_version=DEMO_VERSION,
                run_id=run_id,
                data_status="demo_fixture",
                script=script,
                condition=condition,
                model_slot=model_slot,
                model_id=model_id,
                repetition=1,
                generation=models.generation,
                configuration_version=DEMO_VERSION,
                configuration_hash=configuration_hash,
            ).model_copy(update={"created_at": DEMO_BASE_TIME + timedelta(minutes=run_index)})
            provider = DeterministicFixtureProvider(profile=profile)
            record = ConversationRunner(provider, temporary_store).run_or_resume(
                header=header, script=script, prefix=prefix
            )
            if len(provider.calls) != 6 or len(record.turns) != 6:
                raise RuntimeError(
                    f"Demo fixture {run_id} did not complete exactly six offline calls"
                )
            canonical = _canonical_record(record, run_index=run_index)
            records.append(canonical)
            profiles_by_run[run_id] = profile
            _write_raw_layout(destination, canonical)

    records.sort(key=lambda value: value.header.run_id)
    atomic_write_json(
        destination / "conversations.json",
        [record.model_dump(mode="json") for record in records],
        overwrite=True,
    )
    events, trajectory_rows = _annotation_fixtures(destination, records, profiles_by_run)

    manifest = {
        "fixture_version": DEMO_VERSION,
        "data_status": "demo_fixture",
        "display_label": DEMO_BANNER,
        "network_called": False,
        "script_id": DEMO_SCRIPT_ID,
        "conversation_count": len(records),
        "response_count": sum(len(record.turns) for record in records),
        "annotation_count": len(events),
        "configuration_hash": configuration_hash,
        "files": {
            "combined_conversations": "conversations.json",
            "raw_run_root": "raw",
            "blinded_items": "blinded_items.json",
            "internal_blinding_map": "blinding_map.json",
            "annotation_events": "annotations.jsonl",
            "trajectory_annotations": "trajectory_annotations.csv",
        },
        "runs": [
            {
                "run_id": record.header.run_id,
                "model_slot": record.header.model_slot,
                "fixture_profile": profiles_by_run[record.header.run_id],
                "context_condition": record.header.context_condition.value,
                "turn_count": len(record.turns),
            }
            for record in records
        ],
        "limitations": [
            "All responses and annotations are deterministic synthetic fixtures.",
            "These values demonstrate workflow behaviour and are not dissertation evidence.",
            "The fixture is not a clinical or psychometric validation dataset.",
        ],
    }
    atomic_write_json(destination / "manifest.json", manifest, overwrite=True)
    if len(trajectory_rows) != 24:
        raise RuntimeError("Demo trajectory fixture must contain exactly 24 responses")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic offline demo fixtures (never uses the network)."
    )
    parser.add_argument(
        "--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Fixture directory"
    )
    arguments = parser.parse_args(argv)
    manifest = generate_demo(arguments.output_root)
    print(DEMO_BANNER)
    print(
        f"Generated {manifest['conversation_count']} conversations / "
        f"{manifest['response_count']} responses with network_called=false"
    )
    print(arguments.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
