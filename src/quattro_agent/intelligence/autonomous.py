"""Autonomous, provenance-separated evidence for Phase 2.2 experiments.

Autonomous observations are deliberately not human-gold.  This module turns
already-sanitized runtime records into one representative per connected group,
uses the deterministic production decision only as an explicitly named weak
training target, and keeps outcomes, model disagreements, and provider
telemetry as observations.  It never writes routing labels or changes runtime
authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .features import forbidden_payload_paths, project_model_input


AUTONOMOUS_SCHEMA_VERSION = 1
AUTONOMOUS_DATASET_SCHEMA = "direct-delegate-autonomous-evidence-v1"
AUTONOMOUS_LABEL_SOURCE = "autonomous_deterministic"
AUTONOMOUS_LABELING_METHOD = "autonomous_deterministic_observation_v1"


@dataclass(frozen=True)
class AutonomousTrainingThresholds:
    """Conservative capacity gates for experimental-only training."""

    minimum_independent_groups: int = 128
    minimum_groups_per_class: int = 32
    minimum_categories: int = 4
    minimum_groups_per_category: int = 30
    minimum_complexity_bands: int = 3
    minimum_groups_per_complexity: int = 30
    minimum_train_groups_per_class: int = 16

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{item.name} must be a positive integer")

    def as_dict(self) -> dict[str, int]:
        return {item.name: int(getattr(self, item.name)) for item in fields(self)}


DEFAULT_AUTONOMOUS_TRAINING_THRESHOLDS = AutonomousTrainingThresholds()


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _representatives(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Select one earliest deterministic-observation row per connected group."""
    selected: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if bool(row.get("holdout_sealed")):
            continue
        if row.get("production_decision") not in {"DIRECT", "DELEGATE"}:
            continue
        request = str(row.get("request_text") or "")
        if not request:
            continue
        group = str(row.get("group_fingerprint") or row.get("record_id") or "")
        if not group:
            continue
        prior = selected.get(group)
        if prior is None:
            selected[group] = row
            continue
        prior_time = _parse_time(prior.get("created_at"))
        current_time = _parse_time(row.get("created_at"))
        if (
            current_time is not None
            and (prior_time is None or current_time < prior_time)
        ) or (
            current_time == prior_time
            and str(row.get("record_id")) < str(prior.get("record_id"))
        ):
            selected[group] = row
    return [dict(selected[group]) for group in sorted(selected)]


def autonomous_training_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project deterministic observations into an experimental target view.

    The returned rows are in-memory/private experimental data.  Their
    ``label_source`` explicitly prevents them from satisfying human-gold or
    production-promotion gates.
    """
    projected: list[dict[str, Any]] = []
    for row in _representatives(rows):
        value = dict(row)
        value.update({
            "label": str(row["production_decision"]),
            "label_source": AUTONOMOUS_LABEL_SOURCE,
            "labeling_method": AUTONOMOUS_LABELING_METHOD,
            "label_independent": True,
            "label_confidence": None,
            "gold_provenance": None,
            "evidence_quality": "autonomous_observation",
            "reviewed_label": None,
            "reviewed_label_source": None,
            "reviewed_at": None,
            "label_resolution_event_id": None,
            "label_conflict": False,
            "autonomous_target_kind": "deterministic_production_observation",
        })
        projected.append(value)
    return projected


def _group_counts(rows: Sequence[Mapping[str, Any]], key: str) -> Counter[str]:
    return Counter(str(row.get(key) or "unknown") for row in rows)


def _safe_feature_audit(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for row in rows:
        try:
            projected = project_model_input(row)
            findings = forbidden_payload_paths({
                key: value for key, value in projected.items() if key != "request_text"
            })
            if findings:
                failures.append({
                    "recordId": str(row.get("record_id") or "unknown"),
                    "error": f"forbidden projected paths: {findings}",
                })
        except (KeyError, TypeError, ValueError) as error:
            failures.append({
                "recordId": str(row.get("record_id") or "unknown"),
                "error": str(error),
            })
    return {
        "passed": not failures,
        "failureCount": len(failures),
        "failures": failures[:20],
        "scope": "decision_time_model_input_only",
    }


def _split_group_collisions(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    assignments: dict[str, set[str]] = {}
    for row in rows:
        group = str(row.get("group_fingerprint") or row.get("record_id") or "")
        split = str(row.get("split") or "unknown")
        assignments.setdefault(group, set()).add(split)
    return sorted(group for group, splits in assignments.items() if len(splits) > 1)


def autonomous_evidence_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    thresholds: AutonomousTrainingThresholds | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a bounded autonomous evidence report without creating gold labels."""
    policy = thresholds or DEFAULT_AUTONOMOUS_TRAINING_THRESHOLDS
    projected = autonomous_training_rows(rows)
    classes = _group_counts(projected, "label")
    categories = _group_counts(projected, "task_category")
    complexities = _group_counts(projected, "complexity")
    train_rows = [row for row in projected if row.get("split") == "train"]
    train_classes = _group_counts(train_rows, "label")
    covered_categories = sum(
        count >= policy.minimum_groups_per_category for count in categories.values()
    )
    covered_complexities = sum(
        count >= policy.minimum_groups_per_complexity
        for count in complexities.values()
        if count >= policy.minimum_groups_per_complexity
    )
    feature_audit = _safe_feature_audit(projected)
    collisions = _split_group_collisions(rows)
    known_outcomes = sum(row.get("outcome_success") is not None for row in projected)
    successes = sum(row.get("outcome_success") is True for row in projected)
    disagreements = sum(
        row.get("ml_prediction") in {"DIRECT", "DELEGATE"}
        and row.get("production_decision") in {"DIRECT", "DELEGATE"}
        and row.get("ml_prediction") != row.get("production_decision")
        for row in projected
    )
    providers = Counter(str(row.get("selected_provider") or "unknown") for row in projected)
    source_kinds = Counter(str(row.get("source_kind") or "unknown") for row in projected)
    gates = {
        "observationsAvailable": len(projected) >= policy.minimum_independent_groups,
        "bothClasses": all(
            classes[label] >= policy.minimum_groups_per_class
            for label in ("DIRECT", "DELEGATE")
        ),
        "categoryCoverage": covered_categories >= policy.minimum_categories,
        "complexityCoverage": covered_complexities >= policy.minimum_complexity_bands,
        "trainSplitBothClasses": all(
            train_classes[label] >= policy.minimum_train_groups_per_class
            for label in ("DIRECT", "DELEGATE")
        ),
        "zeroFeatureLeakage": bool(feature_audit["passed"]),
        "zeroCrossSplitGroupContamination": not collisions,
        "noSealedHoldoutTraining": not any(
            bool(row.get("holdout_sealed")) for row in projected
        ),
    }
    return projected, {
        "schemaVersion": AUTONOMOUS_SCHEMA_VERSION,
        "datasetSchema": AUTONOMOUS_DATASET_SCHEMA,
        "labelSource": AUTONOMOUS_LABEL_SOURCE,
        "labelSemantics": (
            "deterministic production decisions are observed weak targets for "
            "experimental training only; they are not human judgments or gold"
        ),
        "trainingReadiness": {
            "status": "READY" if all(gates.values()) else "BLOCKED_BY_DATA",
            "promotionAuthority": "none",
            "thresholds": policy.as_dict(),
            "gates": gates,
        },
        "observationCount": len(projected),
        "independentGroupCount": len(projected),
        "classBalance": dict(sorted(classes.items())),
        "taskCategoryBalance": dict(sorted(categories.items())),
        "complexityBalance": dict(sorted(complexities.items())),
        "trainClassBalance": dict(sorted(train_classes.items())),
        "coveredCategories": covered_categories,
        "coveredComplexityBands": covered_complexities,
        "sourceKindBalance": dict(sorted(source_kinds.items())),
        "providerBalance": dict(sorted(providers.items())),
        "outcomeObservation": {
            "known": known_outcomes,
            "successes": successes,
            "failures": sum(row.get("outcome_success") is False for row in projected),
            "counterfactualAvailable": False,
            "counterfactualStatus": "unavailable",
        },
        "disagreementObservation": {
            "count": disagreements,
            "meaning": "observed shadow/router disagreement; not a counterfactual win",
        },
        "featureAudit": feature_audit,
        "crossSplitGroupCollisions": collisions,
        "protectedHumanGoldUsedAsAutonomousTarget": False,
        "humanGoldCreated": 0,
        "experimentalOnly": True,
    }


def autonomous_dataset_identity(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    """Return a content-addressed identity for the private autonomous snapshot."""
    canonical = json.dumps(
        list(rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"dd-autonomous-{digest[:16]}", digest


def write_autonomous_snapshot(
    directory: Path,
    dataset_version: str,
    rows: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> dict[str, str]:
    """Write a private, content-addressed autonomous evidence snapshot."""
    directory = directory.expanduser().resolve(strict=False)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    data_path = directory / f"{dataset_version}.jsonl"
    report_path = directory / f"{dataset_version}.manifest.json"
    data = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
        for row in rows
    )
    manifest = dict(report) | {
        "datasetVersion": dataset_version,
        "contentSha256": dataset_version.removeprefix("dd-autonomous-"),
        "recordCount": len(rows),
        "datasetPath": str(data_path),
    }
    for path, content in (
        (data_path, data),
        (report_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"),
    ):
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"autonomous artifact is not a regular file: {path}")
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"autonomous artifact differs from existing file: {path}")
        else:
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(path)
        path.chmod(0o600)
    return {"datasetPath": str(data_path), "manifestPath": str(report_path)}


def autonomous_agreement(
    model: Any,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare an experimental model with observed deterministic decisions only."""
    evaluation = [row for row in rows if row.get("split") == "test"]
    predictions = [
        model.predict(
            str(row["request_text"]),
            profile=row,
            repository_present=bool(row.get("repository_present")),
        )["prediction"]
        for row in evaluation
    ]
    labels = [str(row["label"]) for row in evaluation]
    correct = sum(prediction == label for prediction, label in zip(predictions, labels))
    counts = Counter(labels)
    per_class = {}
    for label in ("DIRECT", "DELEGATE"):
        total = counts[label]
        per_class[label] = {
            "count": total,
            "accuracy": (
                sum(prediction == label and actual == label for prediction, actual in zip(predictions, labels))
                / total if total else None
            ),
        }
    balanced = [value["accuracy"] for value in per_class.values() if value["accuracy"] is not None]
    return {
        "status": "evaluated" if evaluation else "unavailable",
        "scope": "autonomous_deterministic_observation_test_split",
        "notCounterfactual": True,
        "sampleCount": len(evaluation),
        "agreementRate": round(correct / len(evaluation), 6) if evaluation else None,
        "classAgreement": per_class,
        "balancedAgreement": round(sum(balanced) / len(balanced), 6) if balanced else None,
    }
