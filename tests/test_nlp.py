"""Tests for deterministic, network-free lexical and TF-IDF features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.nlp_features import (
    add_similarity_features,
    extract_text_features,
    load_lexicon_config,
    project_responses_2d,
    tfidf_cosine_similarity,
    top_tfidf_terms,
)


def test_versioned_lexicons_load_from_readable_yaml() -> None:
    config = load_lexicon_config()
    assert config.version == "1.0.0"
    assert {
        "certainty",
        "uncertainty_alternatives",
        "endorsement",
        "grounding",
        "action_advice",
        "discouragement_refusal",
        "support_wellbeing",
    } == set(config.categories)
    assert config.limitations


def test_empty_and_punctuation_only_text_are_safe() -> None:
    empty = extract_text_features("")
    punctuation = extract_text_features("?!...")

    assert empty["word_count"] == 0
    assert empty["sentence_count"] == 0
    assert empty["lexical_diversity"] == 0.0
    assert empty["certainty_density"] == 0.0
    assert punctuation["word_count"] == 0
    assert punctuation["sentence_count"] == 0
    assert punctuation["question_count"] == 1


def test_casing_phrases_pronouns_and_densities_are_deterministic() -> None:
    text = (
        "I DEFINITELY agree? You might consider another explanation. "
        "YOU should ask a trusted person."
    )
    first = extract_text_features(text)
    second = extract_text_features(text)

    assert first == second
    assert first["sentence_count"] == 3
    assert first["certainty_count"] == 1
    assert first["uncertainty_alternatives_count"] == 2
    assert first["action_advice_count"] == 3
    assert first["support_wellbeing_count"] == 1
    assert first["first_person_count"] == 1
    assert first["second_person_count"] == 2
    assert first["question_count"] == 1
    assert first["certainty_density"] == pytest.approx(1 / first["word_count"])


def test_short_text_lexical_diversity_and_pair_similarity() -> None:
    features = extract_text_features("Hello hello!")
    assert features["word_count"] == 2
    assert features["sentence_count"] == 1
    assert features["lexical_diversity"] == 0.5
    assert tfidf_cosine_similarity("same short text", "same short text") == pytest.approx(1.0)
    assert tfidf_cosine_similarity("...", "?") == 0.0


def test_response_user_similarity_and_turn_drift_respect_conversations() -> None:
    frame = pd.DataFrame(
        [
            {
                "conversation_id": "a",
                "turn_number": 1,
                "user_message": "ordinary explanation",
                "response_text": "ordinary explanation",
            },
            {
                "conversation_id": "a",
                "turn_number": 2,
                "user_message": "could there be another explanation",
                "response_text": "ordinary explanation",
            },
            {
                "conversation_id": "b",
                "turn_number": 1,
                "user_message": "unrelated words",
                "response_text": "a separate response",
            },
        ]
    )
    result = add_similarity_features(frame)

    assert result.loc[0, "response_user_tfidf_similarity"] == pytest.approx(1.0)
    assert np.isnan(result.loc[0, "turn_to_turn_tfidf_similarity"])
    assert result.loc[1, "turn_to_turn_tfidf_similarity"] == pytest.approx(1.0)
    assert result.loc[1, "lexical_drift"] == pytest.approx(0.0)
    # The first turn of conversation b must not compare with conversation a.
    assert np.isnan(result.loc[2, "turn_to_turn_tfidf_similarity"])


def test_top_terms_skip_underpopulated_and_empty_groups() -> None:
    frame = pd.DataFrame(
        {
            "model": ["a", "a", "b", "c", "c"],
            "response_text": [
                "grounding common words",
                "grounding common response",
                "only singleton",
                "...",
                "?!",
            ],
        }
    )
    terms = top_tfidf_terms(frame, group_cols=["model"], top_n=4, min_documents=2)

    assert set(terms["model"]) == {"a"}
    assert "grounding" in set(terms["term"])
    assert terms["document_count"].eq(2).all()


def test_two_dimensional_projection_has_a_short_corpus_guard_and_is_repeatable() -> None:
    short = pd.DataFrame({"response_text": ["one response", "two response"]})
    unavailable = project_responses_2d(short)
    assert unavailable.empty
    assert unavailable.attrs["projection_available"] is False
    assert "at least 3" in unavailable.attrs["reason"]

    corpus = pd.DataFrame(
        {
            "response_text": [
                "ordinary evidence and another explanation",
                "step back and check observable facts",
                "trusted support and wellbeing matter",
                "certainty alone does not prove monitoring",
            ]
        }
    )
    first = project_responses_2d(corpus)
    second = project_responses_2d(corpus)
    assert first.attrs["projection_available"] is True
    assert len(first) == len(corpus)
    np.testing.assert_allclose(first[["svd_x", "svd_y"]], second[["svd_x", "svd_y"]])
