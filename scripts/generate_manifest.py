# ruff: noqa: E402
"""Generate and validate the configuration-driven study manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_models, load_scripts
from src.manifest import (
    generate_manifest,
    manifest_dataframe,
    validate_manifest,
    write_manifest_csv,
)

HISTORICAL_MODELS_PATH = ROOT / "config" / "archive" / "models-study-v2-generation-v3-nemotron.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "experiment_manifest.csv",
    )
    parser.add_argument("--validate", action="store_true")
    arguments = parser.parse_args()
    scripts = load_scripts(ROOT / "config" / "scenarios")
    models = load_models(HISTORICAL_MODELS_PATH)
    rows = generate_manifest(scripts, models)
    errors = validate_manifest(rows, models=models)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if arguments.validate:
        if not arguments.output.is_file():
            print(f"ERROR: Manifest is missing: {arguments.output}")
            return 1
        expected = manifest_dataframe(rows).fillna("").astype(str).reset_index(drop=True)
        actual = pd.read_csv(arguments.output).fillna("").astype(str).reset_index(drop=True)
        if list(actual.columns) != list(expected.columns) or not actual.equals(expected):
            print("ERROR: Historical Study V2 manifest differs from archived configuration")
            return 1
    else:
        write_manifest_csv(rows, arguments.output, models=models)
    print(f"Manifest valid: {len(rows)} unique balanced runs")
    print(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
