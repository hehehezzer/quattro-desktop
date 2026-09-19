"""Understandable CPU-only TF-IDF logistic regression for DIRECT/DELEGATE."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .store import FEATURE_SCHEMA_VERSION
from .features import MODEL_INPUT_FIELDS, project_model_input


ALGORITHM = "tfidf-logistic-regression-stdlib-v1"
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{1,63}")
FEATURE_SETS = frozenset({
    "text_only",
    "metadata_only",
    "safe_metadata",
    "safe_metadata_no_length",
    "legacy_full",
})
_SAFE_BOOLEAN_FEATURES = (
    "repository_required",
    "retrieval_required",
    "tool_required",
    "current_information_required",
    "execution_required",
    "modification_required",
    "verification_required",
    "multi_step_required",
)


def _terms(
    text: str,
    profile: Mapping[str, Any] | None = None,
    *,
    feature_set: str = "safe_metadata",
) -> list[str]:
    tokens = [token.lower() for token in _TOKEN.findall(text[:32_000])]
    bigrams = [f"{left}::{right}" for left, right in zip(tokens, tokens[1:])]
    profile = profile or {}
    if feature_set == "text_only":
        return tokens + bigrams
    metadata = []
    keys = (
        ("complexity", "category", "task_category", *_SAFE_BOOLEAN_FEATURES)
        if feature_set in {"safe_metadata", "metadata_only", "safe_metadata_no_length"}
        else ("task_type", "complexity", "scope", "risk", "tier")
    )
    for key in keys:
        value = profile.get(key)
        value = getattr(value, "value", value)
        if value is not None:
            metadata.append(f"__{key}_{str(value).lower()}")
    text_terms = [] if feature_set == "metadata_only" else tokens + bigrams
    return text_terms + metadata


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-min(value, 60.0)))
    exp_value = math.exp(max(value, -60.0))
    return exp_value / (1.0 + exp_value)


def _atomic_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


class DirectDelegateModel:
    """Serializable sparse linear model with a calibrated decision threshold."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if payload.get("algorithm") != ALGORITHM:
            raise ValueError("unsupported DIRECT/DELEGATE model algorithm")
        if payload.get("feature_version") not in {
            FEATURE_SCHEMA_VERSION,
            "direct-delegate-features-v1",
        }:
            raise ValueError("unsupported DIRECT/DELEGATE feature version")
        self.payload = dict(payload)
        self.vocabulary = {str(key): int(value) for key, value in payload["vocabulary"].items()}
        self.idf = [float(value) for value in payload["idf"]]
        self.weights = [float(value) for value in payload["weights"]]
        self.intercept = float(payload["intercept"])
        self.threshold = float(payload.get("threshold", 0.5))
        self.feature_set = str(payload.get("feature_set") or "legacy_full")
        if self.feature_set not in FEATURE_SETS:
            raise ValueError("unsupported DIRECT/DELEGATE feature set")
        calibration = payload.get("calibration") or {}
        self.calibration_slope = float(calibration.get("slope", 1.0))
        self.calibration_intercept = float(calibration.get("intercept", 0.0))
        self.numeric_means = [float(value) for value in payload["numeric_means"]]
        self.numeric_scales = [float(value) for value in payload["numeric_scales"]]
        self.numeric_features = [
            str(value) for value in payload.get("numeric_features", ())
        ]
        expected = len(self.vocabulary) + len(self.numeric_means)
        if len(self.vocabulary) > 100_000 or len(self.numeric_means) > 100:
            raise ValueError("model feature dimensions exceed safety limits")
        if set(self.vocabulary.values()) != set(range(len(self.vocabulary))):
            raise ValueError("model vocabulary indexes are inconsistent")
        if len(self.idf) != len(self.vocabulary) or len(self.weights) != expected:
            raise ValueError("model feature dimensions are inconsistent")
        numeric_values = [
            *self.idf, *self.weights, self.intercept, self.threshold,
            self.calibration_slope, self.calibration_intercept,
            *self.numeric_means, *self.numeric_scales,
        ]
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("model contains non-finite numeric values")
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("model threshold must be between zero and one")
        if any(value <= 0 for value in self.numeric_scales):
            raise ValueError("model numeric scales must be positive")

    @classmethod
    def load(cls, path: pathlib.Path) -> "DirectDelegateModel":
        if path.is_symlink():
            raise ValueError("model artifact must not be a symbolic link")
        if path.stat().st_size > 20_000_000:
            raise ValueError("model artifact exceeds 20 MB")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("model artifact must contain an object")
        return cls(payload)

    def save(self, path: pathlib.Path) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("model artifact must be a regular file")
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != self.payload:
                raise ValueError(f"immutable model artifact differs: {path}")
            os.chmod(path, 0o600)
            return
        _atomic_json(path, self.payload)

    @staticmethod
    def _numeric(
        text: str,
        profile: Mapping[str, Any],
        repository_present: bool,
        *,
        feature_set: str,
    ) -> list[float]:
        if feature_set == "text_only":
            return []
        if feature_set in {"safe_metadata", "metadata_only"}:
            return [
                math.log1p(len(text)),
                math.log1p(max(0, (len(text) + 3) // 4)),
                *(float(bool(profile.get(name))) for name in _SAFE_BOOLEAN_FEATURES),
            ]
        if feature_set == "safe_metadata_no_length":
            return [
                *(float(bool(profile.get(name))) for name in _SAFE_BOOLEAN_FEATURES),
            ]
        required = profile.get("required_capabilities") or profile.get("requiredCapabilities") or ()
        retrieval = bool(
            profile.get("retrieval_required")
            or profile.get("retrievalRequired")
            or any(str(item) in {"repository_read", "research", "long_context"} for item in required)
        )
        context_tokens = int(
            profile.get("final_request_tokens") or profile.get("finalRequestTokens") or 0
        )
        return [
            math.log1p(len(text)),
            math.log1p(max(0, (len(text) + 3) // 4)),
            float(repository_present),
            float(retrieval),
            math.log1p(max(0, context_tokens)),
        ]

    def vectorize(
        self,
        text: str,
        *,
        profile: Mapping[str, Any] | None = None,
        repository_present: bool = False,
    ) -> dict[int, float]:
        model_input = project_model_input({**(profile or {}), "request_text": text})
        counts = Counter(_terms(
            text, model_input, feature_set=self.feature_set
        ))
        total = max(1, sum(counts.values()))
        vector: dict[int, float] = {}
        for term, count in counts.items():
            index = self.vocabulary.get(term)
            if index is not None:
                vector[index] = (count / total) * self.idf[index]
        offset = len(self.vocabulary)
        for index, value in enumerate(self._numeric(
            text,
            model_input,
            repository_present,
            feature_set=self.feature_set,
        )):
            vector[offset + index] = (value - self.numeric_means[index]) / self.numeric_scales[index]
        return vector

    def predict(
        self,
        text: str,
        *,
        profile: Mapping[str, Any] | None = None,
        repository_present: bool = False,
    ) -> dict[str, Any]:
        model_input = project_model_input({**(profile or {}), "request_text": text})
        vector = self.vectorize(
            text, profile=profile, repository_present=repository_present
        )
        score = self.intercept + sum(self.weights[index] * value for index, value in vector.items())
        delegate_probability = _sigmoid(
            self.calibration_slope * score + self.calibration_intercept
        )
        prediction = "DELEGATE" if delegate_probability >= self.threshold else "DIRECT"
        confidence = delegate_probability if prediction == "DELEGATE" else 1.0 - delegate_probability
        abstention_threshold = float(
            (self.payload.get("abstention") or {}).get("confidence_threshold", 0.0)
        )
        active_requirements = [
            name for name in _SAFE_BOOLEAN_FEATURES if bool(model_input.get(name))
        ]
        return {
            "prediction": prediction,
            "confidence": round(confidence, 6),
            "delegateProbability": round(delegate_probability, 6),
            "abstain": bool(abstention_threshold and confidence < abstention_threshold),
            "abstentionReason": (
                "confidence_below_validation_threshold"
                if abstention_threshold and confidence < abstention_threshold else None
            ),
            "featureSummary": {
                "activeRequirements": active_requirements,
                "complexity": str(model_input.get("complexity") or "unknown"),
                "category": str(model_input.get("category") or "unknown"),
                "taskCategory": str(model_input.get("task_category") or "unknown"),
            },
        }

    def _raw_score(self, text: str, profile: Mapping[str, Any]) -> float:
        vector = self.vectorize(
            text,
            profile=profile,
            repository_present=bool(profile.get("repository_present")),
        )
        return self.intercept + sum(
            self.weights[index] * value for index, value in vector.items()
        )


def _fit_vocabulary(
    rows: Sequence[Mapping[str, Any]],
    max_features: int,
    *,
    feature_set: str,
) -> tuple[dict[str, int], list[float]]:
    document_frequency: Counter[str] = Counter()
    for row in rows:
        document_frequency.update(set(_terms(
            str(row["request_text"]), row, feature_set=feature_set
        )))
    ordered = sorted(document_frequency, key=lambda term: (-document_frequency[term], term))
    ordered = ordered[:max_features]
    vocabulary = {term: index for index, term in enumerate(ordered)}
    size = len(rows)
    idf = [math.log((size + 1) / (document_frequency[term] + 1)) + 1.0 for term in ordered]
    return vocabulary, idf


def _numeric_stats(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_set: str,
) -> tuple[list[float], list[float]]:
    values = [
        DirectDelegateModel._numeric(
            str(row["request_text"]),
            row,
            bool(row.get("repository_present")),
            feature_set=feature_set,
        )
        for row in rows
    ]
    if not values or not values[0]:
        return [], []
    means = [sum(column) / len(column) for column in zip(*values)]
    scales = []
    for index, mean in enumerate(means):
        variance = sum((row[index] - mean) ** 2 for row in values) / len(values)
        scales.append(max(math.sqrt(variance), 1e-6))
    return means, scales


def _training_vectors(
    rows: Sequence[Mapping[str, Any]],
    vocabulary: Mapping[str, int],
    idf: Sequence[float],
    means: Sequence[float],
    scales: Sequence[float],
    *,
    feature_set: str,
) -> list[dict[int, float]]:
    payload = {
        "algorithm": ALGORITHM,
        "feature_version": FEATURE_SCHEMA_VERSION,
        "feature_set": feature_set,
        "vocabulary": dict(vocabulary),
        "idf": list(idf),
        "weights": [0.0] * (len(vocabulary) + len(means)),
        "intercept": 0.0,
        "threshold": 0.5,
        "numeric_means": list(means),
        "numeric_scales": list(scales),
        "numeric_features": _numeric_feature_names(feature_set),
    }
    model = DirectDelegateModel(payload)
    return [
        model.vectorize(
            str(row["request_text"]),
            profile=row,
            repository_present=bool(row.get("repository_present")),
        )
        for row in rows
    ]


def train_direct_delegate_model(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_version: str,
    max_features: int = 2_048,
    epochs: int = 500,
    learning_rate: float = 0.35,
    l2: float = 0.001,
    feature_set: str = "safe_metadata",
    calibrate: bool = True,
    source_revision: str = "unknown",
) -> DirectDelegateModel:
    """Fit deterministic batch-gradient logistic regression on the train split."""
    if not 1 <= max_features <= 100_000:
        raise ValueError("max_features must be between 1 and 100000")
    if not 1 <= epochs <= 10_000:
        raise ValueError("epochs must be between 1 and 10000")
    if not 0.0 < learning_rate <= 10.0:
        raise ValueError("learning_rate must be in (0, 10]")
    if not 0.0 <= l2 <= 10.0:
        raise ValueError("l2 must be between 0 and 10")
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"unsupported feature set: {feature_set}")
    raw_train_rows = [
        row for row in rows
        if row.get("split") == "train"
        and row.get("label") in {"DIRECT", "DELEGATE"}
        and bool(row.get("label_independent", True))
    ]
    invalid_sources = sorted({
        str(row.get("label_source") or "")
        for row in raw_train_rows
        if row.get("label_source") not in {
            "human_gold", "human_verified", "reviewed_outcome",
            "probe_gold", "silver", "curated_benchmark",
        }
    })
    if invalid_sources:
        raise ValueError(
            f"training labels are not independently sourced: {invalid_sources}"
        )
    source_priority = {"human_gold": 0, "probe_gold": 1, "silver": 2}
    grouped_train: dict[str, list[Mapping[str, Any]]] = {}
    for row in raw_train_rows:
        grouped_train.setdefault(
            str(row.get("group_fingerprint") or row.get("record_id")), []
        ).append(row)
    train_rows = [
        sorted(
            members,
            key=lambda row: (
                source_priority.get(str(row.get("label_source")), 9),
                str(row.get("record_id")),
            ),
        )[0]
        for _group, members in sorted(grouped_train.items())
    ]
    labels = [1 if row.get("label") == "DELEGATE" else 0 for row in train_rows]
    if len(train_rows) < 8 or len(set(labels)) != 2:
        raise ValueError("BLOCKED_BY_DATA: need at least 8 train rows containing both classes")
    vocabulary, idf = _fit_vocabulary(
        train_rows, max_features, feature_set=feature_set
    )
    means, scales = _numeric_stats(train_rows, feature_set=feature_set)
    vectors = _training_vectors(
        train_rows,
        vocabulary,
        idf,
        means,
        scales,
        feature_set=feature_set,
    )
    weights = [0.0] * (len(vocabulary) + len(means))
    intercept = 0.0
    positives = sum(labels)
    negatives = len(labels) - positives
    positive_weight = len(labels) / (2.0 * positives)
    negative_weight = len(labels) / (2.0 * negatives)
    for _epoch in range(epochs):
        gradients: dict[int, float] = {}
        intercept_gradient = 0.0
        for vector, label in zip(vectors, labels):
            probability = _sigmoid(intercept + sum(weights[index] * value for index, value in vector.items()))
            sample_weight = positive_weight if label else negative_weight
            error = (probability - label) * sample_weight
            intercept_gradient += error
            for index, value in vector.items():
                gradients[index] = gradients.get(index, 0.0) + error * value
        scale = 1.0 / len(labels)
        intercept -= learning_rate * intercept_gradient * scale
        for index in range(len(weights)):
            gradient = gradients.get(index, 0.0) * scale + l2 * weights[index]
            weights[index] -= learning_rate * gradient
    payload: dict[str, Any] = {
        "schema_version": 1,
        "feature_version": FEATURE_SCHEMA_VERSION,
        "feature_set": feature_set,
        "algorithm": ALGORITHM,
        "dataset_version": dataset_version,
        "dataset_fingerprint": dataset_version.removeprefix("dd-dataset-"),
        "source_revision": source_revision,
        "model_input_fields": list(MODEL_INPUT_FIELDS),
        "vocabulary": vocabulary,
        "idf": idf,
        "weights": weights,
        "intercept": intercept,
        "threshold": 0.5,
        "calibration": {"method": "none", "slope": 1.0, "intercept": 0.0},
        "numeric_means": means,
        "numeric_scales": scales,
        "numeric_features": _numeric_feature_names(feature_set),
        "training": {
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2": l2,
            "train_rows": len(train_rows),
            "class_balance": {"DIRECT": negatives, "DELEGATE": positives},
            "label_sources": dict(sorted(Counter(
                str(row.get("label_source") or "excluded") for row in train_rows
            ).items())),
            "configuration": {
                "max_features": max_features,
                "epochs": epochs,
                "learning_rate": learning_rate,
                "l2": l2,
                "feature_set": feature_set,
                "calibrate": calibrate,
            },
        },
    }
    validation_rows = [
        row for row in rows
        if row.get("split") == "validation"
        and row.get("label") in {"DIRECT", "DELEGATE"}
        and bool(row.get("label_independent", True))
        and row.get("label_source") in {
            "human_gold", "human_verified", "reviewed_outcome", "probe_gold"
        }
    ]
    validation_by_group: dict[str, Mapping[str, Any]] = {}
    for row in validation_rows:
        validation_by_group.setdefault(
            str(row.get("group_fingerprint") or row.get("record_id")), row
        )
    validation_rows = list(validation_by_group.values())
    provisional = DirectDelegateModel(payload)
    if calibrate and len(validation_rows) >= 8 and len({row["label"] for row in validation_rows}) == 2:
        logits = [provisional._raw_score(str(row["request_text"]), row) for row in validation_rows]
        validation_labels = [1 if row["label"] == "DELEGATE" else 0 for row in validation_rows]
        slope, calibration_intercept = _fit_platt(logits, validation_labels)
        payload["calibration"] = {
            "method": "platt_validation",
            "slope": slope,
            "intercept": calibration_intercept,
            "sample_count": len(validation_rows),
        }
        calibrated = DirectDelegateModel(payload)
        probabilities = [
            float(calibrated.predict(str(row["request_text"]), profile=row)["delegateProbability"])
            for row in validation_rows
        ]
        threshold, cost = _select_threshold(probabilities, validation_labels)
        payload["threshold"] = threshold
        payload["threshold_selection"] = {
            "method": "validation_weighted_false_negative_cost",
            "false_negative_weight": 2.0,
            "validation_cost": cost,
            "sample_count": len(validation_rows),
        }
        confidence_threshold, abstention = _select_abstention_threshold(
            probabilities, validation_labels, threshold
        )
        payload["abstention"] = {
            "method": "validation_error_bounded_confidence",
            "confidence_threshold": confidence_threshold,
            **abstention,
        }
    else:
        payload["abstention"] = {
            "method": "unavailable",
            "confidence_threshold": 0.0,
            "sample_count": len(validation_rows),
        }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    payload["model_version"] = f"dd-logreg-{digest}"
    return DirectDelegateModel(payload)


def _numeric_feature_names(feature_set: str) -> list[str]:
    if feature_set == "text_only":
        return []
    if feature_set in {"safe_metadata", "metadata_only"}:
        return ["log_request_length", "log_estimated_tokens", *_SAFE_BOOLEAN_FEATURES]
    if feature_set == "safe_metadata_no_length":
        return list(_SAFE_BOOLEAN_FEATURES)
    return [
        "log_request_length",
        "log_estimated_tokens",
        "repository_present",
        "retrieval_required",
        "log_context_tokens",
    ]


def _fit_platt(logits: Sequence[float], labels: Sequence[int]) -> tuple[float, float]:
    slope = 1.0
    intercept = 0.0
    for _index in range(400):
        slope_gradient = 0.0
        intercept_gradient = 0.0
        for logit, label in zip(logits, labels):
            probability = _sigmoid(slope * logit + intercept)
            error = probability - label
            slope_gradient += error * logit
            intercept_gradient += error
        scale = 1.0 / len(labels)
        slope -= 0.05 * (slope_gradient * scale + 0.001 * (slope - 1.0))
        intercept -= 0.05 * intercept_gradient * scale
        slope = min(10.0, max(0.05, slope))
        intercept = min(10.0, max(-10.0, intercept))
    return slope, intercept


def _select_threshold(
    probabilities: Sequence[float], labels: Sequence[int]
) -> tuple[float, float]:
    candidates = sorted({
        0.5,
        *(min(0.8, max(0.2, float(value))) for value in probabilities),
    })
    ranked: list[tuple[float, float, float]] = []
    for threshold in candidates:
        false_negative = sum(
            label == 1 and probability < threshold
            for probability, label in zip(probabilities, labels)
        )
        false_positive = sum(
            label == 0 and probability >= threshold
            for probability, label in zip(probabilities, labels)
        )
        cost = (2.0 * false_negative + false_positive) / len(labels)
        ranked.append((cost, abs(threshold - 0.5), threshold))
    cost, _distance, threshold = min(ranked)
    return threshold, cost


def _select_abstention_threshold(
    probabilities: Sequence[float], labels: Sequence[int], threshold: float
) -> tuple[float, dict[str, Any]]:
    """Select an abstention confidence threshold on validation evidence only."""
    candidates = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
    selected = 0.0
    selected_report = {
        "sample_count": len(labels),
        "covered_count": len(labels),
        "coverage": 1.0 if labels else 0.0,
        "covered_error_rate": None,
    }
    for candidate in candidates:
        covered = []
        for probability, label in zip(probabilities, labels):
            prediction = int(probability >= threshold)
            confidence = probability if prediction else 1.0 - probability
            if confidence >= candidate:
                covered.append(prediction == label)
        if len(covered) < max(8, len(labels) // 4):
            continue
        error_rate = 1.0 - (sum(covered) / len(covered))
        if error_rate <= 0.15:
            selected = candidate
            selected_report = {
                "sample_count": len(labels),
                "covered_count": len(covered),
                "coverage": round(len(covered) / len(labels), 6),
                "covered_error_rate": round(error_rate, 6),
            }
            break
    return selected, selected_report
