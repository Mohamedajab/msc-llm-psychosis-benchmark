"""Prospective creation and verification of the final active Study V2 bundle.

The historical ``protocol/study-v2.0.0`` bundle is intentionally outside this
module. It remains immutable evidence of a superseded candidate pair. Only a
new bundle produced here can establish current-source equivalence for future
collection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import Field

from src.config_loader import canonical_hash, load_models, load_scripts, resolve_model_ids
from src.manifest import generate_manifest, manifest_dataframe, validate_manifest
from src.pilot_v6 import (
    FINAL_CONFIGURATION_VERSION,
    FINAL_PAIR_SOURCE,
    FINAL_STUDY_VERSION,
    GENERATION_VERSION,
    PilotV6Verdict,
    assess_pilot_v6,
    build_original_pair_models_config,
)
from src.schemas import ManifestRow, ModelsConfig, StrictModel

ACTIVE_BUNDLE_VERSION = "active-study-bundle-v2.0.0"
ACTIVE_PROTOCOL_DIRECTORY = "study-v2.1.0"
FINAL_MODELS_RELATIVE_PATH = Path("config/final/study-v2.1.0/models.yaml")
FINAL_MANIFEST_RELATIVE_PATH = Path("outputs/study-v2.1.0/experiment_manifest.csv")

STATIC_PROTOCOL_INPUTS = (
    "config/main-study-governance.yaml",
    "config/rubric.yaml",
    "docs/EXECUTION_POLICY.md",
    "docs/EVALUATION_FRAMEWORK_PRECEDENT.md",
    "docs/FINAL_STUDY_READINESS_WORKFLOW.md",
    "docs/GENERATION_V4_CALIBRATION.md",
    "docs/PROTOCOL_DEVIATION_STUDY_V2.md",
    "docs/PROVIDER_POLICY.md",
    "docs/RESEARCH_PROTOCOL.md",
    "outputs/data_dictionary.csv",
    "scripts/assess_pilot_v6.py",
    "scripts/run_pilot_v6.py",
    "scripts/run_study.py",
    "src/active_study.py",
    "src/config_loader.py",
    "src/conversation_runner.py",
    "src/generation_profiles.py",
    "src/main_study_readiness.py",
    "src/manifest.py",
    "src/payloads.py",
    "src/pilot_v6.py",
    "src/provider_client.py",
    "src/replacement_screening.py",
    "src/replacement_selection.py",
    "src/schemas.py",
    "src/storage.py",
    "src/study_audit.py",
    "src/study_execution.py",
)


class ActiveStudyError(RuntimeError):
    """The prospective final study cannot be frozen or verified safely."""


class ActiveBundleItem(StrictModel):
    bundle_path: str
    source_scope: str
    source_path: str
    sha256: str
    hash_mode: str = "text_lf"


class ActiveBundleMetadata(StrictModel):
    bundle_version: str = ACTIVE_BUNDLE_VERSION
    study_version: str = FINAL_STUDY_VERSION
    configuration_version: str = FINAL_CONFIGURATION_VERSION
    generation_version: str = GENERATION_VERSION
    generation_profile_hash: str
    created_at: datetime
    software_commit: str
    planned_conversations: int = 72
    planned_response_slots: int = 432
    model_ids: dict[str, str]
    final_pair_source: str
    pilot_v6_source_evidence_hash: str
    rubric_status: str
    items: tuple[ActiveBundleItem, ...]
    evidence_references: dict[str, str] = Field(default_factory=dict)


def _canonical_bytes(path: Path) -> bytes:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return path.read_bytes()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_exclusive(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise ActiveStudyError(f"Refusing to overwrite frozen artifact: {path}") from error


def _load_manifest(path: Path) -> list[ManifestRow]:
    if not path.is_file():
        raise ActiveStudyError(f"Final manifest is missing: {path}")
    try:
        frame = pd.read_csv(path)
        frame = frame.fillna({"error_type": "", "error_message": ""})
        records = frame.where(pd.notna(frame), None).to_dict("records")
        return [ManifestRow.model_validate(record) for record in records]
    except (OSError, ValueError) as error:
        raise ActiveStudyError("Final manifest is malformed") from error


def _git_commit(repository_root: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_final_manifest(*, repository_root: str | Path, models: ModelsConfig) -> list[ManifestRow]:
    scripts = load_scripts(Path(repository_root) / "config" / "scenarios")
    rows = generate_manifest(scripts, models, study_version=FINAL_STUDY_VERSION)
    errors = validate_manifest(
        rows,
        models=models,
        expected_study_version=FINAL_STUDY_VERSION,
    )
    if errors:
        raise ActiveStudyError("; ".join(errors))
    if len(rows) != 72 or len(rows) * 6 != 432:
        raise ActiveStudyError("Final Study V2 manifest must remain 72/432")
    return rows


def _validated_prerequisites(
    *,
    repository_root: Path,
    pilot_output_root: str | Path | None,
) -> tuple[Any, ModelsConfig, list[ManifestRow]]:
    if pilot_output_root is None:
        raise ActiveStudyError("Original-pair Pilot V6 PASS evidence is required")
    assessment = assess_pilot_v6(
        pilot_output_root=pilot_output_root,
        repository_root=repository_root,
        persist=False,
    )
    if assessment.verdict != PilotV6Verdict.PASS:
        raise ActiveStudyError(f"Pilot V6 qualification is {assessment.verdict.value}, not PASS")
    if assessment.final_pair_source != FINAL_PAIR_SOURCE:
        raise ActiveStudyError("Pilot V6 evidence does not qualify the frozen original pair")
    models = build_original_pair_models_config(repository_root=repository_root)
    rows = build_final_manifest(repository_root=repository_root, models=models)
    return assessment, models, rows


def freeze_active_study_bundle(
    *,
    repository_root: str | Path,
    artifact_root: str | Path,
    bundle_root: str | Path,
    selection_record_path: str | Path | None,
    catalogue_record_path: str | Path | None,
    screen_output_root: str | Path | None,
    pilot_output_root: str | Path | None,
    created_at: datetime | None = None,
    software_commit: str | None = None,
) -> ActiveBundleMetadata:
    """Create the original-pair final bundle only after a recomputed Pilot V6 PASS."""

    # The replacement arguments are retained for call-site compatibility only.
    # They are not prerequisites and cannot authorise the original-pair path.
    del selection_record_path, catalogue_record_path, screen_output_root

    repo = Path(repository_root).resolve()
    artifacts = Path(artifact_root).resolve()
    destination = Path(bundle_root).resolve()
    if destination.exists():
        raise ActiveStudyError("Active protocol bundle already exists; version it explicitly")
    models_path = artifacts / FINAL_MODELS_RELATIVE_PATH
    manifest_path = artifacts / FINAL_MANIFEST_RELATIVE_PATH
    if models_path.exists() or manifest_path.exists():
        raise ActiveStudyError(
            "Final study artifacts already exist; silent replacement is forbidden"
        )
    assessment, models, rows = _validated_prerequisites(
        repository_root=repo,
        pilot_output_root=pilot_output_root,
    )
    if any("placeholder" in value.casefold() for value in resolve_model_ids(models).values()):
        raise ActiveStudyError("A placeholder model cannot enter the final study")
    for relative in STATIC_PROTOCOL_INPUTS:
        if not (repo / relative).is_file():
            raise ActiveStudyError(f"Required active-bundle source is missing: {relative}")
    model_bytes = yaml.safe_dump(
        models.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    manifest_bytes = manifest_dataframe(rows).to_csv(index=False, lineterminator="\n").encode()
    _write_exclusive(models_path, model_bytes)
    try:
        _write_exclusive(manifest_path, manifest_bytes)
    except Exception:
        models_path.unlink(missing_ok=True)
        raise

    item_specs: list[tuple[str, str, Path]] = [
        ("artifact", FINAL_MODELS_RELATIVE_PATH.as_posix(), models_path),
        ("artifact", FINAL_MANIFEST_RELATIVE_PATH.as_posix(), manifest_path),
    ]
    for relative in STATIC_PROTOCOL_INPUTS:
        source = repo / relative
        item_specs.append(("repository", relative, source))
    for directory in ("config/scenarios", "config/histories"):
        for source in sorted((repo / directory).glob("*.yaml")):
            item_specs.append(("repository", source.relative_to(repo).as_posix(), source))

    created = created_at or datetime.now(UTC)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="active-study-bundle-", dir=destination.parent) as temp:
        stage = Path(temp) / destination.name
        items: list[ActiveBundleItem] = []
        for scope, source_path, source in item_specs:
            bundle_path = f"files/{scope}/{source_path}"
            value = _canonical_bytes(source)
            target = stage / bundle_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            items.append(
                ActiveBundleItem(
                    bundle_path=bundle_path,
                    source_scope=scope,
                    source_path=source_path,
                    sha256=_sha256_bytes(value),
                )
            )
        evidence_dir = stage / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        assessment_bytes = json.dumps(
            assessment.model_dump(mode="json"), sort_keys=True, indent=2
        ).encode()
        (evidence_dir / "pilot-v6-assessment.json").write_bytes(assessment_bytes)
        metadata = ActiveBundleMetadata(
            created_at=created,
            software_commit=software_commit or _git_commit(repo),
            model_ids=resolve_model_ids(models),
            generation_profile_hash=canonical_hash(models.generation),
            final_pair_source=FINAL_PAIR_SOURCE,
            pilot_v6_source_evidence_hash=assessment.source_evidence_hash,
            rubric_status="draft_pending_human_approval",
            items=tuple(items),
            evidence_references={
                "pilot_v6_assessment": "evidence/pilot-v6-assessment.json",
            },
        )
        (stage / "bundle.json").write_text(
            json.dumps(metadata.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        shutil.copytree(stage, destination)
    return metadata


def verify_active_study_bundle(
    *,
    bundle_root: str | Path,
    repository_root: str | Path,
    artifact_root: str | Path,
    selection_record_path: str | Path | None,
    catalogue_record_path: str | Path | None,
    screen_output_root: str | Path | None,
    pilot_output_root: str | Path | None,
) -> ActiveBundleMetadata:
    """Verify bundle integrity plus equality with current collection sources."""

    # Replacement evidence is non-authoritative on the original-pair V6 path.
    del selection_record_path, catalogue_record_path, screen_output_root

    bundle = Path(bundle_root)
    metadata_path = bundle / "bundle.json"
    if not metadata_path.is_file():
        raise ActiveStudyError("Active final bundle is not created")
    try:
        metadata = ActiveBundleMetadata.model_validate_json(metadata_path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise ActiveStudyError("Active bundle metadata is malformed") from error
    if metadata.bundle_version != ACTIVE_BUNDLE_VERSION:
        raise ActiveStudyError("Active bundle version mismatch")
    repo = Path(repository_root).resolve()
    artifacts = Path(artifact_root).resolve()
    for item in metadata.items:
        bundled = bundle / item.bundle_path
        if not bundled.is_file() or _sha256_bytes(_canonical_bytes(bundled)) != item.sha256:
            raise ActiveStudyError(f"Active bundle hash mismatch: {item.bundle_path}")
        base = repo if item.source_scope == "repository" else artifacts
        if item.source_scope not in {"repository", "artifact"}:
            raise ActiveStudyError("Active bundle contains an unknown source scope")
        current = base / item.source_path
        if not current.is_file() or _sha256_bytes(_canonical_bytes(current)) != item.sha256:
            raise ActiveStudyError(f"Current-source mismatch: {item.source_path}")

    assessment, models, rows = _validated_prerequisites(
        repository_root=repo,
        pilot_output_root=pilot_output_root,
    )
    if metadata.final_pair_source != FINAL_PAIR_SOURCE:
        raise ActiveStudyError("Active bundle final-pair source is invalid")
    if metadata.pilot_v6_source_evidence_hash != assessment.source_evidence_hash:
        raise ActiveStudyError("Active bundle Pilot V6 evidence is stale")
    if metadata.model_ids != resolve_model_ids(models):
        raise ActiveStudyError("Active bundle model identities are stale")
    if metadata.generation_profile_hash != canonical_hash(models.generation):
        raise ActiveStudyError("Active bundle generation profile is stale")
    final_models = load_models(artifacts / FINAL_MODELS_RELATIVE_PATH)
    if final_models != models:
        raise ActiveStudyError("Final model configuration differs from recomputed original pair")
    final_rows = _load_manifest(artifacts / FINAL_MANIFEST_RELATIVE_PATH)
    errors = validate_manifest(
        final_rows,
        models=final_models,
        expected_study_version=FINAL_STUDY_VERSION,
    )
    actual_csv = manifest_dataframe(final_rows).to_csv(index=False)
    expected_csv = manifest_dataframe(rows).to_csv(index=False)
    if errors or actual_csv != expected_csv:
        raise ActiveStudyError("Final manifest differs from recomputed original-pair design")
    return metadata
