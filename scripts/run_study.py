"""Guarded, manifest-ordered Study V2 runner; offline preflight is the default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.protocol_bundle import verify_historical_bundle
from src.active_study import (
    FINAL_MANIFEST_RELATIVE_PATH,
    FINAL_MODELS_RELATIVE_PATH,
    verify_active_study_bundle,
)
from src.config_loader import (
    load_histories,
    load_models,
    load_scripts,
    resolve_model_ids,
    validate_catalogue,
)
from src.main_study_readiness import evaluate_main_study_readiness
from src.manifest import generate_manifest, manifest_dataframe, validate_manifest
from src.pilot_qualification import assess_pilot_v4, assess_pilot_v5
from src.provider_client import OpenRouterProvider
from src.storage import RawRunStore, atomic_write_json
from src.study_execution import (
    build_execution_summary,
    execute_manifest_rows,
    print_execution_summary,
)
from src.study_status import load_study_v2_status, replacement_endpoint_not_frozen

STUDY_VERSION = "study-v2.0.0"
MANIFEST_PATH = ROOT / "outputs" / "experiment_manifest.csv"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "raw" / "study-v2"
PREFLIGHT_FAILURE_ROOT = ROOT / "data" / "raw" / "study-preflight"
MINIMUM_REQUEST_INTERVAL_SECONDS = 5.0
TECHNICAL_PILOT_OUTPUT_ROOT = ROOT / "data" / "raw" / "runs"
GOVERNANCE_PATH = ROOT / "config" / "main-study-governance.yaml"


class StudyPreflightError(RuntimeError):
    """A frozen-protocol or live-safety condition was not satisfied."""


def load_frozen_study() -> tuple[list[Any], list[Any], Any, list[Any]]:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(ROOT / "config" / "models.yaml")
    catalogue_errors = validate_catalogue(scripts, histories)
    if catalogue_errors:
        raise StudyPreflightError("; ".join(catalogue_errors))
    rows = generate_manifest(scripts, models)
    manifest_errors = validate_manifest(rows, models=models, expected_study_version=STUDY_VERSION)
    if manifest_errors:
        raise StudyPreflightError("; ".join(manifest_errors))
    if len(rows) != 72 or len(rows) * 6 != 432:
        raise StudyPreflightError("Study V2 requires exactly 72 conversations and 432 slots")
    if not MANIFEST_PATH.is_file():
        raise StudyPreflightError("Frozen manifest file is missing")
    expected = manifest_dataframe(rows).fillna("").astype(str).reset_index(drop=True)
    actual = pd.read_csv(MANIFEST_PATH).fillna("").astype(str).reset_index(drop=True)
    if list(actual.columns) != list(expected.columns) or not actual.equals(expected):
        raise StudyPreflightError("Frozen manifest differs from configuration-derived Study V2")
    return scripts, histories, models, rows


def build_offline_preflight(
    *, pilot_output_root: Path = TECHNICAL_PILOT_OUTPUT_ROOT
) -> dict[str, Any]:
    scripts, histories, models, rows = load_frozen_study()
    bundle = verify_historical_bundle()
    pilot_v4 = assess_pilot_v4(output_root=pilot_output_root, persist=False)
    pilot_v5 = assess_pilot_v5(output_root=pilot_output_root, persist=False)
    status = load_study_v2_status()
    readiness = evaluate_main_study_readiness(
        repository_root=ROOT,
        governance_path=GOVERNANCE_PATH,
        pilot_output_root=pilot_output_root,
    )
    return {
        "status": "offline_preflight",
        "network_called": False,
        "study_version": STUDY_VERSION,
        "configuration_version": models.version,
        "generation_version": models.generation.version,
        "models": resolve_model_ids(models),
        "planned_conversations": len(rows),
        "planned_response_slots": len(rows) * 6,
        "scripts": len(scripts),
        "histories": len(histories),
        "protocol_bundle_commit": bundle["software_commit"],
        "protocol_bundle_items": len(bundle["items"]),
        "historical_bundle_verified": True,
        "pilot_v4_qualification": pilot_v4.verdict.value,
        "pilot_v4_failed_criteria": list(pilot_v4.failed_criteria),
        "pilot_v5_qualification": pilot_v5.verdict.value,
        "pilot_v5_failed_criteria": list(pilot_v5.failed_criteria),
        "replacement_endpoint_status": status.replacement_endpoint_status,
        "pilot_v6_status": status.pilot_v6_status,
        "main_study_status": status.main_study_status,
        "replacement_blocker": status.blocker,
        "main_study_live_blocked": replacement_endpoint_not_frozen(status)
        or pilot_v5.main_study_blocked
        or readiness.main_study != "READY",
        "replacement_catalogue": readiness.replacement_catalogue,
        "replacement_screen": readiness.replacement_screen,
        "replacement_selection": readiness.replacement_selection,
        "active_bundle": readiness.active_bundle,
        "governance": readiness.governance,
        "readiness_blockers": list(readiness.blockers),
    }


def require_live_gate(
    *,
    live_requested: bool,
    live_confirmed: bool,
    protocol_confirmed: bool,
    environ: Mapping[str, str] | None = None,
) -> str:
    if not live_requested or not live_confirmed or not protocol_confirmed:
        raise StudyPreflightError(
            "Live study requires --live, --confirm-live and --confirm-protocol-frozen"
        )
    values = os.environ if environ is None else environ
    if values.get("RUN_LIVE_STUDY") != "1":
        raise StudyPreflightError("Live study requires RUN_LIVE_STUDY=1")
    key = values.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise StudyPreflightError("Live study requires an API key; no POST was made")
    return key


def _store_preflight_failure(model_ids: dict[str, str], error: Exception, key: str) -> Path:
    timestamp = datetime.now(UTC)
    return atomic_write_json(
        PREFLIGHT_FAILURE_ROOT
        / f"{STUDY_VERSION}-preflight_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{uuid.uuid4().hex}.json",
        {
            "study_version": STUDY_VERSION,
            "record_type": "MAIN-STUDY PREFLIGHT FAILURE - NO RESEARCH RESPONSE",
            "timestamp": timestamp.isoformat(),
            "requested_models": model_ids,
            "generation_requests_made": 0,
            "error_type": type(error).__name__,
            "error_message": str(error).replace(key, "[REDACTED]")[:500],
        },
    )


def execute_live_study(
    *,
    maximum_http_attempts: int,
    live_requested: bool = False,
    live_confirmed: bool = False,
    protocol_confirmed: bool = False,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    max_new_conversations: int | None = None,
    stop_after_execution_order: int | None = None,
    request_interval_seconds: float = MINIMUM_REQUEST_INTERVAL_SECONDS,
    environ: Mapping[str, str] | None = None,
    provider_factory: Callable[..., Any] = OpenRouterProvider,
    pilot_output_root: Path = TECHNICAL_PILOT_OUTPUT_ROOT,
    catalogue_record_path: Path | None = None,
    selection_record_path: Path | None = None,
    screen_output_root: Path | None = None,
    active_bundle_root: Path | None = None,
    final_artifact_root: Path = ROOT,
    governance_path: Path = GOVERNANCE_PATH,
) -> dict[str, Any]:
    if maximum_http_attempts < 1:
        raise StudyPreflightError("Live study requires a positive explicit attempt cap")
    if max_new_conversations is not None and max_new_conversations < 1:
        raise StudyPreflightError("max_new_conversations must be positive")
    if request_interval_seconds < MINIMUM_REQUEST_INTERVAL_SECONDS:
        raise StudyPreflightError("Study request pacing must be at least five seconds")
    readiness = evaluate_main_study_readiness(
        repository_root=ROOT,
        governance_path=governance_path,
        catalogue_record_path=catalogue_record_path,
        selection_record_path=selection_record_path,
        screen_output_root=screen_output_root,
        pilot_output_root=pilot_output_root,
        active_bundle_root=active_bundle_root,
        final_artifact_root=final_artifact_root,
    )
    if readiness.main_study != "READY":
        primary = readiness.blockers[0] if readiness.blockers else "readiness_not_pass"
        raise StudyPreflightError(
            f"Main Study V2 is blocked: {primary}; all blockers={list(readiness.blockers)}"
        )
    if None in (
        catalogue_record_path,
        selection_record_path,
        screen_output_root,
        active_bundle_root,
    ):
        raise StudyPreflightError("Main Study V2 active evidence paths are incomplete")
    verify_active_study_bundle(
        bundle_root=active_bundle_root,
        repository_root=ROOT,
        artifact_root=final_artifact_root,
        selection_record_path=selection_record_path,
        catalogue_record_path=catalogue_record_path,
        screen_output_root=screen_output_root,
        pilot_output_root=pilot_output_root,
    )
    key = require_live_gate(
        live_requested=live_requested,
        live_confirmed=live_confirmed,
        protocol_confirmed=protocol_confirmed,
        environ=environ,
    )
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    models = load_models(final_artifact_root / FINAL_MODELS_RELATIVE_PATH)
    rows = generate_manifest(scripts, models, study_version="study-v2.1.0")
    manifest_errors = validate_manifest(rows, models=models, expected_study_version="study-v2.1.0")
    if manifest_errors:
        raise StudyPreflightError("; ".join(manifest_errors))
    expected = manifest_dataframe(rows).fillna("").astype(str).reset_index(drop=True)
    actual = (
        pd.read_csv(final_artifact_root / FINAL_MANIFEST_RELATIVE_PATH)
        .fillna("")
        .astype(str)
        .reset_index(drop=True)
    )
    if list(actual.columns) != list(expected.columns) or not actual.equals(expected):
        raise StudyPreflightError("Final active manifest differs from selected configuration")
    model_ids = resolve_model_ids(models)
    provider = provider_factory(api_key=key)
    provider.set_retry_rate_limits(False)
    provider.set_minimum_request_interval(request_interval_seconds)
    provider.set_provider_routing(models.provider_routing)
    try:
        provider.validate_exact_models_strict(
            tuple(model_ids.values()),
            minimum_context_tokens=models.provider_routing.minimum_context_tokens,
            timeout_seconds=min(20, models.generation.timeout_seconds),
        )
    except (OSError, RuntimeError, ValueError) as error:
        path = _store_preflight_failure(model_ids, error, key)
        raise StudyPreflightError(
            f"Catalogue qualification failed before POST; record: {path}"
        ) from error
    store = RawRunStore(output_root)
    execute_manifest_rows(
        rows=rows,
        scripts=scripts,
        histories=histories,
        models=models,
        provider=provider,
        store=store,
        data_status="main_study",
        maximum_http_attempts=maximum_http_attempts,
        max_new_conversations=max_new_conversations,
        stop_after_execution_order=stop_after_execution_order,
    )
    return build_execution_summary(planned_rows=rows, store=store)


def _print_offline(summary: dict[str, Any]) -> None:
    print("MAIN STUDY V2 OFFLINE PREFLIGHT - NO NETWORK CALL OCCURRED")
    print(
        f"Study={summary['study_version']}; configuration={summary['configuration_version']}; "
        f"generation={summary['generation_version']}"
    )
    print(
        f"{summary['planned_conversations']} balanced conversations; "
        f"{summary['planned_response_slots']} planned response slots"
    )
    for slot, model_id in summary["models"].items():
        print(f"{slot}: {model_id}")
    print("Historical protocol bundle verified; active collection is superseded/pending.")
    print(f"Pilot V4: {summary['pilot_v4_qualification']}")
    print(f"Pilot V5: {summary['pilot_v5_qualification']}")
    print(f"replacement endpoint: {summary['replacement_endpoint_status']}")
    print(f"Pilot V6: {summary['pilot_v6_status']}")
    print(f"replacement screen: {summary['replacement_screen']}")
    print(f"replacement selection: {summary['replacement_selection']}")
    print(f"active final bundle: {summary['active_bundle']}")
    print(f"main study: {summary['main_study_status']}")
    print(f"blocker: {summary['replacement_blocker']}")
    print(
        "Main-study live collection blocked: "
        f"{'yes' if summary['main_study_live_blocked'] else 'no'}"
    )
    print(
        "Protocol confirmation is an operator attestation; it is not evidence of "
        "supervisor, ethics, rubric or data-management approval."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--confirm-protocol-frozen", action="store_true")
    parser.add_argument("--max-http-attempts", type=int)
    parser.add_argument("--max-new-conversations", type=int)
    parser.add_argument("--stop-after-execution-order", type=int)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--pilot-output-root", type=Path, default=TECHNICAL_PILOT_OUTPUT_ROOT)
    parser.add_argument("--catalogue-record", type=Path)
    parser.add_argument("--selection-record", type=Path)
    parser.add_argument("--screen-output-root", type=Path)
    parser.add_argument("--active-bundle-root", type=Path)
    parser.add_argument("--final-artifact-root", type=Path, default=ROOT)
    parser.add_argument("--governance", type=Path, default=GOVERNANCE_PATH)
    parser.add_argument(
        "--request-interval-seconds", type=float, default=MINIMUM_REQUEST_INTERVAL_SECONDS
    )
    args = parser.parse_args(argv)
    try:
        if not args.live:
            _print_offline(build_offline_preflight(pilot_output_root=args.pilot_output_root))
            return 0
        if args.max_http_attempts is None:
            raise StudyPreflightError("Live study requires an explicit --max-http-attempts value")
        load_dotenv(ROOT / ".env", override=False)
        summary = execute_live_study(
            maximum_http_attempts=args.max_http_attempts,
            live_requested=True,
            live_confirmed=args.confirm_live,
            protocol_confirmed=args.confirm_protocol_frozen,
            output_root=args.output_root,
            max_new_conversations=args.max_new_conversations,
            stop_after_execution_order=args.stop_after_execution_order,
            request_interval_seconds=args.request_interval_seconds,
            pilot_output_root=args.pilot_output_root,
            catalogue_record_path=args.catalogue_record,
            selection_record_path=args.selection_record,
            screen_output_root=args.screen_output_root,
            active_bundle_root=args.active_bundle_root,
            final_artifact_root=args.final_artifact_root,
            governance_path=args.governance,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_execution_summary("MAIN STUDY V2 - AGGREGATE EXECUTION STATUS", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
