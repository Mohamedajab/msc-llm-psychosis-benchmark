"""Generate and verify the non-sensitive frozen Study V2 protocol bundle."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_models

BUNDLE_ROOT = ROOT / "protocol" / "study-v2.0.0"
METADATA_PATH = BUNDLE_ROOT / "bundle.json"
STUDY_VERSION = "study-v2.0.0"
INCLUDED_PATHS = (
    "config/models.yaml",
    "config/archive/models-study-v2-generation-v2.yaml",
    "config/rubric.yaml",
    "outputs/experiment_manifest.csv",
    "outputs/data_dictionary.csv",
    "docs/RESEARCH_PROTOCOL.md",
    "docs/PROVIDER_POLICY.md",
    "docs/EXECUTION_POLICY.md",
    "docs/PROTOCOL_DEVIATION_STUDY_V2.md",
    "src/config_loader.py",
    "src/conversation_runner.py",
    "src/manifest.py",
    "src/payloads.py",
    "src/provider_client.py",
    "src/pilot_qualification.py",
    "src/schemas.py",
    "src/storage.py",
    "src/study_execution.py",
    "scripts/run_pilot_v4.py",
    "scripts/assess_pilot_v4.py",
    "scripts/audit_pilot_v4.py",
    "scripts/run_pilot_v5.py",
    "scripts/assess_pilot_v5.py",
    "scripts/run_study.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files() -> list[Path]:
    paths = [ROOT / relative for relative in INCLUDED_PATHS]
    paths.extend(sorted((ROOT / "config" / "scenarios").glob("*.json")))
    paths.extend(sorted((ROOT / "config" / "histories").glob("*.json")))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Protocol bundle source is missing: {missing[0].relative_to(ROOT)}")
    return paths


def _software_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def generate_bundle(*, created_at: datetime | None = None) -> dict:
    """Copy an explicit allowlist; raw/private namespaces can never enter the bundle."""

    models = load_models(ROOT / "config" / "models.yaml")
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    items = []
    for source in _source_files():
        relative = source.relative_to(ROOT)
        destination = BUNDLE_ROOT / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        items.append(
            {
                "source_path": relative.as_posix(),
                "bundle_path": destination.relative_to(BUNDLE_ROOT).as_posix(),
                "sha256": sha256_file(source),
            }
        )
    metadata = {
        "bundle_version": "protocol-bundle-v1",
        "study_version": STUDY_VERSION,
        "model_configuration_version": models.version,
        "generation_version": models.generation.version,
        "rubric_status": "draft_pending_supervisor_research_group_approval",
        "software_commit": _software_commit(),
        "created_at_utc": (created_at or datetime.now(UTC)).isoformat(),
        "contains_sensitive_or_observed_data": False,
        "items": sorted(items, key=lambda item: item["source_path"]),
    }
    METADATA_PATH.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metadata


def verify_bundle() -> dict:
    if not METADATA_PATH.is_file():
        raise RuntimeError("Frozen Study V2 protocol bundle has not been generated")
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if metadata.get("study_version") != STUDY_VERSION:
        raise RuntimeError("Protocol bundle study version mismatch")
    if metadata.get("contains_sensitive_or_observed_data") is not False:
        raise RuntimeError("Protocol bundle safety declaration is invalid")
    expected_sources = {path.relative_to(ROOT).as_posix() for path in _source_files()}
    actual_sources = {item["source_path"] for item in metadata.get("items", [])}
    if actual_sources != expected_sources:
        raise RuntimeError("Protocol bundle allowlist differs from the frozen source set")
    for item in metadata["items"]:
        source = ROOT / item["source_path"]
        bundled = BUNDLE_ROOT / item["bundle_path"]
        expected = item["sha256"]
        if sha256_file(source) != expected or sha256_file(bundled) != expected:
            raise RuntimeError(f"Protocol bundle hash mismatch: {item['source_path']}")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--generate", action="store_true")
    action.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        metadata = generate_bundle() if args.generate else verify_bundle()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"Protocol bundle valid: {metadata['study_version']} | "
        f"{len(metadata['items'])} hashed planned-study files"
    )
    print(METADATA_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
