"""Run or inspect the persisted Main Study V2 worker; offline by default."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.main_study import (
    DEFAULT_INITIAL_RETRY_WAIT_SECONDS,
    DEFAULT_MAXIMUM_AUTO_RESUMES,
    DEFAULT_MAXIMUM_RETRY_WAIT_SECONDS,
    default_paths,
    run_main_study_preflight,
    run_study_worker,
)


def _print_preflight(preflight) -> None:  # noqa: ANN001
    print("MAIN STUDY WORKER PREFLIGHT - NO NETWORK CALL OCCURRED")
    print(f"pilot_v6={preflight.pilot_v6}")
    print(f"final_pair_source={preflight.final_pair_source}")
    print(f"active_bundle={preflight.active_bundle}")
    print(f"governance={preflight.governance}")
    print(f"main_study={preflight.main_study}")
    print(f"checks={preflight.checks}")
    print(f"blockers={list(preflight.blockers)}")
    print("network_requests=0")


def main(argv: list[str] | None = None) -> int:
    paths = default_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--confirm-protocol-frozen", action="store_true")
    parser.add_argument("--lock-token")
    parser.add_argument("--job-root", type=Path, default=paths["job_root"])
    parser.add_argument("--output-root", type=Path, default=paths["raw_root"])
    parser.add_argument("--pilot-output-root", type=Path, default=paths["pilot_v6_root"])
    parser.add_argument("--active-bundle-root", type=Path, default=paths["active_bundle_root"])
    parser.add_argument("--governance", type=Path, default=paths["governance_path"])
    parser.add_argument("--max-auto-resumes", type=int, default=DEFAULT_MAXIMUM_AUTO_RESUMES)
    parser.add_argument(
        "--initial-retry-wait-seconds",
        type=int,
        default=DEFAULT_INITIAL_RETRY_WAIT_SECONDS,
    )
    parser.add_argument(
        "--maximum-retry-wait-seconds",
        type=int,
        default=DEFAULT_MAXIMUM_RETRY_WAIT_SECONDS,
    )
    args = parser.parse_args(argv)

    if not args.live:
        preflight = run_main_study_preflight(
            repository_root=ROOT,
            raw_root=args.output_root,
            job_root=args.job_root,
            pilot_v6_root=args.pilot_output_root,
            active_bundle_root=args.active_bundle_root,
            governance_path=args.governance,
            environ=dict(os.environ),
        )
        _print_preflight(preflight)
        return 0

    if not args.confirm_live or not args.confirm_protocol_frozen:
        print("ERROR: live worker requires both confirmation flags", file=sys.stderr)
        return 2
    if os.environ.get("RUN_LIVE_STUDY") != "1":
        print("ERROR: live worker requires RUN_LIVE_STUDY=1", file=sys.stderr)
        return 2
    load_dotenv(ROOT / ".env", override=False)
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("ERROR: live worker requires an API key", file=sys.stderr)
        return 2
    if not args.lock_token:
        print("ERROR: live worker requires a launcher reservation", file=sys.stderr)
        return 2
    try:
        return run_study_worker(
            repository_root=ROOT,
            job_root=args.job_root,
            raw_root=args.output_root,
            pilot_v6_root=args.pilot_output_root,
            active_bundle_root=args.active_bundle_root,
            governance_path=args.governance,
            lock_token=args.lock_token,
            maximum_auto_resumes=args.max_auto_resumes,
            initial_retry_wait_seconds=args.initial_retry_wait_seconds,
            maximum_retry_wait_seconds=args.maximum_retry_wait_seconds,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: main-study worker stopped ({type(error).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
