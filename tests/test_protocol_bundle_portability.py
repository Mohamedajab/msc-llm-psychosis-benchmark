"""Cross-platform integrity tests for immutable historical protocol bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import protocol_bundle


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _synthetic_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stored: bytes,
    recorded: bytes,
    suffix: str = ".txt",
) -> tuple[Path, Path]:
    root = tmp_path
    bundle = root / "protocol" / "study-v2.0.0"
    source_path = f"synthetic/item{suffix}"
    bundle_path = f"files/{source_path}"
    item = bundle / bundle_path
    item.parent.mkdir(parents=True)
    item.write_bytes(stored)
    metadata = {
        "bundle_version": "protocol-bundle-v1",
        "study_version": "study-v2.0.0",
        "model_configuration_version": "test-only",
        "generation_version": "test-only",
        "rubric_status": "test-only",
        "software_commit": "test-only",
        "created_at_utc": "2026-08-30T00:00:00+00:00",
        "contains_sensitive_or_observed_data": False,
        "items": [
            {
                "source_path": source_path,
                "bundle_path": bundle_path,
                "sha256": _sha256(recorded),
            }
        ],
    }
    metadata_path = bundle / "bundle.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(protocol_bundle, "ROOT", root)
    monkeypatch.setattr(protocol_bundle, "BUNDLE_ROOT", bundle)
    monkeypatch.setattr(protocol_bundle, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(
        protocol_bundle,
        "HISTORICAL_BUNDLE_FINGERPRINT",
        protocol_bundle.historical_bundle_fingerprint(),
    )
    return item, metadata_path


@pytest.mark.parametrize("stored", [b"alpha\nbeta\n", b"alpha\r\nbeta\r\n"])
def test_lf_and_crlf_equivalent_historical_text_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored: bytes
) -> None:
    _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=stored,
        recorded=b"alpha\r\nbeta\r\n",
    )
    assert protocol_bundle.verify_historical_bundle()["study_version"] == "study-v2.0.0"


def test_portable_tree_fingerprint_is_identical_for_lf_and_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, _ = _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=b"alpha\nbeta\n",
        recorded=b"alpha\r\nbeta\r\n",
    )
    lf_fingerprint = protocol_bundle.historical_bundle_fingerprint()
    item.write_bytes(b"alpha\r\nbeta\r\n")
    assert protocol_bundle.historical_bundle_fingerprint() == lf_fingerprint


def test_substantive_text_change_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item, _ = _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=b"alpha\nbeta\n",
        recorded=b"alpha\r\nbeta\r\n",
    )
    item.write_bytes(b"alpha\nchanged\n")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        protocol_bundle.verify_historical_bundle()


def test_missing_or_extra_bundle_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, _ = _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=b"alpha\n",
        recorded=b"alpha\r\n",
    )
    item.unlink()
    with pytest.raises(RuntimeError, match="file set differs"):
        protocol_bundle.verify_historical_bundle()

    item.write_bytes(b"alpha\n")
    extra = item.parent / "extra.txt"
    extra.write_text("extra\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="file set differs"):
        protocol_bundle.verify_historical_bundle()


def test_incorrect_item_mapping_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, metadata_path = _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=b"alpha\n",
        recorded=b"alpha\r\n",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["items"][0]["source_path"] = "synthetic/wrong.txt"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError, match="path mapping is invalid"):
        protocol_bundle.verify_historical_bundle()


def test_binary_artifacts_remain_exact_byte_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, _ = _synthetic_bundle(
        tmp_path,
        monkeypatch,
        stored=b"\x00\x01\r\n\xff",
        recorded=b"\x00\x01\r\n\xff",
        suffix=".bin",
    )
    assert protocol_bundle.verify_historical_bundle()["study_version"] == "study-v2.0.0"
    item.write_bytes(b"\x00\x01\n\xff")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        protocol_bundle.verify_historical_bundle()
