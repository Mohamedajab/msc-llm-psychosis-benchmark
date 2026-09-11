"""Verify the completed Study V2.1 research artefact without changing it."""

# ruff: noqa: E402
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_repository_safety import audit_tracked_files
from scripts.protocol_bundle import verify_historical_bundle
from src.active_study import FINAL_MANIFEST_RELATIVE_PATH, ActiveBundleMetadata
from src.annotation import AnnotationStore, response_hash
from src.judge_execution import load_judge_configuration, load_successes
from src.main_study import default_paths, load_study_progress, planned_study, validate_saved_study
from src.manifest import manifest_dataframe
from src.storage import RawRunStore

EXPECTED_CONVERSATIONS = 72
EXPECTED_RESPONSES = 432
EXPECTED_MODEL_RESPONSES = 216
EXPECTED_TECHNICAL_ERRORS = 145
EXPECTED_AUTOMATIC_RECOVERIES = 127
PRIMARY_ANNOTATOR = "annotator_1"
EXPECTED_JUDGES = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.3-flash",
)

ANALYSIS_ROOT = ROOT / "data" / "private"
ANALYSIS_FREEZE_MANIFEST = ANALYSIS_ROOT / "analysis-freeze-v1.sha256.txt"
RQ1_PATH = ANALYSIS_ROOT / "analysis-v2" / "tables" / "rq1_presentation_level_tests.csv"
RQ2_PATH = ANALYSIS_ROOT / "analysis-v2" / "tables" / "rq2_model_tests.csv"
RQ3_PATH = ANALYSIS_ROOT / "analysis-v2" / "tables" / "rq3_context_tests.csv"
RQ4_EVENTS_PATH = ANALYSIS_ROOT / "analysis-v2" / "tables" / "rq4_trajectory_events.csv"
RQ4_INTERACTION_PATH = (
    ANALYSIS_ROOT / "analysis-v3" / "tables" / "presentation_by_time_interactions.csv"
)
JUDGE_AGREEMENT_PATH = (
    ANALYSIS_ROOT / "analysis-v3" / "tables" / "human_vs_three_judge_majority.csv"
)

REQUIRED_ANALYSIS_OUTPUTS = (
    RQ1_PATH,
    RQ2_PATH,
    RQ3_PATH,
    RQ4_EVENTS_PATH,
    RQ4_INTERACTION_PATH,
    JUDGE_AGREEMENT_PATH,
)

EXPECTED_RQ1 = {
    ("control", "ambiguous", "mean_A1"): {
        "mean_difference": 0.3194444444444444,
        "bootstrap_95_ci_lower": 0.11111111111111112,
        "bootstrap_95_ci_upper": 0.5347222222222222,
        "p_holm": 0.03680839559908222,
        "rank_biserial_effect": 0.719047619047619,
    },
    ("control", "ambiguous", "mean_A2"): {
        "mean_difference": 0.3333333333333333,
        "bootstrap_95_ci_lower": 0.12916666666666665,
        "bootstrap_95_ci_upper": 0.5389236111111105,
        "p_holm": 0.03898699581405505,
        "rank_biserial_effect": 0.7720588235294118,
    },
    ("ambiguous", "fixed_belief", "mean_A2"): {
        "mean_difference": -0.2986111111111111,
        "bootstrap_95_ci_lower": -0.4694444444444444,
        "bootstrap_95_ci_upper": -0.15277777777777776,
        "p_holm": 0.013526062870283496,
        "rank_biserial_effect": -0.9619047619047619,
    },
    ("ambiguous", "fixed_belief", "mean_A3"): {
        "mean_difference": 0.2898550724637681,
        "bootstrap_95_ci_lower": 0.12681159420289853,
        "bootstrap_95_ci_upper": 0.45652173913043476,
        "p_holm": 0.0375987788510608,
        "rank_biserial_effect": 0.9393939393939394,
    },
}

EXPECTED_RQ4_INTERACTION = {
    "mean_difference": -0.5416666666666666,
    "ci_lower": -0.8541666666666666,
    "ci_upper": -0.2708333333333333,
    "p_holm": 0.008835776488315624,
    "rank_biserial": -0.8562091503267973,
}

EXPECTED_JUDGE_AGREEMENT = {
    "A1": (0.7981438515081206, 0.570610211706102),
    "A2": (0.5072463768115942, 0.07399347116430888),
    "A3": (0.5753424657534246, 0.2315789473684211),
    "B1": (0.6317016317016317, 0.35365114717586754),
    "B2": (0.9489559164733179, 0.20792859018114995),
    "B3": (0.7314814814814815, 0.1688514967716691),
    "C1": (0.6976744186046512, 0.5217558290259086),
}


class FinalReleaseError(RuntimeError):
    """A completed-study verification check failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FinalReleaseError(message)


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FinalReleaseError(f"Required analysis output is missing: {path.relative_to(ROOT)}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise FinalReleaseError(
            f"Could not parse analysis output: {path.relative_to(ROOT)}"
        ) from error
    _require(bool(rows), f"Analysis output is empty: {path.relative_to(ROOT)}")
    return rows


def _one_row(rows: list[dict[str, str]], **fields: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(name) == value for name, value in fields.items())]
    _require(
        len(matches) == 1,
        f"Expected one reported-result row for {fields}; found {len(matches)}",
    )
    return matches[0]


def _as_float(row: dict[str, str], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise FinalReleaseError(f"Reported-result field is not numeric: {field}") from error


def _assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise FinalReleaseError(f"Reported result differs for {label}: {actual} != {expected}")


def verify_study_completion() -> dict[str, Any]:
    paths = default_paths(ROOT)
    _, _, _, rows = planned_study(ROOT)
    expected_manifest = manifest_dataframe(rows).fillna("").astype(str).reset_index(drop=True)
    manifest_path = ROOT / FINAL_MANIFEST_RELATIVE_PATH
    _require(manifest_path.is_file(), "Final Study V2.1 manifest is missing")
    actual_manifest = pd.read_csv(manifest_path).fillna("").astype(str).reset_index(drop=True)
    _require(
        list(actual_manifest.columns) == list(expected_manifest.columns)
        and actual_manifest.equals(expected_manifest),
        "Saved Study V2.1 manifest differs from the frozen factorial design",
    )

    report = validate_saved_study(repository_root=ROOT, raw_root=paths["raw_root"])
    progress = load_study_progress(
        repository_root=ROOT,
        raw_root=paths["raw_root"],
        state_path=paths["job_root"] / "state.json",
        runtime_amendments_path=paths["runtime_amendments_path"],
    )
    expected = {
        "planned_conversations": EXPECTED_CONVERSATIONS,
        "stored_conversations": EXPECTED_CONVERSATIONS,
        "completed_conversations": EXPECTED_CONVERSATIONS,
        "successful_responses": EXPECTED_RESPONSES,
        "missing_responses": 0,
        "truncated_responses": 0,
        "resolved_model_mismatches": 0,
    }
    for field, value in expected.items():
        _require(report.get(field) == value, f"Study completion check failed: {field}")
    _require(progress.status.value == "COMPLETE", "Persisted main-study status is not COMPLETE")
    _require(
        progress.technical_errors == EXPECTED_TECHNICAL_ERRORS,
        "Recorded technical-error total differs from the frozen study summary",
    )
    _require(
        progress.automatic_resumes == EXPECTED_AUTOMATIC_RECOVERIES,
        "Automatic-recovery total differs from the frozen study summary",
    )
    _require(
        progress.approved_finish_metadata_anomalies == 1,
        "Approved finish-metadata anomaly count differs from the frozen record",
    )
    _require(
        set(progress.response_counts_by_model.values()) == {EXPECTED_MODEL_RESPONSES}
        and len(progress.response_counts_by_model) == 2,
        "Final response split is not 216/216 across the two frozen models",
    )
    return {
        "conversations": report["completed_conversations"],
        "responses": report["successful_responses"],
        "truncations": report["truncated_responses"],
        "technical_errors": progress.technical_errors,
        "automatic_recoveries": progress.automatic_resumes,
        "model_responses": progress.response_counts_by_model,
    }


def _raw_response_hashes() -> Counter[str]:
    store = RawRunStore(default_paths(ROOT)["raw_root"])
    hashes: Counter[str] = Counter()
    for run_id in store.list_run_ids():
        for event in store.successful_turns(run_id):
            hashes[response_hash(event.result.text or "")] += 1
    return hashes


def verify_human_annotations() -> tuple[dict[str, Any], dict[str, str]]:
    annotation_path = ROOT / "data" / "annotations" / "annotations.jsonl"
    events = [
        event
        for event in AnnotationStore(annotation_path).latest_events(annotator_id=PRIMARY_ANNOTATOR)
        if event.rating_round == "initial"
    ]
    _require(len(events) == EXPECTED_RESPONSES, "Primary human annotation count is not 432")
    _require(
        len({event.blinded_item_id for event in events}) == EXPECTED_RESPONSES,
        "Primary human annotations contain duplicate blinded item IDs",
    )
    _require(
        all(event.annotation_method == "human" for event in events),
        "Primary annotation provenance is not entirely human",
    )
    _require(all(event.scores.complete() for event in events), "A final human rating is incomplete")
    annotation_hashes = Counter(event.source_response_hash for event in events)
    _require(
        annotation_hashes == _raw_response_hashes(),
        "Human annotation source hashes do not match the 432 saved study responses",
    )
    item_hashes = {event.blinded_item_id: event.source_response_hash for event in events}
    return {
        "annotations": len(events),
        "annotator_id": PRIMARY_ANNOTATOR,
        "annotation_method": "human",
    }, item_hashes


def verify_judges(human_items: dict[str, str]) -> dict[str, Any]:
    configuration_path = ROOT / "config" / "llm-judges.yaml"
    configuration = load_judge_configuration(configuration_path)
    by_id = {spec.judge_id: spec for spec in configuration.judges}
    _require(
        set(by_id) == set(EXPECTED_JUDGES),
        "Frozen judge configuration is not the expected set",
    )
    judge_root = ROOT / "data" / "private" / "judges"
    counts: dict[str, int] = {}
    for judge_id in EXPECTED_JUDGES:
        results = load_successes(
            judge_root=judge_root,
            spec=by_id[judge_id],
            configuration=configuration,
        )
        _require(len(results) == EXPECTED_RESPONSES, f"{judge_id} does not contain 432 results")
        judge_items = {item_id: result.source_response_hash for item_id, result in results.items()}
        _require(
            judge_items == human_items,
            f"{judge_id} results do not match the primary human annotation item set",
        )
        counts[judge_id] = len(results)
    return {"judges": counts, "total": sum(counts.values())}


def _canonical_bytes(path: Path) -> bytes:
    value = path.read_bytes()
    try:
        return value.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return value


def verify_final_bundle_integrity() -> dict[str, Any]:
    """Verify the frozen bundle itself, without using it to authorise new collection."""

    bundle_root = ROOT / "protocol" / "study-v2.1.0"
    metadata_path = bundle_root / "bundle.json"
    _require(metadata_path.is_file(), "Final Study V2.1 bundle metadata is missing")
    try:
        metadata = ActiveBundleMetadata.model_validate_json(metadata_path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise FinalReleaseError("Final Study V2.1 bundle metadata is malformed") from error
    expected_paths = {"bundle.json"}
    expected_paths.update(item.bundle_path for item in metadata.items)
    expected_paths.update(metadata.evidence_references.values())
    actual_paths = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    }
    _require(actual_paths == expected_paths, "Final Study V2.1 bundle file membership differs")
    for item in metadata.items:
        path = bundle_root / item.bundle_path
        _require(path.is_file(), f"Final bundle item is missing: {item.bundle_path}")
        digest = hashlib.sha256(_canonical_bytes(path)).hexdigest()
        _require(digest == item.sha256, f"Final bundle hash mismatch: {item.bundle_path}")
    pilot_path = bundle_root / metadata.evidence_references["pilot_v6_assessment"]
    try:
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FinalReleaseError("Frozen Pilot V6 assessment is unreadable") from error
    _require(pilot.get("verdict") == "PASS", "Frozen Pilot V6 assessment is not PASS")
    _require(
        pilot.get("source_evidence_hash") == metadata.pilot_v6_source_evidence_hash,
        "Frozen Pilot V6 assessment hash differs from bundle metadata",
    )
    _require(metadata.planned_conversations == 72, "Final bundle conversation count is not 72")
    _require(metadata.planned_response_slots == 432, "Final bundle response count is not 432")
    _require(len(metadata.model_ids) == 2, "Final bundle does not contain exactly two models")
    verify_historical_bundle()
    return {
        "study_version": metadata.study_version,
        "items": len(metadata.items),
        "pilot_v6": pilot["verdict"],
        "historical_bundle": "PASS",
    }


def _manifest_path(recorded: str) -> Path:
    path = Path(recorded)
    if path.is_file():
        candidate = path.resolve()
    else:
        parts = PureWindowsPath(recorded).parts
        indexes = [
            index
            for index, part in enumerate(parts)
            if part in {"requirements.txt", "scripts", "data"}
        ]
        _require(bool(indexes), f"Could not resolve frozen analysis path: {recorded}")
        candidate = (ROOT / Path(*parts[indexes[-1] :])).resolve()
    _require(
        candidate.is_relative_to(ROOT.resolve()),
        "Analysis freeze path is outside the project",
    )
    return candidate


def verify_analysis_freeze() -> dict[str, Any]:
    _require(ANALYSIS_FREEZE_MANIFEST.is_file(), "Analysis freeze manifest is missing")
    pattern = re.compile(r"^([0-9A-Fa-f]{64})\s{2}(.+)$")
    checked = 0
    for line_number, line in enumerate(
        ANALYSIS_FREEZE_MANIFEST.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if (
            not line.strip()
            or line.startswith("ANALYSIS ")
            or line.startswith("Git commit:")
            or line.startswith("Created:")
        ):
            continue
        match = pattern.fullmatch(line)
        _require(match is not None, f"Malformed analysis freeze entry on line {line_number}")
        expected, recorded_path = match.groups()
        path = _manifest_path(recorded_path)
        _require(path.is_file(), f"Frozen analysis file is missing: {path.relative_to(ROOT)}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        _require(
            actual.casefold() == expected.casefold(),
            f"Frozen analysis hash mismatch: {path.relative_to(ROOT)}",
        )
        checked += 1
    _require(checked > 0, "Analysis freeze manifest contains no hash entries")
    return {"files": checked}


def verify_reported_results() -> dict[str, Any]:
    for path in REQUIRED_ANALYSIS_OUTPUTS:
        load_csv_rows(path)

    rq1 = load_csv_rows(RQ1_PATH)
    supported = {
        (row["level_a"], row["level_b"], row["outcome"])
        for row in rq1
        if row["significant_0_05"].casefold() == "true"
    }
    _require(supported == set(EXPECTED_RQ1), "RQ1 supported comparisons differ from the freeze")
    for key, expected in EXPECTED_RQ1.items():
        row = _one_row(rq1, level_a=key[0], level_b=key[1], outcome=key[2])
        for field, value in expected.items():
            _assert_close(_as_float(row, field), value, f"RQ1 {key} {field}")

    for label, path in (("RQ2", RQ2_PATH), ("RQ3", RQ3_PATH)):
        rows = load_csv_rows(path)
        primary = [row for row in rows if row["outcome"] in {"mean_A1", "mean_A2", "mean_A3"}]
        _require(len(primary) == 3, f"{label} does not contain the three primary axes")
        _require(
            not any(row["significant_0_05"].casefold() == "true" for row in primary),
            f"{label} contains a Holm-significant primary comparison",
        )

    rq4 = load_csv_rows(RQ4_INTERACTION_PATH)
    row = _one_row(
        rq4,
        level_a="ambiguous",
        level_b="fixed_belief",
        outcome="late_minus_early_A1",
    )
    for field, value in EXPECTED_RQ4_INTERACTION.items():
        _assert_close(_as_float(row, field), value, f"RQ4 {field}")

    agreement = load_csv_rows(JUDGE_AGREEMENT_PATH)
    for axis, (exact_agreement, kappa) in EXPECTED_JUDGE_AGREEMENT.items():
        row = _one_row(agreement, axis=axis)
        _assert_close(
            _as_float(row, "numeric_exact_agreement"), exact_agreement, f"{axis} agreement"
        )
        _assert_close(_as_float(row, "human_vs_majority_kappa"), kappa, f"{axis} kappa")
    return {
        "rq1_supported_comparisons": len(supported),
        "rq2_supported_primary_comparisons": 0,
        "rq3_supported_primary_comparisons": 0,
        "rq4_interaction": "PASS",
        "judge_agreement_axes": len(EXPECTED_JUDGE_AGREEMENT),
    }


def verify_repository_safety() -> dict[str, Any]:
    suspicious = audit_tracked_files()
    _require(not suspicious, "Repository safety check found: " + ", ".join(suspicious))
    return {"tracked_private_or_secret_files": 0}


def run_verification() -> dict[str, Any]:
    study = verify_study_completion()
    human, human_items = verify_human_annotations()
    judges = verify_judges(human_items)
    protocol = verify_final_bundle_integrity()
    freeze = verify_analysis_freeze()
    results = verify_reported_results()
    safety = verify_repository_safety()
    return {
        "study": study,
        "human": human,
        "judges": judges,
        "protocol": protocol,
        "analysis_freeze": freeze,
        "reported_results": results,
        "repository_safety": safety,
    }


def main() -> int:
    try:
        report = run_verification()
    except (FinalReleaseError, OSError, RuntimeError, ValueError) as error:
        print("FINAL RELEASE VERIFICATION: FAIL", file=sys.stderr)
        print(f"- {error}", file=sys.stderr)
        return 1

    print("FINAL RELEASE VERIFICATION: PASS")
    print(f"Study conversations: {report['study']['conversations']} / {EXPECTED_CONVERSATIONS}")
    print(f"Study responses: {report['study']['responses']} / {EXPECTED_RESPONSES}")
    print(f"Human annotations: {report['human']['annotations']} / {EXPECTED_RESPONSES}")
    print(f"Supplementary judge ratings: {report['judges']['total']} / 1296")
    print(f"Final truncations: {report['study']['truncations']}")
    print(f"Frozen analysis hashes: PASS ({report['analysis_freeze']['files']} files)")
    print("Reported-result checks: PASS")
    print("Protocol verification: PASS")
    print("Repository safety: PASS")
    print("Network requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
