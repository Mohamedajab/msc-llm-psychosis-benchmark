"""Run or inspect the three supplementary LLM judge queues; offline by default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.judge_execution import (
    JudgeExecutionError,
    claim_worker,
    clear_stop_request,
    default_judge_paths,
    judge_progress,
    load_job_state,
    load_judge_configuration,
    release_worker,
    reserve_worker,
    run_judge_preflight,
    run_judges,
)


def _print_preflight(preflight) -> None:  # noqa: ANN001
    print("LLM JUDGES PREFLIGHT - NO NETWORK CALL OCCURRED")
    print(f"ready={str(preflight.ready).lower()}")
    print(f"items={preflight.item_count}/432")
    print(f"judges={list(preflight.selected_judges)}")
    print(f"checks={preflight.checks}")
    print(f"blockers={list(preflight.blockers)}")
    print("network_requests=0")


def _print_progress(*, output_root: Path, configuration_path: Path) -> None:
    configuration = load_judge_configuration(configuration_path)
    rows = judge_progress(judge_root=output_root, configuration=configuration)
    for row in rows:
        print(
            f"{row.judge_id}: completed={row.completed}/432 "
            f"retryable_errors={row.retryable_errors} permanent_errors={row.permanent_errors}"
        )
    print(f"total={sum(row.completed for row in rows)}/1296")


def main(argv: list[str] | None = None) -> int:
    paths = default_judge_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--smoke-one-each", action="store_true")
    parser.add_argument("--judge", action="append", dest="judges")
    parser.add_argument("--lock-token")
    parser.add_argument("--configuration", type=Path, default=paths["configuration"])
    parser.add_argument("--raw-root", type=Path, default=paths["raw_study"])
    parser.add_argument("--output-root", type=Path, default=paths["judge_root"])
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env", override=False)
    if not args.live:
        preflight = run_judge_preflight(
            repository_root=ROOT,
            raw_root=args.raw_root,
            judge_root=args.output_root,
            configuration_path=args.configuration,
            judge_ids=args.judges,
            environ=dict(os.environ),
            require_smoke_validation=not args.smoke_one_each,
        )
        _print_preflight(preflight)
        _print_progress(output_root=args.output_root, configuration_path=args.configuration)
        return 0

    if not args.confirm_live or os.environ.get("RUN_LIVE_JUDGES") != "1":
        print("ERROR: live judging requires --confirm-live and RUN_LIVE_JUDGES=1", file=sys.stderr)
        return 2
    preflight = run_judge_preflight(
        repository_root=ROOT,
        raw_root=args.raw_root,
        judge_root=args.output_root,
        configuration_path=args.configuration,
        judge_ids=args.judges,
        environ=dict(os.environ),
        require_smoke_validation=not args.smoke_one_each,
    )
    lock_token = args.lock_token or reserve_worker(args.output_root)
    lock_claimed = False
    if lock_token:
        claim_worker(args.output_root, lock_token)
        lock_claimed = True
        # The claimed worker is intentionally ignored by the preflight snapshot.
        preflight = preflight.model_copy(
            update={
                "ready": all(
                    value for name, value in preflight.checks.items() if name != "no_active_worker"
                ),
                "blockers": tuple(
                    blocker
                    for blocker in preflight.blockers
                    if blocker != "judge_worker_already_running"
                ),
            }
        )
    if not preflight.ready:
        _print_preflight(preflight)
        if lock_claimed:
            release_worker(args.output_root, lock_token)
        return 2
    try:
        if args.lock_token is None:
            clear_stop_request(args.output_root)
        asyncio.run(
            run_judges(
                repository_root=ROOT,
                raw_root=args.raw_root,
                judge_root=args.output_root,
                configuration_path=args.configuration,
                judge_ids=args.judges,
                smoke_one_each=args.smoke_one_each,
            )
        )
        _print_progress(output_root=args.output_root, configuration_path=args.configuration)
        state = load_job_state(args.output_root)
        return 0 if state.status in {"SMOKE_COMPLETE", "COMPLETE"} else 1
    except (OSError, ValueError, JudgeExecutionError) as error:
        print(f"ERROR: judge worker stopped ({type(error).__name__})", file=sys.stderr)
        return 2
    finally:
        if lock_claimed:
            release_worker(args.output_root, lock_token)


if __name__ == "__main__":
    raise SystemExit(main())
