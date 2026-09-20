"""Deterministic data-maturity measurements for routing intelligence.

This module is intentionally evidence-only.  It never changes a routing
decision and never treats a successful execution as a ground-truth label.
Observed route/model/provider outcomes are reported in a separate section so
they cannot be mistaken for request-time model features or counterfactual
results.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .features import MODEL_INPUT_FIELDS, project_model_input
from .readiness import DEFAULT_PROMOTION_THRESHOLDS, PromotionThresholds


DECISIONS = frozenset({"DIRECT", "DELEGATE"})
MATURITY_SCHEMA_VERSION = 1
# Historical raw tool requirements can be unknown; inference recomputes them.
NULLABLE_RAW_FEATURES = frozenset({"tool_required"})


def _parse_time(value: Any) -> dt.datetime | None:
    """Parse a timezone-aware timestamp and normalize it to UTC."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None


def _round(value: float | None) -> float | None:
    """Round a maturity metric to the report precision."""
    return None if value is None else round(float(value), 6)


def _balance(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    """Count normalized field values in deterministic key order."""
    return dict(sorted(Counter(str(row.get(field) or "unknown") for row in rows).items()))


def _route_balance(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count rows by their deterministic production route."""
    return dict(sorted(Counter(
        str(row.get("production_decision"))
        for row in rows
        if row.get("production_decision") in DECISIONS
    ).items()))


def _observed_success(row: Mapping[str, Any]) -> bool | None:
    """Return an observed binary outcome when the row records one."""
    value = row.get("outcome_success")
    if not isinstance(value, bool):
        value = row.get("success")
    return value if isinstance(value, bool) else None


def _outcome_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize known outcomes without claiming counterfactual evidence."""
    known = [row for row in rows if _observed_success(row) is not None]
    successes = sum(_observed_success(row) is True for row in known)
    failures = len(known) - successes

    def grouped(field: str) -> dict[str, dict[str, Any]]:
        """Aggregate known outcomes by a selected row field."""
        buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in known:
            value = str(row.get(field) or "unknown")
            if value == "unknown":
                continue
            buckets[value].append(row)
        return {
            key: {
                "examples": len(values),
                "successes": sum(_observed_success(row) is True for row in values),
                "failures": sum(_observed_success(row) is False for row in values),
                "successRate": _round(
                    sum(_observed_success(row) is True for row in values) / len(values)
                ) if values else None,
            }
            for key, values in sorted(buckets.items())
        }

    model_provider: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in known:
        provider = str(row.get("selected_provider") or "").strip()
        model = str(row.get("selected_model") or "").strip()
        if provider and model:
            model_provider[f"{provider}/{model}"].append(row)
    by_candidate = {
        key: {
            "providerModel": key,
            "examples": len(values),
            "successes": sum(_observed_success(row) is True for row in values),
            "failures": sum(_observed_success(row) is False for row in values),
            "successRate": _round(
                sum(_observed_success(row) is True for row in values) / len(values)
            ) if values else None,
        }
        for key, values in sorted(model_provider.items())
    }
    return {
        "knownOutcomeExamples": len(known),
        "unknownOutcomeExamples": len(rows) - len(known),
        "successes": successes,
        "failures": failures,
        "successRate": _round(successes / len(known)) if known else None,
        "byDeterministicRoute": grouped("production_decision"),
        "byProvider": grouped("selected_provider"),
        "byModel": grouped("selected_model"),
        "byCandidateProviderModel": by_candidate,
        "counterfactualComparison": {
            "status": "unavailable",
            "reason": "no trustworthy counterfactual execution outcomes are recorded",
            "fabricated": False,
        },
    }


def _freshness(rows: Sequence[Mapping[str, Any]], *, now: dt.datetime) -> dict[str, Any]:
    """Report age and recency coverage for parseable timestamps."""
    parsed = [_parse_time(row.get("created_at")) for row in rows]
    valid = [value for value in parsed if value is not None]
    ages = [max(0.0, (now - value).total_seconds() / 86_400) for value in valid]
    buckets = {
        "last7Days": sum(age <= 7 for age in ages),
        "last30Days": sum(age <= 30 for age in ages),
        "last90Days": sum(age <= 90 for age in ages),
        "olderThan90Days": sum(age > 90 for age in ages),
    }
    return {
        "timestampedExamples": len(valid),
        "missingOrInvalidTimestamps": len(rows) - len(valid),
        "oldestTimestamp": min(valid).isoformat() if valid else None,
        "newestTimestamp": max(valid).isoformat() if valid else None,
        "medianAgeDays": _round(sorted(ages)[len(ages) // 2]) if ages else None,
        "maxAgeDays": _round(max(ages)) if ages else None,
        "buckets": buckets,
        "asOf": now.isoformat(),
    }


def data_maturity(
    rows: Sequence[Mapping[str, Any]],
    *,
    thresholds: PromotionThresholds | None = None,
    now: dt.datetime | None = None,
    duplicate_stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded, deterministic readiness snapshot for dataset rows."""
    policy = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    as_of = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    raw_rows = list(rows)
    invalid_model_inputs: list[dict[str, str]] = []
    valid_projection_ids: set[str] = set()
    projected_feature_present = Counter()
    raw_feature_present = Counter()
    raw_feature_invalid = Counter()
    boolean_fields = {
        "repository_required", "retrieval_required", "tool_required",
        "current_information_required", "execution_required",
        "modification_required", "verification_required", "multi_step_required",
    }
    categorical_fields = {"complexity", "category", "task_category"}
    for row in raw_rows:
        record_id = str(row.get("record_id") or "unknown")
        for field in MODEL_INPUT_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            raw_feature_present[field] += 1
            if field in boolean_fields and not isinstance(value, bool):
                raw_feature_invalid[field] += 1
            if field in categorical_fields and not isinstance(value, str):
                raw_feature_invalid[field] += 1
        try:
            if not str(row.get("request_text") or "").strip():
                raise ValueError("request_text is missing or empty")
            projected = project_model_input(row)
            for field in MODEL_INPUT_FIELDS:
                if projected.get(field) is not None:
                    projected_feature_present[field] += 1
            valid_projection_ids.add(record_id)
        except (KeyError, TypeError, ValueError) as error:
            invalid_model_inputs.append({"recordId": record_id, "reason": str(error)})

    label_valid = [row for row in raw_rows if row.get("label") in DECISIONS]
    independent = [
        row for row in label_valid
        if bool(row.get("label_independent", True))
        and str(row.get("record_id") or "") in valid_projection_ids
    ]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in independent:
        groups[str(row.get("group_fingerprint") or row.get("record_id"))].append(row)
    representatives = [
        sorted(values, key=lambda row: str(row.get("record_id") or ""))[0]
        for _group, values in sorted(groups.items())
    ]
    label_counts = Counter(row["label"] for row in representatives)
    class_balance = {label: label_counts[label] for label in sorted(DECISIONS)}
    counts = list(class_balance.values())
    imbalance = max(counts) / min(counts) if all(counts) else None
    category_balance = _balance(representatives, "task_category")
    complexity_balance = _balance(representatives, "complexity")
    deterministic_balance = _route_balance(representatives)

    label_denominator = len(raw_rows)
    label_rate = len(label_valid) / label_denominator if label_denominator else 0.0
    required_fields = set(MODEL_INPUT_FIELDS) - NULLABLE_RAW_FEATURES
    feature_denominator = len(raw_rows) * len(required_fields)
    feature_missing = feature_denominator - sum(
        raw_feature_present[field] for field in required_fields
    )
    feature_missing_rate = feature_missing / feature_denominator if feature_denominator else 0.0
    leakage_failures = [
        item for item in invalid_model_inputs
        if any(token in item["reason"].lower() for token in (
            "forbidden", "leakage", "non-reproducible", "post-decision",
        ))
    ]
    leakage_rejections = len(leakage_failures)
    missing_invalid = sum(
        not isinstance(row.get("request_text"), str)
        or not str(row.get("request_text") or "").strip()
        or row.get("label") not in (None, *DECISIONS)
        for row in raw_rows
    ) + len(invalid_model_inputs) - leakage_rejections
    untrusted = sum(
        row.get("label") in DECISIONS and not bool(row.get("label_independent", True))
        for row in raw_rows
    )

    duplicate = dict(duplicate_stats or {})
    group_sizes = [len(values) for values in groups.values()]
    total_grouped = sum(group_sizes)
    largest_group = max(group_sizes) if group_sizes else 0
    duplicate.setdefault("exactDuplicateRows", max(0, len(raw_rows) - len({
        str(row.get("request_fingerprint") or row.get("record_id")) for row in raw_rows
    })))
    duplicate["groupCount"] = len(groups)
    duplicate["largestConnectedGroupExamples"] = largest_group
    duplicate["largestConnectedGroupRate"] = _round(
        largest_group / total_grouped if total_grouped else 0.0
    )
    duplicate["collapsedExamples"] = max(0, len(independent) - len(representatives))

    covered_categories = sum(
        count >= policy.minimum_usable_labels_per_category
        for count in category_balance.values()
    )
    blockers: list[str] = []
    if len(representatives) < policy.minimum_independent_usable_groups:
        blockers.append(
            f"need at least {policy.minimum_independent_usable_groups} eligible independent groups; "
            f"found {len(representatives)}"
        )
    if any(
        class_balance.get(label, 0) < policy.minimum_independent_usable_groups_per_class
        for label in DECISIONS
    ):
        blockers.append("eligible independent class counts are below the configured minimum")
    if covered_categories < policy.minimum_categories:
        blockers.append(
            f"need {policy.minimum_categories} task categories with at least "
            f"{policy.minimum_usable_labels_per_category} groups; found {covered_categories}"
        )
    if label_rate < policy.minimum_label_completeness:
        blockers.append(
            f"label completeness is {label_rate:.6f}; minimum is "
            f"{policy.minimum_label_completeness:.6f}"
        )
    if imbalance is None or imbalance > policy.maximum_class_imbalance_ratio:
        blockers.append("eligible labels exceed the configured class-imbalance limit")
    if feature_missing_rate > policy.maximum_feature_missing_rate:
        blockers.append("decision-time feature coverage is incomplete")
    if leakage_rejections:
        blockers.append(f"{leakage_rejections} examples failed model-input validation")

    freshness = _freshness(raw_rows, now=as_of)
    return {
        "schemaVersion": MATURITY_SCHEMA_VERSION,
        "status": "ready" if not blockers else "insufficient_data",
        "promotionReady": not blockers,
        "totalExamples": len(raw_rows),
        "eligibleExamples": len(independent),
        "eligibleIndependentGroups": len(representatives),
        "eligibleUnlabeledExamples": max(0, len(raw_rows) - len(label_valid)),
        "taskCategoryBalance": category_balance,
        "complexityBalance": complexity_balance,
        "deterministicRouteBalance": _route_balance(raw_rows),
        "eligibleDeterministicRouteBalance": deterministic_balance,
        "classImbalance": {
            "counts": class_balance,
            "ratio": _round(imbalance),
            "minorityRate": _round(min(counts) / sum(counts)) if sum(counts) else None,
        },
        "labelCompleteness": {
            "complete": len(label_valid),
            "missing": max(0, len(raw_rows) - len(label_valid)),
            "rate": _round(label_rate),
        },
        "featureCoverage": {
            "fieldCount": len(MODEL_INPUT_FIELDS),
            "requiredFieldCount": len(required_fields),
            "nullableCoveredValues": {
                field: raw_feature_present[field] for field in sorted(NULLABLE_RAW_FEATURES)
            },
            "coveredValues": dict(sorted(raw_feature_present.items())),
            "projectedCoveredValues": dict(sorted(projected_feature_present.items())),
            "missingValueCount": feature_missing,
            "missingRate": _round(feature_missing_rate),
            "rawInvalidValues": dict(sorted(raw_feature_invalid.items())),
            "rawInvalidValueCount": sum(raw_feature_invalid.values()),
            "modelInputValidationFailures": len(invalid_model_inputs),
            "validationFailures": invalid_model_inputs[:20],
        },
        "rejections": {
            "leakage": leakage_rejections,
            "missingOrInvalidFields": missing_invalid,
            "untrustedLabelProvenance": untrusted,
            "total": leakage_rejections + missing_invalid + untrusted,
        },
        "duplicates": duplicate,
        "outcomes": _outcome_report(raw_rows),
        "freshness": freshness,
        "blockingReasons": blockers,
        "thresholds": policy.as_dict(),
        "candidateGates": {
            "eligibleIndependentGroups": len(representatives) >= policy.minimum_independent_usable_groups,
            "classBalance": all(
                class_balance.get(label, 0) >= policy.minimum_independent_usable_groups_per_class
                for label in DECISIONS
            ),
            "labelCompleteness": label_rate >= policy.minimum_label_completeness,
            "featureCoverage": feature_missing_rate <= policy.maximum_feature_missing_rate,
            "zeroLeakageRejections": leakage_rejections == 0,
            "categoryCoverage": covered_categories >= policy.minimum_categories,
        },
    }
