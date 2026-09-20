"""Shared, configurable evidence and promotion policy for Intelligence.

The intelligence pipeline has two deliberately different questions:

* is the stored evidence mature enough to train/evaluate a selector; and
* did an evaluated selector beat the deterministic router without creating a
  new safety or calibration risk?

This module owns the thresholds for both questions.  Keeping them in one
small, validated value object prevents the dataset builder, evaluator, and
CLI reports from silently drifting apart.  The defaults are intentionally
conservative; callers may provide a bounded JSON mapping for offline
experiments, but production routing never reads this policy to make a
decision.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping


READINESS_POLICY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PromotionThresholds:
    """Validated thresholds used by offline data and promotion reports."""

    # Evidence-volume gates.
    minimum_independent_usable_groups: int = 400
    minimum_independent_usable_groups_per_class: int = 200
    minimum_validation_per_class: int = 30
    minimum_test_per_class: int = 30
    minimum_categories: int = 4
    minimum_usable_labels_per_category: int = 30
    maximum_dominant_category_rate: float = 0.60
    minimum_label_completeness: float = 0.95
    maximum_class_imbalance_ratio: float = 2.0
    maximum_feature_missing_rate: float = 0.0
    maximum_rejected_leakage_rate: float = 0.0

    # Evaluation gates.
    minimum_balanced_accuracy_improvement: float = 0.03
    minimum_disagreements: int = 30
    maximum_paired_p_value: float = 0.05
    maximum_delegate_false_negative_rate: float = 0.10
    maximum_expected_calibration_error: float = 0.10
    maximum_brier_score: float = 0.20
    minimum_category_evaluation_samples: int = 30
    minimum_category_class_samples: int = 10

    def __post_init__(self) -> None:
        """Reject invalid threshold values before policy evaluation."""
        integer_fields = {
            "minimum_independent_usable_groups",
            "minimum_independent_usable_groups_per_class",
            "minimum_validation_per_class",
            "minimum_test_per_class",
            "minimum_categories",
            "minimum_usable_labels_per_category",
            "minimum_disagreements",
            "minimum_category_evaluation_samples",
            "minimum_category_class_samples",
        }
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in integer_fields:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"{item.name} must be a nonnegative integer")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{item.name} must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{item.name} must be finite")
            if item.name == "maximum_class_imbalance_ratio":
                if number < 1.0:
                    raise ValueError(f"{item.name} must be at least 1")
            elif not 0.0 <= number <= 1.0:
                raise ValueError(f"{item.name} must be between 0 and 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PromotionThresholds":
        """Build a policy from snake_case or documented camelCase keys.

        Unknown keys are rejected rather than ignored so a misspelled gate
        cannot accidentally make an offline report less conservative.
        """
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("intelligence thresholds must be a JSON object")
        names = {item.name for item in fields(cls)}
        camel = {
            name: "".join(
                part.capitalize() if index else part
                for index, part in enumerate(name.split("_"))
            )
            for name in names
        }
        normalized: dict[str, Any] = {}
        for key, raw in value.items():
            name = str(key)
            if name in names:
                target = name
            else:
                target = next((snake for snake, public in camel.items() if public == name), None)
            if target is None:
                raise ValueError(f"unknown intelligence threshold: {name}")
            normalized[target] = raw
        return cls(**normalized)

    def as_dict(self) -> dict[str, Any]:
        """Return the policy using its configuration field names."""
        return {item.name: getattr(self, item.name) for item in fields(self)}

    def dataset_requirements(self) -> dict[str, Any]:
        """Return the historical dataset-quality key names for compatibility."""
        return {
            "minimumIndependentUsableGroups": self.minimum_independent_usable_groups,
            "minimumIndependentUsableGroupsPerClass": (
                self.minimum_independent_usable_groups_per_class
            ),
            "minimumValidationPerClass": self.minimum_validation_per_class,
            "minimumTestPerClass": self.minimum_test_per_class,
            "minimumCategories": self.minimum_categories,
            "minimumUsableLabelsPerCategory": self.minimum_usable_labels_per_category,
            "maximumDominantCategoryRate": self.maximum_dominant_category_rate,
            "minimumLabelCompleteness": self.minimum_label_completeness,
            "maximumClassImbalanceRatio": self.maximum_class_imbalance_ratio,
            "maximumFeatureMissingRate": self.maximum_feature_missing_rate,
            "maximumRejectedLeakageRate": self.maximum_rejected_leakage_rate,
        }

    def evaluation_requirements(self) -> dict[str, Any]:
        """Return thresholds used to evaluate model promotion evidence."""
        return {
            "minimumBalancedAccuracyImprovement": self.minimum_balanced_accuracy_improvement,
            "minimumDisagreements": self.minimum_disagreements,
            "maximumPairedPValue": self.maximum_paired_p_value,
            "maximumDelegateFalseNegativeRate": self.maximum_delegate_false_negative_rate,
            "maximumExpectedCalibrationError": self.maximum_expected_calibration_error,
            "maximumBrierScore": self.maximum_brier_score,
            "minimumCategoryEvaluationSamples": self.minimum_category_evaluation_samples,
            "minimumCategoryClassSamples": self.minimum_category_class_samples,
        }


DEFAULT_PROMOTION_THRESHOLDS = PromotionThresholds()


def load_promotion_thresholds(path: str | os.PathLike[str] | None = None) -> PromotionThresholds:
    """Load an optional bounded JSON policy for offline evaluation.

    The file is never consulted by request-time routing.  It is accepted only
    by diagnostic/training commands and is kept small to avoid turning the
    report command into an arbitrary file reader.
    """
    if path is None:
        return DEFAULT_PROMOTION_THRESHOLDS
    candidate = Path(path).expanduser().resolve(strict=False)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("intelligence thresholds must be a regular file")
    if candidate.stat().st_size > 64_000:
        raise ValueError("intelligence thresholds file exceeds 64 KB")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("intelligence thresholds file is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("intelligence thresholds file must contain an object")
    if "schemaVersion" in payload and payload["schemaVersion"] != READINESS_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported intelligence thresholds schema")
    values = payload.get("thresholds", payload)
    if not isinstance(values, Mapping):
        raise ValueError("intelligence thresholds must be an object")
    return PromotionThresholds.from_mapping(values)


def _gate(
    name: str,
    passed: bool | None,
    *,
    evidence: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build a normalized promotion-gate result."""
    status = "BLOCKED" if passed is None else "PASS" if passed else "FAIL"
    result: dict[str, Any] = {"status": status}
    if evidence:
        result["evidence"] = dict(evidence)
    if reason:
        result["reason"] = reason
    return result


def promotion_gate_summary(
    *,
    maturity: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    """Evaluate conservative, explicit gates for an offline selector.

    ``None`` means that evidence was not available, which is intentionally
    different from a measured failure.  This lets reports distinguish
    ``BLOCKED`` data collection from a model that was actually evaluated and
    performed poorly.
    """
    policy = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    data_gates = maturity.get("candidateGates")
    if not isinstance(data_gates, Mapping):
        data_gates = {}
    gates: dict[str, dict[str, Any]] = {}
    eligible_categories: list[str] = []
    gate_names = (
        "independentUsableGroups",
        "directGroups",
        "delegateGroups",
        "validationPerClass",
        "testPerClass",
        "categoryCoverage",
        "blindHumanGoldBothClasses",
        "credibleChronology",
        "zeroDecisionOutcomeLeakage",
        "zeroCrossSplitContamination",
        "featureSchemaFrozen",
    )
    for name in gate_names:
        value = data_gates.get(name)
        gates[f"data.{name}"] = _gate(
            f"data.{name}",
            bool(value) if isinstance(value, bool) else None,
            evidence={"value": value} if value is not None else None,
            reason=("dataset-quality gate is not satisfied" if value is False else None),
        )

    label_rate = maturity.get("labelCompleteness", {}).get("rate")
    gates["data.labelCompleteness"] = _gate(
        "data.labelCompleteness",
        None if label_rate is None else float(label_rate) >= policy.minimum_label_completeness,
        evidence={"rate": label_rate, "minimum": policy.minimum_label_completeness},
    )
    imbalance = maturity.get("classImbalance", {}).get("ratio")
    gates["data.classBalance"] = _gate(
        "data.classBalance",
        None if imbalance is None else float(imbalance) <= policy.maximum_class_imbalance_ratio,
        evidence={"ratio": imbalance, "maximum": policy.maximum_class_imbalance_ratio},
    )
    feature_missing = maturity.get("featureCoverage", {}).get("missingRate")
    gates["data.featureCoverage"] = _gate(
        "data.featureCoverage",
        None if feature_missing is None else float(feature_missing) <= policy.maximum_feature_missing_rate,
        evidence={"missingRate": feature_missing, "maximum": policy.maximum_feature_missing_rate},
    )
    leakage = maturity.get("rejections", {}).get("leakage", 0)
    eligible = max(1, int(maturity.get("eligibleExamples", 0) or 0))
    leakage_rate = float(leakage) / eligible
    gates["data.leakageRejection"] = _gate(
        "data.leakageRejection",
        leakage_rate <= policy.maximum_rejected_leakage_rate,
        evidence={"count": leakage, "rate": round(leakage_rate, 6), "maximum": policy.maximum_rejected_leakage_rate},
    )

    if not evaluation or evaluation.get("status") not in {"evaluated", "ready"}:
        for name in (
            "holdoutPerformance",
            "noRegressionAgainstDeterministic",
            "calibration",
            "categoryPerformance",
            "pairedDisagreementEvidence",
            "reproducibility",
        ):
            gates[f"model.{name}"] = _gate(
                f"model.{name}", None,
                reason="evaluation evidence is unavailable",
            )
    else:
        baseline = evaluation.get("baseline", {}).get("metrics", {})
        model = evaluation.get("model", {}).get("metrics", {})
        baseline = baseline if isinstance(baseline, Mapping) else {}
        model = model if isinstance(model, Mapping) else {}
        baseline_balanced = baseline.get("balancedAccuracy")
        model_balanced = model.get("balancedAccuracy")
        improvement = (
            float(model_balanced) - float(baseline_balanced)
            if baseline_balanced is not None and model_balanced is not None else None
        )
        gates["model.holdoutPerformance"] = _gate(
            "model.holdoutPerformance",
            None if improvement is None else improvement >= policy.minimum_balanced_accuracy_improvement,
            evidence={"improvement": improvement, "minimum": policy.minimum_balanced_accuracy_improvement},
        )
        model_f1 = model.get("f1")
        baseline_f1 = baseline.get("f1")
        model_fnr = model.get("delegateFalseNegativeRate")
        baseline_fnr = baseline.get("delegateFalseNegativeRate")
        no_regression = (
            None if any(value is None for value in (model_f1, baseline_f1, model_fnr, baseline_fnr))
            else float(model_f1) >= float(baseline_f1)
            and float(model_fnr) <= float(baseline_fnr)
            and float(model_fnr) <= policy.maximum_delegate_false_negative_rate
        )
        gates["model.noRegressionAgainstDeterministic"] = _gate(
            "model.noRegressionAgainstDeterministic",
            no_regression,
            evidence={
                "modelF1": model_f1,
                "baselineF1": baseline_f1,
                "modelDelegateFalseNegativeRate": model_fnr,
                "baselineDelegateFalseNegativeRate": baseline_fnr,
            },
        )
        calibration = (
            evaluation.get("delegateProbabilityCalibration")
            or evaluation.get("calibration")
            or evaluation.get("confidenceCalibration")
        )
        calibration = calibration if isinstance(calibration, Mapping) else {}
        ece = calibration.get("expectedCalibrationError")
        brier = calibration.get("brierScore")
        calibration_pass = (
            None if ece is None or brier is None else
            float(ece) <= policy.maximum_expected_calibration_error
            and float(brier) <= policy.maximum_brier_score
        )
        gates["model.calibration"] = _gate(
            "model.calibration",
            calibration_pass,
            evidence={
                "expectedCalibrationError": ece,
                "brierScore": brier,
                "maximumExpectedCalibrationError": policy.maximum_expected_calibration_error,
                "maximumBrierScore": policy.maximum_brier_score,
            },
        )
        categories = evaluation.get("performanceByTaskCategory") or evaluation.get("performanceByCategory")
        category_values = categories if isinstance(categories, Mapping) else {}
        supported = []
        category_failures = []
        for category, report in category_values.items():
            if not isinstance(report, Mapping):
                continue
            sample_count = int(report.get("sampleCount", 0) or 0)
            balance = report.get("classBalance", {})
            if sample_count < policy.minimum_category_evaluation_samples:
                continue
            if not isinstance(balance, Mapping) or any(
                int(balance.get(label, 0) or 0) < policy.minimum_category_class_samples
                for label in ("DIRECT", "DELEGATE")
            ):
                continue
            supported.append(str(category))
            category_model = report.get("modelMetrics", {})
            category_baseline = report.get("baselineMetrics", {})
            if isinstance(category_model, Mapping) and isinstance(category_baseline, Mapping):
                if float(category_model.get("balancedAccuracy", 0.0)) < float(
                    category_baseline.get("balancedAccuracy", 0.0)
                ):
                    category_failures.append(str(category))
        category_pass = (
            None if not category_values else
            len(supported) >= policy.minimum_categories and not category_failures
        )
        gates["model.categoryPerformance"] = _gate(
            "model.categoryPerformance",
            category_pass,
            evidence={
                "supportedCategories": sorted(supported),
                "minimumCategories": policy.minimum_categories,
                "regressions": sorted(category_failures),
            },
        )
        eligible_categories = sorted(supported)
        paired = evaluation.get("pairedComparison") or {}
        if not isinstance(paired, Mapping):
            paired = {}
        disagreements = paired.get("disagreements")
        paired_pass = (
            None if disagreements is None or paired.get("exactMcNemarPValue") is None else
            int(disagreements) >= policy.minimum_disagreements
            and int(paired.get("modelWins", 0)) > int(paired.get("baselineWins", 0))
            and float(paired["exactMcNemarPValue"]) <= policy.maximum_paired_p_value
        )
        gates["model.pairedDisagreementEvidence"] = _gate(
            "model.pairedDisagreementEvidence",
            paired_pass,
            evidence={
                "disagreements": disagreements,
                "modelWins": paired.get("modelWins"),
                "baselineWins": paired.get("baselineWins"),
                "exactMcNemarPValue": paired.get("exactMcNemarPValue"),
            },
        )
        reproducible = evaluation.get("benchmarkReproducibility", {}).get("passed")
        gates["model.reproducibility"] = _gate(
            "model.reproducibility",
            bool(reproducible) if isinstance(reproducible, bool) else None,
        )

    failed = [name for name, value in gates.items() if value["status"] == "FAIL"]
    blocked = [name for name, value in gates.items() if value["status"] == "BLOCKED"]
    promotion_ready = bool(gates) and not failed and not blocked
    data_not_ready = any(
        name.startswith("data.") and value["status"] != "PASS"
        for name, value in gates.items()
    )
    overall_status = (
        "READY" if promotion_ready
        else "BLOCKED BY DATA" if data_not_ready
        else "NOT READY"
    )
    return {
        "schemaVersion": READINESS_POLICY_SCHEMA_VERSION,
        "status": overall_status,
        "promotionReady": promotion_ready,
        "recommendedMode": "shadow" if not promotion_ready else "category_limited_advisory",
        "eligibleCategories": eligible_categories,
        "authorityScope": "none",
        "gates": gates,
        "gatesPassed": [name for name, value in gates.items() if value["status"] == "PASS"],
        "gatesFailed": failed,
        "gatesBlocked": blocked,
        "thresholds": policy.as_dict(),
    }
