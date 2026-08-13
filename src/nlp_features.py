"""Deterministic, offline lexical features for saved assistant responses.

The functions in this module are deliberately transparent.  They use exact
token/phrase matching and TF-IDF fitted only to the supplied text; they do not
download a language model or call a remote service.  The resulting values are
exploratory textual signals, not clinical labels and not substitutes for the
human rubric.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

DEFAULT_LEXICON_PATH = Path(__file__).resolve().parents[1] / "config" / "nlp_lexicons.yaml"

# Keep apostrophised forms as one word.  ``[^\W_]`` means a Unicode letter or
# digit but excludes underscores, making the behaviour less ASCII-centric.
_WORD_RE = re.compile(r"[^\W_]+(?:['\N{RIGHT SINGLE QUOTATION MARK}][^\W_]+)*", re.UNICODE)
_QUESTION_RE = re.compile(r"\?+")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]+|[\r\n]+")

FIRST_PERSON_PRONOUNS = frozenset(
    {
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "us",
        "our",
        "ours",
        "ourselves",
        "i'm",
        "i've",
        "i'd",
        "i'll",
        "we're",
        "we've",
        "we'd",
        "we'll",
    }
)
SECOND_PERSON_PRONOUNS = frozenset(
    {
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "you're",
        "you've",
        "you'd",
        "you'll",
    }
)


class LexiconConfigurationError(ValueError):
    """Raised when the versioned lexical configuration is malformed."""


@dataclass(frozen=True)
class LexiconConfig:
    """Validated, immutable view of ``config/nlp_lexicons.yaml``."""

    version: str
    status: str
    categories: Mapping[str, tuple[str, ...]]
    limitations: tuple[str, ...]


def _normalise_text(value: object) -> str:
    """Convert a nullable cell to text without turning NaN into ``"nan"``."""

    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def tokenize_words(text: object) -> list[str]:
    """Return deterministic case-folded Unicode word tokens."""

    return [match.group(0).casefold() for match in _WORD_RE.finditer(_normalise_text(text))]


def count_sentences(text: object) -> int:
    """Count token-bearing segments separated by sentence punctuation/newlines."""

    raw = _normalise_text(text)
    return sum(bool(tokenize_words(part)) for part in _SENTENCE_BOUNDARY_RE.split(raw))


def load_lexicon_config(path: str | Path = DEFAULT_LEXICON_PATH) -> LexiconConfig:
    """Load and validate the readable, versioned YAML lexical configuration."""

    file_path = Path(path)
    if not file_path.is_file():
        raise LexiconConfigurationError(f"Lexicon configuration not found: {file_path}")
    try:
        with file_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise LexiconConfigurationError(
            f"Malformed YAML in lexicon configuration {file_path}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise LexiconConfigurationError("Lexicon configuration must be a mapping")
    version = raw.get("version")
    categories = raw.get("categories")
    if not isinstance(version, str) or not version.strip():
        raise LexiconConfigurationError("Lexicon configuration requires a version")
    if not isinstance(categories, dict) or not categories:
        raise LexiconConfigurationError("Lexicon configuration requires categories")

    clean_categories: dict[str, tuple[str, ...]] = {}
    for category, markers in categories.items():
        if not isinstance(category, str) or not category.strip():
            raise LexiconConfigurationError("Lexicon category names must be nonblank strings")
        if not isinstance(markers, list) or not markers:
            raise LexiconConfigurationError(
                f"Lexicon category {category!r} requires a non-empty marker list"
            )
        clean_markers: list[str] = []
        for marker in markers:
            if not isinstance(marker, str) or not tokenize_words(marker):
                raise LexiconConfigurationError(
                    f"Lexicon marker in {category!r} must contain a word"
                )
            clean_markers.append(marker.strip().casefold())
        # A duplicate should not silently double a count.
        clean_categories[category.strip()] = tuple(dict.fromkeys(clean_markers))

    limitations = raw.get("limitations", [])
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise LexiconConfigurationError("Lexicon limitations must be a list of strings")
    status = raw.get("status", "")
    if not isinstance(status, str):
        raise LexiconConfigurationError("Lexicon status must be a string")
    return LexiconConfig(
        version=version.strip(),
        status=status.strip(),
        categories=clean_categories,
        limitations=tuple(limitations),
    )


def load_lexicons(
    path: str | Path = DEFAULT_LEXICON_PATH,
) -> dict[str, tuple[str, ...]]:
    """Return just the category mapping for callers that do not need metadata."""

    return dict(load_lexicon_config(path).categories)


def _marker_count(tokens: Sequence[str], marker: str) -> int:
    marker_tokens = tokenize_words(marker)
    width = len(marker_tokens)
    if not tokens or not width or width > len(tokens):
        return 0
    target = tuple(marker_tokens)
    return sum(
        tuple(tokens[index : index + width]) == target for index in range(len(tokens) - width + 1)
    )


def extract_text_features(
    text: object,
    lexicons: LexiconConfig | Mapping[str, Sequence[str]] | None = None,
) -> dict[str, int | float | str]:
    """Extract explainable lexical counts and densities from one response.

    ``*_density`` values are proportions per word.  The matching count is also
    returned, so a per-100-word value can be obtained without ambiguity.  Exact
    phrase occurrences are counted; stemming, sentiment and negation inference
    are intentionally not attempted.
    """

    if lexicons is None:
        config = load_lexicon_config()
        categories = config.categories
        version = config.version
    elif isinstance(lexicons, LexiconConfig):
        categories = lexicons.categories
        version = lexicons.version
    else:
        categories = lexicons
        version = "unversioned"

    tokens = tokenize_words(text)
    word_count = len(tokens)
    unique_word_count = len(set(tokens))
    first_person_count = sum(token in FIRST_PERSON_PRONOUNS for token in tokens)
    second_person_count = sum(token in SECOND_PERSON_PRONOUNS for token in tokens)
    denominator = float(word_count) if word_count else 1.0

    features: dict[str, int | float | str] = {
        "nlp_lexicon_version": version,
        "word_count": word_count,
        "sentence_count": count_sentences(text),
        "unique_word_count": unique_word_count,
        "lexical_diversity": unique_word_count / denominator if word_count else 0.0,
        "first_person_count": first_person_count,
        "first_person_proportion": first_person_count / denominator if word_count else 0.0,
        "second_person_count": second_person_count,
        "second_person_proportion": second_person_count / denominator if word_count else 0.0,
        "question_count": len(_QUESTION_RE.findall(_normalise_text(text))),
    }
    for category, markers in categories.items():
        count = sum(_marker_count(tokens, marker) for marker in markers)
        density = count / denominator if word_count else 0.0
        features[f"{category}_count"] = count
        features[f"{category}_density"] = density
        features[f"{category}_density_per_100_words"] = density * 100.0
    return features


def text_feature_frame(
    texts: Iterable[object],
    lexicons: LexiconConfig | Mapping[str, Sequence[str]] | None = None,
) -> pd.DataFrame:
    """Extract lexical features for an iterable while preserving row order."""

    return pd.DataFrame([extract_text_features(text, lexicons) for text in texts])


def add_lexical_features(
    frame: pd.DataFrame,
    *,
    text_col: str = "response_text",
    lexicons: LexiconConfig | Mapping[str, Sequence[str]] | None = None,
) -> pd.DataFrame:
    """Return a copy of a response table with deterministic lexical columns."""

    if text_col not in frame.columns:
        raise KeyError(f"Missing text column: {text_col}")
    output = frame.reset_index(drop=True).copy()
    feature_rows = text_feature_frame(output[text_col], lexicons)
    for column in feature_rows.columns:
        output[column] = feature_rows[column].to_numpy()
    return output


def _vectorizer(ngram_range: tuple[int, int] = (1, 2)) -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=True,
        token_pattern=r"(?u)\b\w[\w'’]*\b",
        ngram_range=ngram_range,
        norm="l2",
    )


def tfidf_cosine_similarity(text_a: object, text_b: object) -> float:
    """Return TF-IDF cosine similarity for a pair, or zero for blank vocabulary."""

    texts = [_normalise_text(text_a), _normalise_text(text_b)]
    try:
        matrix = _vectorizer().fit_transform(texts)
    except ValueError:
        return 0.0
    similarity = float(matrix[0].multiply(matrix[1]).sum())
    return min(1.0, max(0.0, similarity))


def add_similarity_features(
    frame: pd.DataFrame,
    *,
    response_col: str = "response_text",
    user_col: str = "user_message",
    conversation_col: str = "conversation_id",
    turn_col: str = "turn_number",
) -> pd.DataFrame:
    """Add response/user similarity and within-conversation response drift.

    One vectorizer is fitted to the supplied response and user corpus, making
    row values comparable within that analysis.  The first response in each
    conversation has no predecessor, so its turn similarity and drift are
    missing rather than fabricated.
    """

    missing = [
        column
        for column in (response_col, user_col, conversation_col, turn_col)
        if column not in frame.columns
    ]
    if missing:
        raise KeyError(f"Missing similarity columns: {', '.join(missing)}")

    output = frame.reset_index(drop=True).copy()
    size = len(output)
    response_user = np.zeros(size, dtype=float)
    previous_similarity = np.full(size, np.nan, dtype=float)
    drift = np.full(size, np.nan, dtype=float)
    if not size:
        output["response_user_tfidf_similarity"] = response_user
        output["turn_to_turn_tfidf_similarity"] = previous_similarity
        output["previous_response_tfidf_similarity"] = previous_similarity.copy()
        output["turn_to_turn_tfidf_drift"] = drift
        output["lexical_drift"] = drift.copy()
        return output

    responses = [_normalise_text(value) for value in output[response_col]]
    users = [_normalise_text(value) for value in output[user_col]]
    try:
        matrix = _vectorizer().fit_transform(responses + users)
    except ValueError:
        matrix = None

    if matrix is not None:
        response_matrix = matrix[:size]
        user_matrix = matrix[size:]
        response_user = np.asarray(response_matrix.multiply(user_matrix).sum(axis=1)).ravel()

        # Stable mergesort preserves input order when turn numbers tie.
        ordered_positions = output.assign(_position=np.arange(size)).sort_values(
            [conversation_col, turn_col, "_position"], kind="mergesort"
        )
        for _, group in ordered_positions.groupby(conversation_col, sort=False, dropna=False):
            positions = group["_position"].astype(int).tolist()
            for previous, current in pairwise(positions):
                similarity = float(
                    response_matrix[previous].multiply(response_matrix[current]).sum()
                )
                similarity = min(1.0, max(0.0, similarity))
                previous_similarity[current] = similarity
                drift[current] = 1.0 - similarity

    output["response_user_tfidf_similarity"] = response_user
    output["turn_to_turn_tfidf_similarity"] = previous_similarity
    output["previous_response_tfidf_similarity"] = previous_similarity.copy()
    output["turn_to_turn_tfidf_drift"] = drift
    output["lexical_drift"] = drift.copy()
    return output


def extract_response_features(
    frame: pd.DataFrame,
    *,
    response_col: str = "response_text",
    user_col: str = "user_message",
    conversation_col: str = "conversation_id",
    turn_col: str = "turn_number",
    lexicons: LexiconConfig | Mapping[str, Sequence[str]] | None = None,
) -> pd.DataFrame:
    """Apply lexical and TF-IDF trajectory features to a response table."""

    lexical = add_lexical_features(frame, text_col=response_col, lexicons=lexicons)
    return add_similarity_features(
        lexical,
        response_col=response_col,
        user_col=user_col,
        conversation_col=conversation_col,
        turn_col=turn_col,
    )


def _top_term_columns(group_cols: Sequence[str]) -> list[str]:
    return [
        *group_cols,
        "rank",
        "term",
        "mean_tfidf",
        "document_frequency",
        "document_count",
    ]


def top_tfidf_terms(
    frame: pd.DataFrame,
    *,
    text_col: str = "response_text",
    group_cols: Sequence[str] = (),
    top_n: int = 10,
    min_documents: int = 2,
    ngram_range: tuple[int, int] = (1, 2),
) -> pd.DataFrame:
    """Return deterministic top terms within sufficiently populated groups.

    Each group gets its own TF-IDF fit.  Groups below ``min_documents`` and
    groups with punctuation-only text are skipped instead of raising an empty
    vocabulary error.  Ties are resolved alphabetically.
    """

    if text_col not in frame.columns:
        raise KeyError(f"Missing text column: {text_col}")
    missing_groups = [column for column in group_cols if column not in frame.columns]
    if missing_groups:
        raise KeyError(f"Missing grouping columns: {', '.join(missing_groups)}")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    if min_documents < 1:
        raise ValueError("min_documents must be at least 1")

    columns = _top_term_columns(group_cols)
    if frame.empty:
        return pd.DataFrame(columns=columns)

    if group_cols:
        grouper: str | list[str]
        grouper = group_cols[0] if len(group_cols) == 1 else list(group_cols)
        groups = frame.groupby(grouper, sort=True, dropna=False)
    else:
        groups = [((), frame)]

    rows: list[dict[str, Any]] = []
    for key, group in groups:
        texts = [_normalise_text(value) for value in group[text_col]]
        texts = [text for text in texts if tokenize_words(text)]
        if len(texts) < min_documents:
            continue
        vectorizer = _vectorizer(ngram_range)
        try:
            matrix = vectorizer.fit_transform(texts)
        except ValueError:
            continue
        terms = vectorizer.get_feature_names_out()
        means = np.asarray(matrix.mean(axis=0)).ravel()
        frequencies = np.asarray((matrix > 0).sum(axis=0)).ravel()
        order = sorted(range(len(terms)), key=lambda index: (-means[index], terms[index]))

        key_values = key if isinstance(key, tuple) else (key,)
        group_values = dict(zip(group_cols, key_values, strict=True))
        for rank, index in enumerate(order[:top_n], start=1):
            rows.append(
                {
                    **group_values,
                    "rank": rank,
                    "term": str(terms[index]),
                    "mean_tfidf": float(means[index]),
                    "document_frequency": int(frequencies[index]),
                    "document_count": len(texts),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _empty_projection(frame: pd.DataFrame, reason: str) -> pd.DataFrame:
    output = frame.iloc[0:0].copy()
    output["svd_x"] = pd.Series(dtype=float)
    output["svd_y"] = pd.Series(dtype=float)
    output.attrs["projection_available"] = False
    output.attrs["reason"] = reason
    return output


def project_responses_2d(
    frame: pd.DataFrame,
    *,
    text_col: str = "response_text",
    min_documents: int = 3,
    random_state: int = 0,
    ngram_range: tuple[int, int] = (1, 2),
) -> pd.DataFrame:
    """Create an offline 2D TF-IDF/SVD map when the corpus can support it.

    An empty frame with a human-readable ``attrs['reason']`` is returned when
    there are too few nonblank documents/features.  This guard keeps dashboard
    empty states from crashing on the small technical pilot.
    """

    if text_col not in frame.columns:
        raise KeyError(f"Missing text column: {text_col}")
    if min_documents < 3:
        raise ValueError("A two-dimensional projection requires at least 3 documents")
    if frame.empty:
        return _empty_projection(frame, "No responses are available")

    texts = [_normalise_text(value) for value in frame[text_col]]
    nonblank_count = sum(bool(tokenize_words(text)) for text in texts)
    if nonblank_count < min_documents:
        return _empty_projection(
            frame,
            f"Need at least {min_documents} nonblank responses; found {nonblank_count}",
        )
    vectorizer = _vectorizer(ngram_range)
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return _empty_projection(frame, "The supplied responses have no TF-IDF vocabulary")
    if matrix.shape[1] < 3 or min(matrix.shape) < 3:
        return _empty_projection(
            frame,
            "Need at least 3 documents and 3 distinct TF-IDF features for a stable 2D map",
        )

    projection = TruncatedSVD(n_components=2, random_state=random_state).fit_transform(matrix)
    output = frame.reset_index(drop=True).copy()
    output["svd_x"] = projection[:, 0]
    output["svd_y"] = projection[:, 1]
    output.attrs["projection_available"] = True
    output.attrs["reason"] = ""
    return output


def conversation_records_to_frame(records: Iterable[Any]) -> pd.DataFrame:
    """Flatten current ``ConversationRecord`` objects into one row per turn."""

    rows: list[dict[str, Any]] = []
    for record in records:
        header = record.header
        for turn in record.turns:
            result = turn.result
            rows.append(
                {
                    "conversation_id": header.run_id,
                    "run_id": header.run_id,
                    "data_status": header.data_status,
                    "script_id": header.script_id,
                    "theme": getattr(header.theme, "value", header.theme),
                    "presentation_level": getattr(
                        header.presentation_level, "value", header.presentation_level
                    ),
                    "model_slot": header.model_slot,
                    "context_condition": getattr(
                        header.context_condition, "value", header.context_condition
                    ),
                    "repetition": header.repetition,
                    "turn_number": turn.turn_number,
                    "user_message": turn.user_message,
                    "response_text": result.text or "",
                    "observation_status": getattr(result.status, "value", result.status),
                }
            )
    return pd.DataFrame(rows)


# Descriptive aliases used in notebooks/dashboard code.
compute_nlp_features = extract_response_features
tfidf_similarity = tfidf_cosine_similarity
tfidf_response_map = project_responses_2d


__all__ = [
    "DEFAULT_LEXICON_PATH",
    "FIRST_PERSON_PRONOUNS",
    "SECOND_PERSON_PRONOUNS",
    "LexiconConfig",
    "LexiconConfigurationError",
    "add_lexical_features",
    "add_similarity_features",
    "compute_nlp_features",
    "conversation_records_to_frame",
    "count_sentences",
    "extract_response_features",
    "extract_text_features",
    "load_lexicon_config",
    "load_lexicons",
    "project_responses_2d",
    "text_feature_frame",
    "tfidf_cosine_similarity",
    "tfidf_response_map",
    "tfidf_similarity",
    "tokenize_words",
    "top_tfidf_terms",
]
