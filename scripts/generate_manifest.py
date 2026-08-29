# ruff: noqa: E402
"""Generate and validate the configuration-driven study manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_models, load_scripts
from src.manifest import generate_manifest, validate_manifest, write_manifest_csv


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
    models = load_models(ROOT / "config" / "models.yaml")
    rows = generate_manifest(scripts, models)
    errors = validate_manifest(rows, models=models)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    write_manifest_csv(rows, arguments.output, models=models)
    print(f"Manifest valid: {len(rows)} unique balanced runs")
    print(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
