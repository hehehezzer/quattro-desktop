"""Reproducible binary routing metrics and baseline comparison."""

from __future__ import annotations

import statistics
import time
import math
import random
import hashlib
import datetime as dt
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..delegation import classify_task_request
from .classical import DirectDelegateModel, train_direct_delegate_model
from .dataset import REAL_LABEL_SOURCES, dataset_quality
from .features import decision_profile, feature_audit


PHASE2_MODEL_REQUIREMENTS = {
    "minimumBalancedAccuracyImprovement": 0.03,
    "minimumDisagreements": 30,
    "maximumPairedPValue": 0.05,
    "maximumDelegateFalseNegativeRate": 0.10,
    "maximumExpectedCalibrationError": 0.10,
    "maximumBrierScore": 0.20,
}
_DRIFT_TOKEN = re.compile(r"[a-z][a-z0-9_./-]{1,63}")


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def classification_metrics(labels: Sequence[str], predictions: Sequence[str]) -> dict[str, Any]:
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have equal length")
    true_positive = sum(
        label == "DELEGATE" and prediction == "DELEGATE"
        for label, prediction in zip(labels, predictions)
    )
    true_negative = sum(
        label == "DIRECT" and prediction == "DIRECT"
        for label, prediction in zip(labels, predictions)
    )
    false_positive = sum(
        label == "DIRECT" and prediction == "DELEGATE"
        for label, prediction in zip(labels, predictions)
    )
    false_negative = sum(
        label == "DELEGATE" and prediction == "DIRECT"
        for label, prediction in zip(labels, predictions)
    )
    sample_count = len(labels)
    accuracy = (true_positive + true_negative) / sample_count if sample_count else 0.0
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    specificity = true_negative / (true_negative + false_positive) if true_negative + false_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    delegate_count = true_positive + false_negative
    direct_count = true_negative + false_positive
    per_class = {
        "DIRECT": {
            "precision": round(
                true_negative / (true_negative + false_negative)
                if true_negative + false_negative else 0.0,
                6,
            ),
            "recall": round(true_negative / direct_count if direct_count else 0.0, 6),
            "f1": 0.0,
            "falseNegativeRate": round(
                false_positive / direct_count if direct_count else 0.0, 6
            ),
            "falsePositiveRate": round(
                false_negative / delegate_count if delegate_count else 0.0, 6
            ),
        },
        "DELEGATE": {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "falseNegativeRate": round(
                false_negative / delegate_count if delegate_count else 0.0, 6
            ),
            "falsePositiveRate": round(
                false_positive / direct_count if direct_count else 0.0, 6
            ),
        },
    }
    direct_precision = per_class["DIRECT"]["precision"]
    direct_recall = per_class["DIRECT"]["recall"]
    per_class["DIRECT"]["f1"] = round(
        2 * direct_precision * direct_recall / (direct_precision + direct_recall)
        if direct_precision + direct_recall else 0.0,
        6,
    )
    return {
        "sampleCount": sample_count,
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "specificity": round(specificity, 6),
        "balancedAccuracy": round((recall + specificity) / 2, 6),
        "f1": round(f1, 6),
        "confidenceIntervals95": {
            "accuracy": _wilson_interval(true_positive + true_negative, sample_count),
            "precision": _wilson_interval(true_positive, true_positive + false_positive),
            "recall": _wilson_interval(true_positive, true_positive + false_negative),
            "specificity": _wilson_interval(true_negative, true_negative + false_positive),
        },
        "confusionMatrix": {
            "labels": ["DIRECT", "DELEGATE"],
            "matrix": [[true_negative, false_positive], [false_negative, true_positive]],
        },
        "falsePositives": false_positive,
        "falseNegatives": false_negative,
        "delegateFalseNegativeRate": round(
            false_negative / delegate_count if delegate_count else 0.0, 6
        ),
        "perClass": per_class,
    }


def _calibration(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not examples:
        return {
            "sampleCount": 0,
            "brierScore": None,
            "expectedCalibrationError": None,
            "bins": [],
        }
    bins: list[dict[str, Any]] = []
    weighted_gap = 0.0
    calibration_ranges = tuple(
        (index / 10.0, (index + 1) / 10.0)
        for index in range(10)
    )
    for lower, upper in calibration_ranges:
        members = [
            row for row in examples
            if lower <= float(row["delegateProbability"]) < upper
            or (upper == 1.0 and float(row["delegateProbability"]) == 1.0)
        ]
        if not members:
            continue
        mean_probability = statistics.fmean(
            float(row["delegateProbability"]) for row in members
        )
        observed_delegate_rate = sum(
            row["label"] == "DELEGATE" for row in members
        ) / len(members)
        weighted_gap += abs(mean_probability - observed_delegate_rate) * len(members)
        bins.append({
            "range": f"{lower:.1f}-{upper:.1f}",
            "count": len(members),
            "meanDelegateProbability": round(mean_probability, 6),
            "observedDelegateRate": round(observed_delegate_rate, 6),
        })
    brier = statistics.fmean(
        (float(row["delegateProbability"]) - (1.0 if row["label"] == "DELEGATE" else 0.0)) ** 2
        for row in examples
    )
    intervals = {"brierScore": None, "expectedCalibrationError": None}
    if len(examples) >= 2:
        generator = random.Random(0)
        brier_samples: list[float] = []
        ece_samples: list[float] = []
        for _index in range(500):
            sample = [examples[generator.randrange(len(examples))] for _ in examples]
            sample_brier = statistics.fmean(
                (float(row["delegateProbability"]) - (1.0 if row["label"] == "DELEGATE" else 0.0)) ** 2
                for row in sample
            )
            sample_bins = []
            for lower, upper in calibration_ranges:
                members = [
                    row for row in sample
                    if lower <= float(row["delegateProbability"]) < upper
                    or (upper == 1.0 and float(row["delegateProbability"]) == 1.0)
                ]
                if members:
                    mean_probability = statistics.fmean(
                        float(row["delegateProbability"]) for row in members
                    )
                    observed_delegate_rate = sum(
                        row["label"] == "DELEGATE" for row in members
                    ) / len(members)
                    sample_bins.append(
                        abs(mean_probability - observed_delegate_rate) * len(members)
                    )
            brier_samples.append(sample_brier)
            ece_samples.append(sum(sample_bins) / len(sample))
        brier_samples.sort()
        ece_samples.sort()
        lower = int(len(brier_samples) * 0.025)
        upper = min(len(brier_samples) - 1, int(len(brier_samples) * 0.975))
        intervals = {
            "brierScore": [round(brier_samples[lower], 6), round(brier_samples[upper], 6)],
            "expectedCalibrationError": [
                round(ece_samples[lower], 6), round(ece_samples[upper], 6)
            ],
        }
    return {
        "sampleCount": len(examples),
        "brierScore": round(brier, 6),
        "expectedCalibrationError": round(weighted_gap / len(examples), 6),
        "confidenceIntervals95": intervals,
        "bins": bins,
    }


def _confidence_distribution(
    examples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ranges = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.000001))
    return {
        "sampleCount": len(examples),
        "mean": round(statistics.fmean(
            float(row["confidence"]) for row in examples
        ), 6) if examples else None,
        "bins": [
            {
                "range": f"{lower:.1f}-{min(upper, 1.0):.1f}",
                "count": sum(
                    lower <= float(row["confidence"]) < upper for row in examples
                ),
            }
            for lower, upper in ranges
        ],
    }


def _abstention_report(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    abstained = [row for row in examples if bool(row.get("abstain"))]
    covered = [row for row in examples if not bool(row.get("abstain"))]
    return {
        "sampleCount": len(examples),
        "abstainedCount": len(abstained),
        "abstentionRate": round(len(abstained) / len(examples), 6) if examples else 0.0,
        "coveredCount": len(covered),
        "coverage": round(len(covered) / len(examples), 6) if examples else 0.0,
        "coveredMetrics": classification_metrics(
            [str(row["label"]) for row in covered],
            [str(row["prediction"]) for row in covered],
        ),
    }


def _disagreement_review(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row in examples:
        if row["baseline"] == row["prediction"]:
            continue
        if row["prediction"] == row["label"]:
            category = "likely_deterministic_rule_weakness"
        elif row["baseline"] == row["label"]:
            category = "likely_shadow_error"
        else:
            category = "ambiguous"
        items.append({
            "recordId": row["recordId"],
            "requestExcerpt": row["requestExcerpt"],
            "label": row["label"],
            "labelSource": row.get("labelSource"),
            "baseline": row["baseline"],
            "shadow": row["prediction"],
            "delegateProbability": row["delegateProbability"],
            "confidence": row["confidence"],
            "classification": category,
            "taskCategory": row.get("taskCategory"),
        })
    return {
        "count": len(items),
        "classificationBalance": dict(sorted(Counter(
            str(item["classification"]) for item in items
        ).items())),
        "representative": items[:50],
    }


def _performance_over_time(
    examples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    invalid = 0
    for row in examples:
        timestamp = str(row.get("createdAt") or "")
        try:
            parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            invalid += 1
            continue
        if parsed.tzinfo is None:
            invalid += 1
            continue
        buckets.setdefault(parsed.astimezone(dt.timezone.utc).strftime("%Y-%m"), []).append(row)
    return {
        "invalidTimestampCount": invalid,
        "buckets": {
            key: _subset_report(values) for key, values in sorted(buckets.items())
        },
    }


def _error_examples(examples: Sequence[Mapping[str, Any]], kind: str) -> list[dict[str, Any]]:
    if kind == "falsePositive":
        selected = [
            row for row in examples
            if row["label"] == "DIRECT" and row["prediction"] == "DELEGATE"
        ]
    else:
        selected = [
            row for row in examples
            if row["label"] == "DELEGATE" and row["prediction"] == "DIRECT"
        ]
    return [
        {
            "recordId": row["recordId"],
            "requestExcerpt": row["requestExcerpt"],
            "category": row["category"],
            "complexity": row["complexity"],
            "confidence": row["confidence"],
            "delegateProbability": row["delegateProbability"],
        }
        for row in sorted(selected, key=lambda item: -float(item["confidence"]))[:10]
    ]


def _subset_report(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    labels = [str(row["label"]) for row in examples]
    baseline = [str(row["baseline"]) for row in examples]
    model = [str(row["prediction"]) for row in examples]
    disagreements = sum(left != right for left, right in zip(baseline, model))
    return {
        "sampleCount": len(examples),
        "meaningfulSample": len(examples) >= 5,
        "classBalance": dict(sorted(Counter(labels).items())),
        "baselineMetrics": classification_metrics(labels, baseline),
        "modelMetrics": classification_metrics(labels, model),
        "disagreementRate": round(disagreements / len(examples), 6) if examples else 0.0,
        "disagreementRateInterval95": _wilson_interval(disagreements, len(examples)),
        "calibration": _calibration(examples),
        "confidenceDistribution": _confidence_distribution(examples),
        "abstention": _abstention_report(examples),
        "pairedComparison": _paired_comparison(examples),
        "falsePositiveExamples": _error_examples(examples, "falsePositive"),
        "falseNegativeExamples": _error_examples(examples, "falseNegative"),
    }


def _paired_comparison(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    model_wins = sum(
        row["prediction"] == row["label"] and row["baseline"] != row["label"]
        for row in examples
    )
    baseline_wins = sum(
        row["baseline"] == row["label"] and row["prediction"] != row["label"]
        for row in examples
    )
    disagreements = model_wins + baseline_wins
    if disagreements:
        tail = sum(
            math.comb(disagreements, index)
            for index in range(0, min(model_wins, baseline_wins) + 1)
        ) / (2 ** disagreements)
        p_value = min(1.0, 2.0 * tail)
    else:
        p_value = 1.0
    return {
        "disagreements": disagreements,
        "modelWins": model_wins,
        "baselineWins": baseline_wins,
        "exactMcNemarPValue": round(p_value, 6),
    }


def _paired_bootstrap_difference(
    examples: Sequence[Mapping[str, Any]],
    *,
    iterations: int = 2_000,
) -> dict[str, Any]:
    """Deterministic paired interval for balanced-accuracy improvement."""
    if not examples:
        return {"iterations": 0, "meanDifference": None, "interval95": None}
    generator = random.Random(0x110)
    differences: list[float] = []
    for _index in range(iterations):
        sample = [examples[generator.randrange(len(examples))] for _ in examples]
        labels = [str(row["label"]) for row in sample]
        baseline = [str(row["baseline"]) for row in sample]
        model = [str(row["prediction"]) for row in sample]
        differences.append(
            float(classification_metrics(labels, model)["balancedAccuracy"])
            - float(classification_metrics(labels, baseline)["balancedAccuracy"])
        )
    differences.sort()
    lower = differences[int(iterations * 0.025)]
    upper = differences[min(iterations - 1, int(iterations * 0.975))]
    return {
        "iterations": iterations,
        "meanDifference": round(statistics.fmean(differences), 6),
        "interval95": [round(lower, 6), round(upper, 6)],
    }


def _phase2_assessment(
    quality: Mapping[str, Any],
    real_report: Mapping[str, Any],
    paired: Mapping[str, Any],
    *,
    benchmark_reproducible: bool,
) -> dict[str, Any]:
    reasons = list(quality.get("reasons") or ())
    requirements = PHASE2_MODEL_REQUIREMENTS
    if not benchmark_reproducible:
        reasons.append("fixed benchmark predictions and metrics are not reproducible")
    baseline = real_report["baselineMetrics"]
    model = real_report["modelMetrics"]
    improvement = float(model["balancedAccuracy"]) - float(baseline["balancedAccuracy"])
    if improvement < requirements["minimumBalancedAccuracyImprovement"]:
        reasons.append(
            "model balanced-accuracy improvement on independent real test groups "
            f"is {improvement:.6f}; need at least "
            f"{requirements['minimumBalancedAccuracyImprovement']:.2f}"
        )
    if float(model["f1"]) < float(baseline["f1"]):
        reasons.append("model F1 is below the deterministic router on independent real test groups")
    delegate_count = int(model["confusionMatrix"]["matrix"][1][0]) + int(
        model["confusionMatrix"]["matrix"][1][1]
    )
    baseline_delegate_count = int(baseline["confusionMatrix"]["matrix"][1][0]) + int(
        baseline["confusionMatrix"]["matrix"][1][1]
    )
    model_false_negative_rate = (
        int(model["falseNegatives"]) / delegate_count if delegate_count else 0.0
    )
    baseline_false_negative_rate = (
        int(baseline["falseNegatives"]) / baseline_delegate_count
        if baseline_delegate_count else 0.0
    )
    if model_false_negative_rate > requirements["maximumDelegateFalseNegativeRate"]:
        reasons.append(
            f"model DELEGATE false-negative rate is {model_false_negative_rate:.6f}; "
            f"maximum is {requirements['maximumDelegateFalseNegativeRate']:.2f}"
        )
    if model_false_negative_rate > baseline_false_negative_rate:
        reasons.append("model DELEGATE false-negative rate is worse than the deterministic router")
    calibration = real_report["calibration"]
    ece = calibration.get("expectedCalibrationError")
    brier = calibration.get("brierScore")
    if ece is None or float(ece) > requirements["maximumExpectedCalibrationError"]:
        reasons.append(
            f"expected calibration error must be at most "
            f"{requirements['maximumExpectedCalibrationError']:.2f}"
        )
    if brier is None or float(brier) > requirements["maximumBrierScore"]:
        reasons.append(f"Brier score must be at most {requirements['maximumBrierScore']:.2f}")
    if int(paired["disagreements"]) < requirements["minimumDisagreements"]:
        reasons.append(
            f"need at least {requirements['minimumDisagreements']} independent real "
            f"baseline/model disagreements; found {paired['disagreements']}"
        )
    if (
        int(paired["modelWins"]) <= int(paired["baselineWins"])
        or float(paired["exactMcNemarPValue"]) > requirements["maximumPairedPValue"]
    ):
        reasons.append(
            "paired held-out comparison does not show a statistically credible model win "
            "over the deterministic router"
        )
    return {
        "status": "READY" if not reasons else "BLOCKED_BY_DATA",
        "requirements": dict(requirements),
        "reasons": reasons,
        "balancedAccuracyImprovement": round(improvement, 6),
        "modelDelegateFalseNegativeRate": round(model_false_negative_rate, 6),
        "baselineDelegateFalseNegativeRate": round(baseline_false_negative_rate, 6),
        "pairedComparison": dict(paired),
    }


def _breakdown(examples: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values = sorted({str(row.get(field) or "unknown") for row in examples})
    return {
        value: _subset_report([
            row for row in examples if str(row.get(field) or "unknown") == value
        ])
        for value in values
    }


def _chronological_drift(
    older: Sequence[Mapping[str, Any]], newer: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    older_vocabulary = {
        token
        for row in older
        for token in _DRIFT_TOKEN.findall(str(row.get("request_text") or "").lower())
    }
    newer_vocabulary = {
        token
        for row in newer
        for token in _DRIFT_TOKEN.findall(str(row.get("request_text") or "").lower())
    }
    unseen = newer_vocabulary - older_vocabulary

    def distribution(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, float]:
        counts = Counter(str(row.get(field) or "unknown") for row in rows)
        return {
            key: round(value / len(rows), 6) if rows else 0.0
            for key, value in sorted(counts.items())
        }

    def requirement_rates(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        fields = (
            "repository_required", "retrieval_required", "tool_required",
            "current_information_required", "execution_required",
            "modification_required", "verification_required", "multi_step_required",
        )
        return {
            field: round(
                sum(bool(row.get(field)) for row in rows) / len(rows), 6
            ) if rows else 0.0
            for field in fields
        }

    return {
        "vocabulary": {
            "olderUniqueTerms": len(older_vocabulary),
            "newerUniqueTerms": len(newer_vocabulary),
            "newerUnseenTerms": len(unseen),
            "newerUnseenRate": round(
                len(unseen) / len(newer_vocabulary), 6
            ) if newer_vocabulary else 0.0,
        },
        "category": {
            "older": distribution(older, "category"),
            "newer": distribution(newer, "category"),
        },
        "taskCategory": {
            "older": distribution(older, "task_category"),
            "newer": distribution(newer, "task_category"),
        },
        "requirements": {
            "older": requirement_rates(older),
            "newer": requirement_rates(newer),
        },
        "routePolicyVersion": "not_measurable_from_legacy_records",
    }


def chronological_evaluation(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Train on older independent real groups and evaluate on a newer cohort."""
    grouped: dict[str, list[tuple[dt.datetime, Mapping[str, Any]]]] = {}
    invalid_timestamp_count = 0
    for row in rows:
        if row.get("label") not in {"DIRECT", "DELEGATE"}:
            continue
        if row.get("label_source") not in REAL_LABEL_SOURCES:
            continue
        if not bool(row.get("label_independent", False)):
            continue
        raw_timestamp = str(row.get("created_at") or "")
        if not raw_timestamp:
            invalid_timestamp_count += 1
            continue
        try:
            timestamp = dt.datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            invalid_timestamp_count += 1
            continue
        if timestamp.tzinfo is None:
            invalid_timestamp_count += 1
            continue
        timestamp = timestamp.astimezone(dt.timezone.utc)
        grouped.setdefault(
            str(row.get("group_fingerprint") or row["record_id"]), []
        ).append((timestamp, row))
    representatives: list[tuple[dt.datetime, Mapping[str, Any]]] = []
    conflicting_groups = 0
    for members in grouped.values():
        labels = {str(member[1]["label"]) for member in members}
        if len(labels) != 1:
            conflicting_groups += 1
            continue
        representatives.append(min(
            members,
            key=lambda member: (member[0], str(member[1]["record_id"])),
        ))
    representatives.sort(
        key=lambda member: (member[0], str(member[1]["record_id"]))
    )
    if len(representatives) < 20:
        return {
            "status": "BLOCKED_BY_DATA",
            "reason": "need at least 20 timestamped independent reviewed real groups",
            "independentGroupCount": len(representatives),
            "conflictingGroupCount": conflicting_groups,
            "invalidTimestampCount": invalid_timestamp_count,
        }
    cutoff = max(8, int(len(representatives) * 0.70))
    if len(representatives) - cutoff < 5:
        cutoff = len(representatives) - 5
    older = [member[1] for member in representatives[:cutoff]]
    newer = [member[1] for member in representatives[cutoff:]]
    train_balance = Counter(str(row["label"]) for row in older)
    evaluation_balance = Counter(str(row["label"]) for row in newer)
    if len(train_balance) < 2 or len(evaluation_balance) < 2:
        return {
            "status": "BLOCKED_BY_DATA",
            "reason": "chronological train and evaluation cohorts must contain both classes",
            "independentGroupCount": len(representatives),
            "trainingClassBalance": dict(sorted(train_balance.items())),
            "evaluationClassBalance": dict(sorted(evaluation_balance.items())),
            "cutoffTimestamp": newer[0].get("created_at") if newer else None,
            "conflictingGroupCount": conflicting_groups,
            "invalidTimestampCount": invalid_timestamp_count,
        }
    cohort_identity = hashlib.sha256(
        "|".join(
            str(member[1].get("group_fingerprint") or member[1]["record_id"])
            for member in representatives
        )
        .encode("utf-8")
    ).hexdigest()[:16]
    training_rows = [{**row, "split": "train"} for row in older]
    evaluation_rows = [{**row, "split": "test"} for row in newer]
    model = train_direct_delegate_model(
        training_rows,
        dataset_version=f"chronological-{cohort_identity}",
    )
    examples, _latencies = _evaluate_rows(model, evaluation_rows)
    report = _subset_report(examples)
    return {
        "status": "evaluated",
        "modelVersion": model.payload["model_version"],
        "independentGroupCount": len(representatives),
        "trainingGroupCount": len(older),
        "evaluationGroupCount": len(newer),
        "trainingClassBalance": dict(sorted(train_balance.items())),
        "evaluationClassBalance": dict(sorted(evaluation_balance.items())),
        "cutoffTimestamp": newer[0].get("created_at"),
        "conflictingGroupCount": conflicting_groups,
        "invalidTimestampCount": invalid_timestamp_count,
        "meaningfulSample": (
            len(newer) >= 60
            and all(evaluation_balance[label] >= 30 for label in ("DIRECT", "DELEGATE"))
        ),
        "baselineMetrics": report["baselineMetrics"],
        "modelMetrics": report["modelMetrics"],
        "disagreementRate": report["disagreementRate"],
        "calibration": report["calibration"],
        "falsePositiveExamples": report["falsePositiveExamples"],
        "falseNegativeExamples": report["falseNegativeExamples"],
        "drift": _chronological_drift(older, newer),
    }


def _evaluate_rows(
    model: DirectDelegateModel,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[float]]:
    examples: list[dict[str, Any]] = []
    latencies: list[float] = []
    for row in rows:
        baseline = classify_task_request(str(row["request_text"])).decision
        started = time.perf_counter()
        result = model.predict(
            str(row["request_text"]),
            profile=row,
            repository_present=bool(row.get("repository_present")),
        )
        latencies.append((time.perf_counter() - started) * 1_000)
        prediction = str(result["prediction"])
        rubric_profile = decision_profile(str(row["request_text"]))
        rubric_prediction = (
            "DELEGATE"
            if any(bool(rubric_profile[name]) for name in (
                "repository_required",
                "retrieval_required",
                "execution_required",
                "modification_required",
                "verification_required",
                "multi_step_required",
            ))
            else "DIRECT"
        )
        examples.append({
            "recordId": row["record_id"],
            "requestExcerpt": str(row["request_text"])[:240],
            "label": row["label"],
            "labelSource": row.get("label_source"),
            "groupFingerprint": row.get("group_fingerprint"),
            "baseline": baseline,
            "rubricBaseline": rubric_prediction,
            "prediction": prediction,
            "confidence": float(result["confidence"]),
            "delegateProbability": float(result["delegateProbability"]),
            "abstain": bool(result.get("abstain")),
            "abstentionReason": result.get("abstentionReason"),
            "correct": prediction == row["label"],
            "createdAt": row.get("created_at"),
            "category": row.get("category") or "unknown",
            "complexity": row.get("complexity") or "unknown",
            "labelClass": row.get("label") or "unknown",
            "codingScope": (
                "coding" if str(row.get("category") or "unknown") == "coding"
                else "non_coding"
            ),
            "retrievalRequirement": (
                "required" if bool(row.get("retrieval_required")) else "not_required"
            ),
            "toolRequirement": (
                "unknown" if row.get("tool_required") is None
                else "required" if bool(row.get("tool_required")) else "not_required"
            ),
            "repositoryRequirement": (
                "required" if bool(row.get("repository_required")) else "not_required"
            ),
            "currentInformationRequirement": (
                "required" if bool(row.get("current_information_required"))
                else "not_required"
            ),
            "executionRequirement": (
                "required" if bool(row.get("execution_required")) else "not_required"
            ),
            "modificationRequirement": (
                "required" if bool(row.get("modification_required")) else "not_required"
            ),
            "verificationRequirement": (
                "required" if bool(row.get("verification_required")) else "not_required"
            ),
            "multiStepRequirement": (
                "required" if bool(row.get("multi_step_required")) else "not_required"
            ),
            "taskCategory": row.get("task_category") or "unknown",
        })
    return examples, latencies


def _independent_source_examples(
    examples: Sequence[Mapping[str, Any]], source: str
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in examples:
        group = str(row.get("groupFingerprint") or row["recordId"])
        if row.get("labelSource") != source or group in seen:
            continue
        seen.add(group)
        selected.append(dict(row))
    return selected


def _majority_report(
    examples: Sequence[Mapping[str, Any]],
    *,
    reference_labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    labels = [str(row["label"]) for row in examples]
    fitting_labels = list(reference_labels) if reference_labels is not None else labels
    majority = Counter(fitting_labels).most_common(1)[0][0] if fitting_labels else "DIRECT"
    delegate_prior = (
        sum(label == "DELEGATE" for label in fitting_labels) / len(fitting_labels)
        if fitting_labels else 0.0
    )
    prior_examples = [
        {**row, "delegateProbability": delegate_prior} for row in examples
    ]
    return {
        "majorityClass": majority,
        "fitSampleCount": len(fitting_labels),
        "fitPartition": "train" if reference_labels is not None else "evaluation_fallback",
        "metrics": classification_metrics(labels, [majority] * len(labels)),
        "classPrior": {
            "delegateProbability": round(delegate_prior, 6),
            "calibration": _calibration(prior_examples),
        },
    }


def _rubric_baseline(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    predictions = [str(row["rubricBaseline"]) for row in examples]
    return {
        "name": "semantic_routing_rubric_v1",
        "metrics": classification_metrics(
            [str(row["label"]) for row in examples],
            predictions,
        ),
    }


def _source_report(
    examples: Sequence[Mapping[str, Any]],
    *,
    reference_labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    report = _subset_report(examples)
    paired = _paired_comparison(examples)
    return {
        **report,
        "majorityBaseline": _majority_report(
            examples,
            reference_labels=reference_labels,
        ),
        "pairedComparison": paired,
        "performanceByCategory": _breakdown(examples, "category"),
        "performanceByTaskCategory": _breakdown(examples, "taskCategory"),
        "performanceByComplexity": _breakdown(examples, "complexity"),
        "performanceByRepositoryRequirement": _breakdown(
            examples, "repositoryRequirement"
        ),
        "performanceByRetrievalRequirement": _breakdown(
            examples, "retrievalRequirement"
        ),
        "performanceByToolRequirement": _breakdown(examples, "toolRequirement"),
        "performanceByCurrentInformationRequirement": _breakdown(
            examples, "currentInformationRequirement"
        ),
        "performanceByExecutionRequirement": _breakdown(
            examples, "executionRequirement"
        ),
        "performanceByModificationRequirement": _breakdown(
            examples, "modificationRequirement"
        ),
        "performanceByVerificationRequirement": _breakdown(
            examples, "verificationRequirement"
        ),
        "performanceByMultiStepRequirement": _breakdown(
            examples, "multiStepRequirement"
        ),
    }


def _installed_shadow_comparison(
    candidate: DirectDelegateModel,
    installed: DirectDelegateModel | None,
    test_rows: Sequence[Mapping[str, Any]],
    installed_training_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if installed is None:
        return {"status": "unavailable"}
    seen_requests = {
        str(row.get("request_fingerprint") or "")
        for row in installed_training_rows
        if row.get("label") in {"DIRECT", "DELEGATE"}
    }
    disjoint = [
        row for row in test_rows
        if str(row.get("request_fingerprint") or "") not in seen_requests
    ]
    if not disjoint:
        return {
            "status": "BLOCKED_BY_DATA",
            "reason": "no test rows are disjoint from installed-model evidence",
            "installedModelVersion": installed.payload.get("model_version"),
        }
    candidate_examples, _candidate_latencies = _evaluate_rows(candidate, disjoint)
    installed_examples, _installed_latencies = _evaluate_rows(installed, disjoint)
    candidate_report = _subset_report(candidate_examples)
    installed_report = _subset_report(installed_examples)
    return {
        "status": "evaluated",
        "installedModelVersion": installed.payload.get("model_version"),
        "candidateModelVersion": candidate.payload.get("model_version"),
        "disjointTestGroupCount": len({
            str(row.get("group_fingerprint") or row.get("record_id")) for row in disjoint
        }),
        "candidate": candidate_report,
        "installed": installed_report,
    }


def _feature_ablation(
    rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    configurations: dict[str, tuple[str, dict[str, Any]]] = {
        "full_safe_model": ("safe_metadata", {}),
        "without_request_text": ("metadata_only", {}),
        "without_request_length": ("safe_metadata_no_length", {}),
        "without_repository_requirement": ("safe_metadata", {"repository_required": False}),
        "without_retrieval_requirement": ("safe_metadata", {"retrieval_required": False}),
        "without_tool_requirement": ("safe_metadata", {"tool_required": False}),
        "without_current_information_requirement": (
            "safe_metadata", {"current_information_required": False}
        ),
        "without_execution_requirement": ("safe_metadata", {"execution_required": False}),
        "without_modification_requirement": (
            "safe_metadata", {"modification_required": False}
        ),
        "without_verification_requirement": (
            "safe_metadata", {"verification_required": False}
        ),
        "without_multi_step_requirement": ("safe_metadata", {"multi_step_required": False}),
        "without_complexity": ("safe_metadata", {"complexity": "low"}),
        "without_category": ("safe_metadata", {"category": "general"}),
        "without_task_category": ("safe_metadata", {"task_category": "general"}),
    }
    for name, (feature_set, overrides) in configurations.items():
        ablation_rows = [{**row, **overrides} for row in rows]
        ablation_validation = [{**row, **overrides} for row in validation_rows]
        try:
            candidate = train_direct_delegate_model(
                ablation_rows,
                dataset_version=f"ablation-{name}",
                feature_set=feature_set,
            )
        except ValueError as error:
            result[name] = {"status": "BLOCKED_BY_DATA", "reason": str(error)}
            continue
        examples, _latencies = _evaluate_rows(candidate, ablation_validation)
        report = _subset_report(examples)
        result[name] = {
            "status": "evaluated",
            "featureSet": feature_set,
            "removedFeatureGroup": (
                None if name == "full_safe_model" else name.removeprefix("without_")
            ),
            "metrics": report["modelMetrics"],
            "disagreementRate": report["disagreementRate"],
            "calibration": report["calibration"],
        }
    safe = result.get("full_safe_model", {})
    safe_accuracy = float(
        safe.get("metrics", {}).get("balancedAccuracy", 0.0)
    )
    impacts = {
        name: round(
            safe_accuracy - float(report.get("metrics", {}).get("balancedAccuracy", 0.0)),
            6,
        )
        for name, report in result.items()
        if name != "full_safe_model" and report.get("status") == "evaluated"
    }
    result["diagnosis"] = {
        "safeExactlyMatchesRouter": (
            safe.get("status") == "evaluated"
            and float(safe.get("disagreementRate", 1.0)) == 0.0
        ),
        "balancedAccuracyImpactByRemovedGroup": impacts,
        "suspiciousDominantFeatureGroups": sorted(
            name.removeprefix("without_")
            for name, impact in impacts.items()
            if impact >= 0.20
        ),
        "postDecisionFeaturesUsedByDefaultModel": False,
        "selectionPartition": "validation_only",
        "legacyRouteConditionedAblationDisabled": True,
    }
    return result


def benchmark_direct_delegate(
    model: DirectDelegateModel,
    rows: Sequence[Mapping[str, Any]],
    *,
    installed_model: DirectDelegateModel | None = None,
    installed_training_rows: Sequence[Mapping[str, Any]] = (),
    include_ablation: bool = True,
) -> dict[str, Any]:
    validation_rows = [
        row for row in rows
        if row.get("split") == "validation"
        and row.get("label")
        and bool(row.get("label_independent", True))
    ]
    train_labels = [
        str(row["label"])
        for row in rows
        if row.get("split") == "train"
        and row.get("label") in {"DIRECT", "DELEGATE"}
        and bool(row.get("label_independent", True))
    ]
    train_labels_by_source = {
        source: [
            str(row["label"])
            for row in rows
            if row.get("split") == "train"
            and row.get("label_source") == source
            and row.get("label") in {"DIRECT", "DELEGATE"}
            and bool(row.get("label_independent", True))
        ]
        for source in ("human_gold", "probe_gold", "silver")
    }
    test_rows = [
        row for row in rows
        if row.get("split") == "test"
        and row.get("label")
        and bool(row.get("label_independent", True))
    ]
    quality = dataset_quality(rows)
    if not test_rows:
        return {
            "status": "BLOCKED_BY_DATA",
            "reason": "No verified labeled examples were assigned to the test split.",
            "sampleCount": 0,
            "datasetQuality": quality,
            "productionConclusion": "BLOCKED_BY_DATA",
        }
    examples, latencies = _evaluate_rows(model, test_rows)
    replay_examples, _replay_latencies = _evaluate_rows(model, test_rows)
    benchmark_reproducible = examples == replay_examples
    summary = _subset_report(examples)
    real_examples = _independent_source_examples(examples, "human_gold")
    probe_examples = _independent_source_examples(examples, "probe_gold")
    silver_examples = _independent_source_examples(examples, "silver")
    silver_all_rows = [
        row for row in rows
        if row.get("label_source") == "silver"
        and row.get("label") in {"DIRECT", "DELEGATE"}
    ]
    silver_all_evaluated, _silver_latencies = _evaluate_rows(model, silver_all_rows)
    silver_all_examples = _independent_source_examples(silver_all_evaluated, "silver")
    real_report = _subset_report(real_examples)
    paired = _paired_comparison(real_examples)
    phase2 = _phase2_assessment(
        quality,
        real_report,
        paired,
        benchmark_reproducible=benchmark_reproducible,
    )
    validation = None
    if validation_rows:
        validation_examples, _latencies = _evaluate_rows(model, validation_rows)
        validation = _subset_report(validation_examples)
    confident_correct = sorted(
        (row for row in examples if row["correct"]),
        key=lambda item: -float(item["confidence"]),
    )[:5]
    confident_incorrect = sorted(
        (row for row in examples if not row["correct"]),
        key=lambda item: -float(item["confidence"]),
    )[:5]
    return {
        "status": "evaluated",
        "sampleCount": summary["sampleCount"],
        "classBalance": summary["classBalance"],
        "baseline": {
            "name": "current_deterministic_router",
            "metrics": summary["baselineMetrics"],
        },
        "classPriorBaseline": _majority_report(
            examples,
            reference_labels=train_labels,
        ),
        "simpleHeuristicBaseline": _rubric_baseline(examples),
        "model": {
            "name": model.payload["algorithm"],
            "version": model.payload["model_version"],
            "metrics": summary["modelMetrics"],
        },
        "installedShadowComparison": _installed_shadow_comparison(
            model,
            installed_model,
            test_rows,
            installed_training_rows,
        ),
        "inferenceLatencyMs": {
            "mean": round(statistics.fmean(latencies), 6),
            "p50": round(statistics.median(latencies), 6),
            "max": round(max(latencies), 6),
        },
        "benchmarkReproducibility": {
            "passed": benchmark_reproducible,
            "scope": "held_out_predictions_and_metrics_excluding_latency",
        },
        "disagreementRate": summary["disagreementRate"],
        "disagreementReview": _disagreement_review(examples),
        "pairedBootstrapBalancedAccuracyDifference": _paired_bootstrap_difference(
            examples
        ),
        "confidenceCalibration": summary["calibration"],
        "confidenceDistribution": summary["confidenceDistribution"],
        "abstention": summary["abstention"],
        "falsePositiveExamples": summary["falsePositiveExamples"],
        "falseNegativeExamples": summary["falseNegativeExamples"],
        "confidentCorrect": confident_correct,
        "confidentIncorrect": confident_incorrect,
        "performanceByCategory": _breakdown(examples, "category"),
        "performanceByComplexity": _breakdown(examples, "complexity"),
        "performanceByClass": _breakdown(examples, "labelClass"),
        "performanceByEvidenceSource": _breakdown(examples, "labelSource"),
        "performanceOverTime": _performance_over_time(examples),
        "performanceByCoding": _breakdown(examples, "codingScope"),
        "performanceByRetrievalRequirement": _breakdown(
            examples, "retrievalRequirement"
        ),
        "performanceByToolRequirement": _breakdown(examples, "toolRequirement"),
        "humanGoldRealTest": _source_report(
            real_examples,
            reference_labels=train_labels_by_source["human_gold"],
        ),
        "humanGoldPairedBootstrapBalancedAccuracyDifference": (
            _paired_bootstrap_difference(real_examples)
        ),
        "probeGoldTest": _source_report(
            probe_examples,
            reference_labels=train_labels_by_source["probe_gold"],
        ),
        "silverDiagnosticTest": _source_report(
            silver_examples,
            reference_labels=train_labels_by_source["silver"],
        ),
        "silverDiagnosticResults": {
            "scope": "training_support_only_not_production_readiness",
            "warning": "May include training evidence; report separately from gold tests.",
            **_source_report(silver_all_examples),
        },
        "allLabeledDiagnostic": {
            "warning": "Diagnostic only; label provenance is mixed.",
            **summary,
        },
        "realExecutionIndependentGroups": real_report,
        "realPerformanceByCategory": _breakdown(real_examples, "category"),
        "realPerformanceByComplexity": _breakdown(real_examples, "complexity"),
        "realPerformanceByClass": _breakdown(real_examples, "labelClass"),
        "realPerformanceByCoding": _breakdown(real_examples, "codingScope"),
        "realPerformanceByRetrievalRequirement": _breakdown(
            real_examples, "retrievalRequirement"
        ),
        "realPerformanceByToolRequirement": _breakdown(
            real_examples, "toolRequirement"
        ),
        "featureAudit": feature_audit(),
        "featureAblation": (
            _feature_ablation(
                rows,
                [
                    row for row in validation_rows
                    if bool(row.get("label_independent", True))
                ],
            )
            if include_ablation and quality.get("status") == "READY" else {
                "status": "not_run",
                "reason": "candidate training is blocked by dataset readiness gates",
            }
        ),
        "chronologicalGeneralization": (
            chronological_evaluation(rows)
            if quality.get("status") == "READY"
            else {
                "status": "NOT RUN",
                "reason": "candidate data gates did not pass",
            }
        ),
        "phase2Assessment": phase2,
        "validation": validation,
        "datasetQuality": quality,
        "productionConclusion": phase2["status"],
        "productionConclusionReasons": phase2["reasons"],
        "evidenceWarning": (
            "Metrics describe only verified held-out labels in this immutable dataset; "
            "ML remains shadow-only and does not control production routing."
        ),
    }
