"""Append-only raw evidence storage and reproducible record loading."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from src.schemas import ConversationRecord, ErrorEvent, RunHeader, RunStatus, TurnEvent

SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
RawEvent = TurnEvent | ErrorEvent
RAW_EVENT_ADAPTER = TypeAdapter(RawEvent)


def safe_filename(value: str) -> str:
    cleaned = SAFE_NAME_PATTERN.sub("-", value).strip("-._")
    if not cleaned:
        raise ValueError("Identifier does not contain filename-safe characters")
    return cleaned[:180]


def atomic_write_json(path: Path, value: Any, *, overwrite: bool = False) -> Path:
    """Write complete JSON atomically; successful evidence is exclusive by default.

    For immutable files, an atomic hard-link publishes the completed temporary
    file and fails if the destination already exists.  This avoids the small
    check-then-replace race that could otherwise overwrite evidence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"File already exists and was not overwritten: {path}")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise FileExistsError(
                    f"File already exists and was not overwritten: {path}"
                ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return path


class RawRunStore:
    """One immutable run header plus exclusive per-turn event files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_directory(self, run_id: str) -> Path:
        return self.root / safe_filename(run_id)

    def initialise(self, header: RunHeader) -> Path:
        run_directory = self.run_directory(header.run_id)
        run_directory.mkdir(parents=True, exist_ok=True)
        header_path = run_directory / "run.json"
        if header_path.exists():
            existing = RunHeader.model_validate_json(header_path.read_text(encoding="utf-8"))
            if existing != header:
                raise FileExistsError(
                    f"Run {header.run_id} already exists with different immutable metadata"
                )
            return run_directory
        atomic_write_json(header_path, header.model_dump(mode="json"))
        return run_directory

    def append_success(self, event: TurnEvent) -> Path:
        run_directory = self.run_directory(event.run_id)
        if not (run_directory / "run.json").is_file():
            raise FileNotFoundError(f"Run header does not exist for {event.run_id}")
        path = run_directory / f"turn-{event.turn_number:02d}-success.json"
        return atomic_write_json(path, event.model_dump(mode="json"))

    def append_error(self, event: ErrorEvent) -> Path:
        run_directory = self.run_directory(event.run_id)
        sequence = 1
        while True:
            path = run_directory / f"turn-{event.turn_number:02d}-error-{sequence:02d}.json"
            try:
                return atomic_write_json(path, event.model_dump(mode="json"))
            except FileExistsError:
                # Another writer may have claimed the sequence after our scan.
                pass
            sequence += 1

    def successful_turns(self, run_id: str) -> list[TurnEvent]:
        events = [
            TurnEvent.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.run_directory(run_id).glob("turn-*-success.json"))
        ]
        numbers = [event.turn_number for event in events]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"Successful turns for {run_id} are non-contiguous: {numbers}")
        return events

    def error_events(self, run_id: str) -> list[ErrorEvent]:
        return [
            ErrorEvent.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.run_directory(run_id).glob("turn-*-error-*.json"))
        ]

    def load(self, run_id: str) -> ConversationRecord:
        run_directory = self.run_directory(run_id)
        header = RunHeader.model_validate_json(
            (run_directory / "run.json").read_text(encoding="utf-8")
        )
        turns = self.successful_turns(run_id)
        errors = self.error_events(run_id)
        if len(turns) == 6:
            status = RunStatus.COMPLETED
            completed_at = turns[-1].response_timestamp
        elif errors:
            status = RunStatus.PARTIAL if turns else RunStatus.FAILED
            completed_at = None
        elif turns:
            status = RunStatus.PARTIAL
            completed_at = None
        else:
            status = RunStatus.PLANNED
            completed_at = None
        return ConversationRecord(
            header=header,
            turns=tuple(turns),
            errors=tuple(errors),
            status=status,
            completed_at=completed_at,
        )

    def list_run_ids(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and (path / "run.json").is_file()
        )

    def export_record(self, run_id: str, destination: str | Path) -> Path:
        record = self.load(run_id)
        return atomic_write_json(Path(destination), record.model_dump(mode="json"), overwrite=False)
