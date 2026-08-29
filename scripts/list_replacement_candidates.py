"""List technically eligible replacement candidates; offline unless fully gated."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.replacement_screening import (
    CATALOGUE_ENDPOINT,
    build_catalogue_evidence,
    persist_catalogue_evidence,
)

DEFAULT_EVIDENCE_ROOT = ROOT / "data" / "private"


class CatalogueDiscoveryError(RuntimeError):
    """A live catalogue lookup did not satisfy the independent safety gates."""


def require_live_gates(
    *,
    live_requested: bool,
    live_confirmed: bool,
    environ: Mapping[str, str] | None = None,
) -> None:
    values = os.environ if environ is None else environ
    if not live_requested:
        raise CatalogueDiscoveryError("Live catalogue lookup requires --live")
    if not live_confirmed:
        raise CatalogueDiscoveryError("Live catalogue lookup requires --confirm-live")
    if values.get("RUN_LIVE_SCREEN") != "1":
        raise CatalogueDiscoveryError("Live catalogue lookup requires RUN_LIVE_SCREEN=1")


def fetch_catalogue(*, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """Make the workflow's one metadata GET; never make a generation request."""

    try:
        with httpx.Client(transport=transport, timeout=20) as client:
            response = client.get(CATALOGUE_ENDPOINT)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise CatalogueDiscoveryError("OpenRouter catalogue retrieval failed") from error
    entries = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(entries, list):
        raise CatalogueDiscoveryError("OpenRouter catalogue response has no model list")
    return [dict(value) for value in entries if isinstance(value, Mapping)]


def execute_live_discovery(
    *,
    live_requested: bool,
    live_confirmed: bool,
    environ: Mapping[str, str] | None = None,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    catalogue_fetcher: Callable[[], list[dict[str, Any]]] = fetch_catalogue,
    retrieved_at: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    require_live_gates(
        live_requested=live_requested,
        live_confirmed=live_confirmed,
        environ=environ,
    )
    timestamp = retrieved_at or datetime.now(UTC)
    record = build_catalogue_evidence(catalogue_fetcher(), retrieved_at=timestamp)
    path = persist_catalogue_evidence(record, evidence_root)
    return record, path


def print_offline_status() -> None:
    print("REPLACEMENT CANDIDATE CATALOGUE - NOT RESEARCH DATA")
    print("catalogue_status=NOT_FETCHED")
    print("live_lookup_required=yes")
    print("network_requests=0")
    print("generation_requests=0")


def print_safe_catalogue(record: Mapping[str, Any], path: Path) -> None:
    evaluations = record["candidate_evaluations"]
    eligible = [value for value in evaluations if value["eligible"]]
    print("REPLACEMENT CANDIDATE CATALOGUE - NOT RESEARCH DATA")
    print("catalogue_status=FETCHED")
    print("network_requests=1")
    print("generation_requests=0")
    print(f"catalogue_evidence_hash={record['catalogue_evidence_hash']}")
    print(f"evaluated_candidates={len(evaluations)}; eligible_candidates={len(eligible)}")
    print(
        "exact_model_id | canonical_slug | display_name | zero_price | input | output | "
        "context | max_completion | parameters | expiration | specialisation | eligible | reasons"
    )
    for value in evaluations:
        print(
            f"{value['exact_model_id']} | {value['canonical_slug']} | "
            f"{value['display_name']} | "
            f"{str(value['zero_price_confirmed']).casefold()} | "
            f"{','.join(value['input_modalities']) or 'unreported'} | "
            f"{','.join(value['output_modalities']) or 'unreported'} | "
            f"{value['context_length']} | {value['maximum_completion_capability']} | "
            f"{','.join(value['relevant_supported_parameters']) or 'none'} | "
            f"{value['expiration_date']} | "
            f"{','.join(value['specialisation_warnings']) or 'none'} | "
            f"{str(value['eligible']).casefold()} | "
            f"{','.join(value['rejection_reasons']) or 'none'}"
        )
    print(f"deterministic_eligible_order={record['deterministic_eligible_order']}")
    print(f"catalogue_record={path.resolve()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    args = parser.parse_args(argv)
    if not args.live:
        print_offline_status()
        return 0
    try:
        record, path = execute_live_discovery(
            live_requested=True,
            live_confirmed=args.confirm_live,
            evidence_root=args.evidence_root,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_safe_catalogue(record, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
