"""Frozen script and configuration catalogue tests."""

from pathlib import Path

from src.config_loader import (
    load_histories,
    load_models,
    load_rubric,
    load_scripts,
    resolve_model_ids,
    validate_catalogue,
)
from src.payloads import assert_target_payload_clean
from src.schemas import ChatMessage

ROOT = Path(__file__).parents[1]


def test_exactly_nine_six_turn_scripts_and_balanced_prefixes() -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    assert len(scripts) == 9
    assert all(len(script.turns) == 6 for script in scripts)
    assert validate_catalogue(scripts, histories) == []


def test_target_script_and_prefix_text_contains_no_experiment_cues() -> None:
    scripts = load_scripts(ROOT / "config" / "scenarios")
    histories = load_histories(ROOT / "config" / "histories")
    for script in scripts:
        assert_target_payload_clean(
            [ChatMessage(role="user", content=turn) for turn in script.turns]
        )
    for history in histories:
        assert_target_payload_clean(history.messages)


def test_models_and_seven_axis_rubric_validate() -> None:
    models = load_models(ROOT / "config" / "models.yaml")
    rubric = load_rubric(ROOT / "config" / "rubric.yaml")
    assert set(models.model_slots) == {"model_minimax", "model_nemotron"}
    assert models.version == "2.2.0"
    assert models.generation.version == "generation-v4"
    assert models.generation.max_tokens == 4096
    assert models.generation.visible_response_instruction is None
    assert models.generation.reasoning_policy.reasoning_control_requested == "NATIVE"
    assert models.repetition_seeds == {1: 20260814, 2: 20260815}
    assert [axis.id for axis in rubric.axes] == ["A1", "A2", "A3", "B1", "B2", "B3", "C1"]
    assert rubric.primary_axes == ("A1", "A2", "A3")


def test_archived_generation_v2_remains_interpretable_and_unchanged() -> None:
    models = load_models(ROOT / "config" / "archive" / "models-study-v2-generation-v2.yaml")
    assert models.version == "2.0.0"
    assert models.generation.version == "generation-v2"
    assert models.generation.max_tokens == 512
    assert models.repetition_seeds == {1: 20260814, 2: 20260815}


def test_exact_models_resolve_from_versioned_configuration() -> None:
    models = load_models(ROOT / "config" / "models.yaml")
    assert resolve_model_ids(models) == {
        "model_minimax": "minimax/minimax-m3:free",
        "model_nemotron": "nvidia/nemotron-3-super-120b-a12b:free",
    }
