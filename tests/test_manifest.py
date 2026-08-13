"""Full factorial study manifest tests."""

from pathlib import Path

from src.config_loader import load_models, load_scripts
from src.manifest import generate_manifest, validate_manifest

ROOT = Path(__file__).parents[1]


def test_manifest_has_72_unique_balanced_runs_and_stable_order() -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    models = load_models(ROOT / "config" / "models.yaml")
    rows = generate_manifest(scripts, models)
    assert len(rows) == 72
    assert len({row.run_id for row in rows}) == 72
    assert validate_manifest(rows) == []
    assert [row.run_id for row in rows] == [
        row.run_id for row in generate_manifest(scripts, models)
    ]
