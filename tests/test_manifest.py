"""Full factorial study manifest tests."""

from pathlib import Path

from src.config_loader import generation_for_repetition, load_models, load_scripts
from src.manifest import generate_manifest, validate_manifest

ROOT = Path(__file__).parents[1]


def test_manifest_has_72_unique_balanced_runs_and_stable_order() -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    models = load_models(ROOT / "config" / "models.yaml")
    rows = generate_manifest(scripts, models)
    assert len(rows) == 72
    assert len(rows) * 6 == 432
    assert len({row.run_id for row in rows}) == 72
    assert len({row.requested_model_id for row in rows}) == 2
    assert validate_manifest(rows) == []
    assert [row.run_id for row in rows] == [
        row.run_id for row in generate_manifest(scripts, models)
    ]
    seeds_by_repetition = {
        repetition: {row.planned_seed for row in rows if row.repetition == repetition}
        for repetition in (1, 2)
    }
    assert seeds_by_repetition == {1: {20260814}, 2: {20260815}}
    assert generation_for_repetition(models, 1).seed == 20260814
    assert generation_for_repetition(models, 2).seed == 20260815
