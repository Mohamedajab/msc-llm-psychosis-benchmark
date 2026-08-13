"""Guarded TF-IDF + logistic-regression baseline for human-labelled data.

This is an explainable future-analysis scaffold, not a result generator for the
small Friday technical pilot.  Every evaluation split is made at conversation
level.  When multiple themes are viable, an entire theme is held out; otherwise
the fallback is deterministic stratified grouped cross-validation.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

DEMO_ONLY_LABEL = "DEMO FIXTURE - NOT RESEARCH DATA"
TECHNICAL_PILOT_LABEL = "TECHNICAL PILOT - DESCRIPTIVE ONLY"
EXPLORATORY_LABEL = "EXPLORATORY BASELINE - NOT DISSERTATION EVIDENCE"


class InsufficientBaselineDataError(ValueError):
    """Raised when grouped supervised evaluation would not be credible."""


def _python_scalar(value: Any) -> Any:
    return value.item() if isinstance(value, np.generic) else value


def _sort_key(value: Any) -> tuple[str, str]:
    return (type(value).__name__, str(value))


def _required_columns(frame: pd.DataFrame, columns: Sequence[str], *, context: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing {context} columns: {', '.join(missing)}")


def _clean_labelled_rows(
    frame: pd.DataFrame,
    *,
    text_col: str,
    label_col: str,
    conversation_col: str,
) -> tuple[pd.DataFrame, int]:
    _required_columns(
        frame,
        (text_col, label_col, conversation_col),
        context="baseline",
    )
    usable = frame[label_col].notna() & frame[conversation_col].notna()
    clean = frame.loc[usable].reset_index(drop=True).copy()
    clean[text_col] = clean[text_col].fillna("").astype(str)
    return clean, int((~usable).sum())


def _validate_training_size(
    frame: pd.DataFrame,
    *,
    label_col: str,
    conversation_col: str,
    min_conversations: int,
    min_class_conversations: int,
) -> list[Any]:
    if min_conversations < 2:
        raise ValueError("min_conversations must be at least 2")
    if min_class_conversations < 2:
        raise ValueError("min_class_conversations must be at least 2")
    if frame.empty:
        raise InsufficientBaselineDataError("No labelled responses are available")

    conversations = frame[conversation_col].nunique(dropna=True)
    if conversations < min_conversations:
        raise InsufficientBaselineDataError(
            f"Need at least {min_conversations} labelled conversations; found {conversations}"
        )
    raw_classes = list(pd.unique(frame[label_col]))
    if len(raw_classes) < 2:
        raise InsufficientBaselineDataError(
            "At least two target classes are required for logistic regression"
        )
    if any(not isinstance(label, Hashable) for label in raw_classes):
        raise InsufficientBaselineDataError("Target labels must be hashable scalar values")
    classes = sorted((_python_scalar(value) for value in raw_classes), key=_sort_key)

    weak_classes: list[str] = []
    for label in classes:
        support = frame.loc[frame[label_col] == label, conversation_col].nunique()
        if support < min_class_conversations:
            weak_classes.append(f"{label!r} ({support} conversations)")
    if weak_classes:
        raise InsufficientBaselineDataError(
            "Every class must occur in at least "
            f"{min_class_conversations} conversations; insufficient: {', '.join(weak_classes)}"
        )
    return classes


def _encode_labels(values: pd.Series, classes: Sequence[Any]) -> np.ndarray:
    mapping = {value: index for index, value in enumerate(classes)}
    return np.asarray([mapping[value] for value in values], dtype=int)


def _theme_folds(
    frame: pd.DataFrame,
    *,
    theme_col: str,
    conversation_col: str,
    encoded_labels: np.ndarray,
    n_classes: int,
) -> list[tuple[np.ndarray, np.ndarray, Any]]:
    if theme_col not in frame.columns or frame[theme_col].isna().any():
        return []
    # Holding out a theme only guarantees group safety when each conversation
    # belongs to exactly one theme.
    per_conversation = frame.groupby(conversation_col, dropna=False)[theme_col].nunique()
    if (per_conversation != 1).any():
        return []
    themes = sorted((_python_scalar(value) for value in pd.unique(frame[theme_col])), key=_sort_key)
    if len(themes) < 2:
        return []

    folds: list[tuple[np.ndarray, np.ndarray, Any]] = []
    theme_values = frame[theme_col].to_numpy()
    all_classes = set(range(n_classes))
    for theme in themes:
        test = np.flatnonzero(theme_values == theme)
        train = np.flatnonzero(theme_values != theme)
        if not len(train) or not len(test):
            return []
        if set(np.unique(encoded_labels[train])) != all_classes:
            # A classifier cannot be evaluated if a held-out theme removes a
            # class completely from training.
            return []
        folds.append((train, test, theme))
    return folds


def _stratified_group_folds(
    frame: pd.DataFrame,
    *,
    conversation_col: str,
    encoded_labels: np.ndarray,
    n_classes: int,
    max_splits: int,
    random_state: int,
) -> list[tuple[np.ndarray, np.ndarray, None]]:
    groups = frame[conversation_col].to_numpy()
    group_support = [
        frame.loc[encoded_labels == label, conversation_col].nunique() for label in range(n_classes)
    ]
    n_splits = min(max_splits, frame[conversation_col].nunique(), min(group_support))
    if n_splits < 2:
        return []
    splitter = StratifiedGroupKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )
    all_classes = set(range(n_classes))
    folds: list[tuple[np.ndarray, np.ndarray, None]] = []
    for train, test in splitter.split(frame, encoded_labels, groups):
        if set(np.unique(encoded_labels[train])) == all_classes:
            folds.append((np.asarray(train), np.asarray(test), None))
    return folds


def _make_folds(
    frame: pd.DataFrame,
    *,
    label_col: str,
    conversation_col: str,
    theme_col: str | None,
    classes: Sequence[Any],
    prefer_leave_one_theme_out: bool,
    max_splits: int,
    random_state: int,
) -> tuple[str, list[tuple[np.ndarray, np.ndarray, Any | None]]]:
    encoded = _encode_labels(frame[label_col], classes)
    folds: list[tuple[np.ndarray, np.ndarray, Any | None]] = []
    if prefer_leave_one_theme_out and theme_col:
        folds = _theme_folds(
            frame,
            theme_col=theme_col,
            conversation_col=conversation_col,
            encoded_labels=encoded,
            n_classes=len(classes),
        )
        if len(folds) >= 2:
            return "leave_one_theme_out", folds

    folds = _stratified_group_folds(
        frame,
        conversation_col=conversation_col,
        encoded_labels=encoded,
        n_classes=len(classes),
        max_splits=max_splits,
        random_state=random_state,
    )
    if len(folds) < 2:
        raise InsufficientBaselineDataError(
            "Could not form at least two valid conversation-grouped folds with all "
            "target classes represented in training"
        )
    return "stratified_group_kfold", folds


def assert_no_group_leakage(
    frame: pd.DataFrame,
    splits: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    conversation_col: str = "conversation_id",
) -> None:
    """Raise if any conversation appears on both sides of a supplied split."""

    _required_columns(frame, (conversation_col,), context="group-check")
    for fold_number, (train, test) in enumerate(splits, start=1):
        train_groups = set(frame.iloc[np.asarray(train)][conversation_col])
        test_groups = set(frame.iloc[np.asarray(test)][conversation_col])
        overlap = train_groups & test_groups
        if overlap:
            raise AssertionError(
                f"Conversation leakage in fold {fold_number}: {sorted(map(str, overlap))}"
            )


def grouped_cv_splits(
    frame: pd.DataFrame,
    *,
    label_col: str = "label",
    conversation_col: str = "conversation_id",
    theme_col: str | None = "theme",
    min_conversations: int = 6,
    min_class_conversations: int = 2,
    prefer_leave_one_theme_out: bool = True,
    max_splits: int = 5,
    random_state: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build deterministic conversation-safe indices for external inspection.

    Rows with missing labels or conversation identifiers are excluded before
    indices are made.  The returned positional indices therefore address that
    cleaned/reset table; callers with missing rows should clean them first.
    """

    _required_columns(frame, (label_col, conversation_col), context="split")
    usable = frame[label_col].notna() & frame[conversation_col].notna()
    clean = frame.loc[usable].reset_index(drop=True).copy()
    classes = _validate_training_size(
        clean,
        label_col=label_col,
        conversation_col=conversation_col,
        min_conversations=min_conversations,
        min_class_conversations=min_class_conversations,
    )
    _, folds = _make_folds(
        clean,
        label_col=label_col,
        conversation_col=conversation_col,
        theme_col=theme_col,
        classes=classes,
        prefer_leave_one_theme_out=prefer_leave_one_theme_out,
        max_splits=max_splits,
        random_state=random_state,
    )
    splits = [(train, test) for train, test, _ in folds]
    assert_no_group_leakage(clean, splits, conversation_col=conversation_col)
    return splits


def build_baseline_pipeline(*, random_state: int = 0) -> Pipeline:
    """Construct the deliberately small explainable text baseline."""

    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    token_pattern=r"(?u)\b\w[\w'’]*\b",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=2_000,
                    random_state=random_state,
                ),
            ),
        ]
    )


def _class_balance(values: np.ndarray, classes: Sequence[Any]) -> list[dict[str, Any]]:
    total = len(values)
    return [
        {
            "label": _python_scalar(classes[class_index]),
            "count": int(np.sum(values == class_index)),
            "proportion": float(np.sum(values == class_index) / total) if total else 0.0,
        }
        for class_index in range(len(classes))
    ]


def _balanced_accuracy_or_none(
    truth: np.ndarray, prediction: np.ndarray, n_classes: int
) -> float | None:
    present = np.unique(truth)
    if len(present) < 2:
        return None
    recalls = [
        float(np.mean(prediction[truth == class_index] == class_index))
        for class_index in present
        if 0 <= class_index < n_classes
    ]
    return float(np.mean(recalls)) if recalls else None


def _coefficient_summary(
    pipeline: Pipeline, classes: Sequence[Any], *, top_n: int
) -> list[dict[str, Any]]:
    vectorizer: TfidfVectorizer = pipeline.named_steps["tfidf"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    terms = vectorizer.get_feature_names_out()
    coefficients = classifier.coef_
    if len(classes) == 2 and coefficients.shape[0] == 1:
        coefficients = np.vstack((-coefficients[0], coefficients[0]))

    rows: list[dict[str, Any]] = []
    for class_index, label in enumerate(classes):
        weights = coefficients[class_index]
        positive_order = sorted(
            range(len(terms)), key=lambda index: (-weights[index], terms[index])
        )[:top_n]
        negative_order = sorted(
            range(len(terms)), key=lambda index: (weights[index], terms[index])
        )[:top_n]
        rows.append(
            {
                "label": _python_scalar(label),
                "positive_terms": [
                    {"term": str(terms[index]), "coefficient": float(weights[index])}
                    for index in positive_order
                ],
                "negative_terms": [
                    {"term": str(terms[index]), "coefficient": float(weights[index])}
                    for index in negative_order
                ],
            }
        )
    return rows


def _evidence_label(
    frame: pd.DataFrame,
    *,
    demo_only: bool | None,
    data_status_col: str,
) -> tuple[bool, str]:
    statuses: set[str] = set()
    if data_status_col in frame.columns:
        statuses = {
            str(value).strip().casefold() for value in frame[data_status_col].dropna().unique()
        }
    inferred_demo = any(status in {"demo", "demo_fixture"} for status in statuses)
    is_demo = bool(demo_only) or inferred_demo
    if is_demo:
        return True, DEMO_ONLY_LABEL
    if statuses and statuses <= {"technical_pilot", "pilot"}:
        return False, TECHNICAL_PILOT_LABEL
    return False, EXPLORATORY_LABEL


def evaluate_grouped_baseline(
    frame: pd.DataFrame,
    *,
    text_col: str = "response_text",
    label_col: str = "label",
    conversation_col: str = "conversation_id",
    theme_col: str | None = "theme",
    data_status_col: str = "data_status",
    min_conversations: int = 6,
    min_class_conversations: int = 2,
    prefer_leave_one_theme_out: bool = True,
    max_splits: int = 5,
    random_state: int = 0,
    demo_only: bool | None = None,
    top_terms_per_class: int = 10,
    include_fitted_model: bool = False,
) -> dict[str, Any]:
    """Evaluate the baseline without ever splitting a conversation across folds.

    The target may be binary or multi-class/ordinal, but logistic regression
    treats ordinal values as nominal classes.  Returned results are descriptive
    and carry an explicit evidence-status label.
    """

    clean, excluded_rows = _clean_labelled_rows(
        frame,
        text_col=text_col,
        label_col=label_col,
        conversation_col=conversation_col,
    )
    classes = _validate_training_size(
        clean,
        label_col=label_col,
        conversation_col=conversation_col,
        min_conversations=min_conversations,
        min_class_conversations=min_class_conversations,
    )
    encoded = _encode_labels(clean[label_col], classes)
    strategy, folds = _make_folds(
        clean,
        label_col=label_col,
        conversation_col=conversation_col,
        theme_col=theme_col,
        classes=classes,
        prefer_leave_one_theme_out=prefer_leave_one_theme_out,
        max_splits=max_splits,
        random_state=random_state,
    )
    splits = [(train, test) for train, test, _ in folds]
    assert_no_group_leakage(clean, splits, conversation_col=conversation_col)

    fold_results: list[dict[str, Any]] = []
    aggregate_confusion = np.zeros((len(classes), len(classes)), dtype=int)
    for fold_number, (train, test, held_out_theme) in enumerate(folds, start=1):
        pipeline = build_baseline_pipeline(random_state=random_state)
        try:
            pipeline.fit(clean.iloc[train][text_col], encoded[train])
        except ValueError as error:
            if "empty vocabulary" in str(error).casefold():
                raise InsufficientBaselineDataError(
                    "Training responses contain no usable TF-IDF vocabulary"
                ) from error
            raise
        prediction = pipeline.predict(clean.iloc[test][text_col])
        matrix = confusion_matrix(encoded[test], prediction, labels=np.arange(len(classes)))
        aggregate_confusion += matrix
        train_groups = {
            _python_scalar(value) for value in clean.iloc[train][conversation_col].unique()
        }
        test_groups = {
            _python_scalar(value) for value in clean.iloc[test][conversation_col].unique()
        }
        if train_groups & test_groups:  # defensive duplicate of the public assertion
            raise RuntimeError("Internal error: grouped split leaked a conversation")

        train_themes: list[Any] = []
        test_themes: list[Any] = []
        if theme_col and theme_col in clean.columns:
            train_themes = sorted(
                (_python_scalar(value) for value in clean.iloc[train][theme_col].unique()),
                key=_sort_key,
            )
            test_themes = sorted(
                (_python_scalar(value) for value in clean.iloc[test][theme_col].unique()),
                key=_sort_key,
            )
        fold_results.append(
            {
                "fold": fold_number,
                "held_out_theme": _python_scalar(held_out_theme),
                "train_rows": len(train),
                "test_rows": len(test),
                "train_conversations": sorted(train_groups, key=_sort_key),
                "test_conversations": sorted(test_groups, key=_sort_key),
                "train_themes": train_themes,
                "test_themes": test_themes,
                "train_class_balance": _class_balance(encoded[train], classes),
                "test_class_balance": _class_balance(encoded[test], classes),
                "macro_f1": float(
                    f1_score(
                        encoded[test],
                        prediction,
                        labels=np.arange(len(classes)),
                        average="macro",
                        zero_division=0,
                    )
                ),
                "balanced_accuracy": _balanced_accuracy_or_none(
                    encoded[test], prediction, len(classes)
                ),
                "confusion_matrix": matrix.tolist(),
            }
        )

    final_pipeline = build_baseline_pipeline(random_state=random_state)
    try:
        final_pipeline.fit(clean[text_col], encoded)
    except ValueError as error:
        if "empty vocabulary" in str(error).casefold():
            raise InsufficientBaselineDataError(
                "Labelled responses contain no usable TF-IDF vocabulary"
            ) from error
        raise

    demo_flag, evidence_status = _evidence_label(
        clean, demo_only=demo_only, data_status_col=data_status_col
    )
    macro_values = np.asarray([fold["macro_f1"] for fold in fold_results], dtype=float)
    balanced_values = np.asarray(
        [
            fold["balanced_accuracy"]
            for fold in fold_results
            if fold["balanced_accuracy"] is not None
        ],
        dtype=float,
    )
    result: dict[str, Any] = {
        "evidence_status": evidence_status,
        "demo_only": demo_flag,
        "target_column": label_col,
        "text_column": text_col,
        "conversation_column": conversation_col,
        "cv_strategy": strategy,
        "n_rows": len(clean),
        "excluded_unlabelled_rows": excluded_rows,
        "n_conversations": int(clean[conversation_col].nunique()),
        "classes": [_python_scalar(value) for value in classes],
        "class_balance": _class_balance(encoded, classes),
        "folds": fold_results,
        "macro_f1_mean": float(macro_values.mean()),
        "macro_f1_std": float(macro_values.std(ddof=0)),
        "balanced_accuracy_mean": (float(balanced_values.mean()) if balanced_values.size else None),
        "confusion_matrix": aggregate_confusion.tolist(),
        "coefficient_terms": _coefficient_summary(
            final_pipeline, classes, top_n=top_terms_per_class
        ),
        "limitations": [
            "Turns are correlated within conversations; folds therefore hold out "
            "whole conversations.",
            "This small linear model is an exploratory baseline, not clinical evidence.",
            "Ordinal labels are treated as nominal classes by logistic regression.",
        ],
    }
    if include_fitted_model:
        result["fitted_model"] = final_pipeline
    return result


# Clear alias for notebook callers.
train_and_evaluate_baseline = evaluate_grouped_baseline


__all__ = [
    "DEMO_ONLY_LABEL",
    "EXPLORATORY_LABEL",
    "TECHNICAL_PILOT_LABEL",
    "InsufficientBaselineDataError",
    "assert_no_group_leakage",
    "build_baseline_pipeline",
    "evaluate_grouped_baseline",
    "grouped_cv_splits",
    "train_and_evaluate_baseline",
]
