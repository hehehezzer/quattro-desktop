"""Evidence-acquisition progress, quality states, and sealed-holdout helpers.

This module is deliberately offline-only.  It summarizes independent review
evidence and protects immutable evaluation cohorts; it is never imported by
request-time routing.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .readiness import DEFAULT_PROMOTION_THRESHOLDS, PromotionThresholds
from .review import TARGET_CATEGORIES, sampling_category


EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_QUALITY_STATES = (
    "unlabeled",
    "single_review",
    "disputed",
    "consensus",
    "adjudicated",
    "rejected",
    "contaminated",
    "curated_fixture",
    "machine_consensus",
    "legacy_exposed",
)
GOLD_PROVENANCE_CLASSES = (
    "human_blind",
    "consensus_human_blind",
    "adjudicated_human",
    "curated_fixture",
)


def _requirement(current: int, required: int) -> dict[str, int]:
    return {
        "current": int(current),
        "required": int(required),
        "deficit": max(0, int(required) - int(current)),
    }


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def evidence_acquisition_progress(
    rows: Sequence[Mapping[str, Any]],
    *,
    blind_audit: Mapping[str, Any],
    holdout_summary: Mapping[str, Any] | None = None,
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    """Report live evidence deficits without treating model output as truth."""
    policy = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    representatives: dict[str, Mapping[str, Any]] = {}
    latest_created_at: dict[str, str] = {}
    source_priority = {"human_gold": 0, "probe_gold": 1, "silver": 2}
    for row in rows:
        if bool(row.get("holdout_sealed")):
            continue
        group = str(row.get("group_fingerprint") or row.get("record_id") or "")
        parsed = _parse_time(row.get("created_at"))
        current = _parse_time(latest_created_at.get(group))
        if parsed is not None and (current is None or parsed > current):
            latest_created_at[group] = str(row.get("created_at"))
    for row in rows:
        if bool(row.get("holdout_sealed")):
            continue
        if row.get("label") not in {"DIRECT", "DELEGATE"}:
            continue
        if not bool(row.get("label_independent")):
            continue
        group = str(row.get("group_fingerprint") or row.get("record_id") or "")
        prior = representatives.get(group)
        if prior is None or source_priority.get(
            str(row.get("label_source")), 9
        ) < source_priority.get(str(prior.get("label_source")), 9):
            representatives[group] = row
    usable = [
        dict(row) | {"created_at": latest_created_at.get(group, row.get("created_at"))}
        for group, row in representatives.items()
    ]
    human_gold_rows = [
        row for row in usable if row.get("label_source") == "human_gold"
    ]
    classes = Counter(str(row["label"]) for row in usable)
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    sampling_categories: dict[str, Counter[str]] = defaultdict(Counter)
    human_gold_categories: dict[str, Counter[str]] = defaultdict(Counter)
    complexities: dict[str, Counter[str]] = defaultdict(Counter)
    for row in usable:
        label = str(row["label"])
        evidence_category = str(
            row.get("evidence_task_category")
            or row.get("task_category")
            or "unknown"
        )
        categories[evidence_category][label] += 1
        sampling_categories[sampling_category(str(row.get("request_text") or ""))][
            label
        ] += 1
        if row.get("label_source") == "human_gold":
            human_gold_categories[
                evidence_category
            ][label] += 1
        complexities[str(
            row.get("evidence_complexity") or row.get("complexity") or "unknown"
        )][label] += 1

    category_rows = {}
    for category, balance in sorted(categories.items()):
        total = sum(balance.values())
        category_rows[category] = {
            **_requirement(total, policy.minimum_usable_labels_per_category),
            "classRepresentation": {
                label: int(balance[label]) for label in ("DIRECT", "DELEGATE")
            },
            "acceptedHumanGold": sum(human_gold_categories[category].values()),
            "humanGoldClassRepresentation": {
                label: int(human_gold_categories[category][label])
                for label in ("DIRECT", "DELEGATE")
            },
        }
    covered_categories = sum(
        value["deficit"] == 0 for value in category_rows.values()
    )

    complexity_rows = {}
    for band in ("low", "medium", "high", "unknown"):
        balance = complexities.get(band, Counter())
        total = sum(balance.values())
        complexity_rows[band] = {
            **_requirement(total, policy.minimum_usable_labels_per_complexity_band),
            "classRepresentation": {
                label: int(balance[label]) for label in ("DIRECT", "DELEGATE")
            },
        }
    covered_complexities = sum(
        complexity_rows[band]["deficit"] == 0 for band in ("low", "medium", "high")
    )

    gold_balance = Counter(str(row["label"]) for row in human_gold_rows)
    audited_quality_states = Counter({
        str(key): int(value)
        for key, value in (blind_audit.get("qualityStates", {}) or {}).items()
    })
    group_quality: dict[str, str] = {}
    quality_priority = {
        "contaminated": 0, "adjudicated": 1, "consensus": 2,
        "disputed": 3, "single_review": 4, "rejected": 5,
        "legacy_exposed": 6, "curated_fixture": 7,
        "machine_consensus": 8, "unlabeled": 9,
    }
    for row in rows:
        group = str(row.get("group_fingerprint") or row.get("record_id"))
        quality = str(row.get("evidence_quality") or "")
        if not quality:
            if row.get("label_conflict"):
                quality = "contaminated"
            elif row.get("label_source") == "probe_gold":
                quality = "curated_fixture"
            elif row.get("label_source") == "silver":
                quality = "machine_consensus"
            elif row.get("labeling_method") == "legacy_exposed_review":
                quality = "legacy_exposed"
            else:
                quality = "unlabeled"
        prior = group_quality.get(group)
        if prior is None or quality_priority.get(quality, 99) < quality_priority.get(prior, 99):
            group_quality[group] = quality
    quality_states = Counter(group_quality.values())
    for key, value in audited_quality_states.items():
        quality_states[key] = max(quality_states[key], value)
    provenance = Counter({
        str(key): int(value)
        for key, value in (blind_audit.get("acceptedProvenanceBalance", {}) or {}).items()
    })
    provenance["human_blind"] += int(
        (blind_audit.get("individualVoteProvenance", {}) or {}).get(
            "human_blind", 0
        )
    )
    provenance["curated_fixture"] += sum(
        1 for row in usable if row.get("label_source") == "probe_gold"
    )
    timestamped = sorted(
        parsed for parsed in (_parse_time(row.get("created_at")) for row in usable)
        if parsed is not None
    )
    human_timestamped = sorted(
        parsed for parsed in (
            _parse_time(row.get("created_at")) for row in human_gold_rows
        ) if parsed is not None
    )
    human_gold_count = len(human_gold_rows)
    human_gold = {
        **_requirement(human_gold_count, policy.minimum_human_gold_groups),
        "byClass": {
            label: _requirement(
                gold_balance[label], policy.minimum_human_gold_groups_per_class
            )
            for label in ("DIRECT", "DELEGATE")
        },
    }
    human_partitions = chronological_partition(human_gold_rows)
    label_by_group = {
        str(row.get("group_fingerprint") or row.get("record_id")): str(row["label"])
        for row in human_gold_rows
    }
    chronological_train_balance = Counter(
        label_by_group[group] for group in human_partitions["train"]
    )
    chronological_evaluation_balance = Counter(
        label_by_group[group]
        for group in (
            human_partitions["validation"] + human_partitions["unsealedNewest"]
        )
    )
    chronology_usable = bool(
        human_gold["deficit"] == 0
        and all(value["deficit"] == 0 for value in human_gold["byClass"].values())
        and len(human_timestamped) == len(human_gold_rows)
        and bool(human_timestamped)
        and all(
            chronological_train_balance[label]
            >= policy.minimum_human_gold_groups_per_class
            for label in ("DIRECT", "DELEGATE")
        )
        and all(
            chronological_evaluation_balance[label]
            >= policy.minimum_human_gold_groups_per_class
            for label in ("DIRECT", "DELEGATE")
        )
    )
    return {
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "global": _requirement(
            len(usable), policy.minimum_independent_usable_groups
        ),
        "classes": {
            label: _requirement(
                classes[label], policy.minimum_independent_usable_groups_per_class
            )
            for label in ("DIRECT", "DELEGATE")
        },
        "categoryCoverage": {
            **_requirement(covered_categories, policy.minimum_categories),
            "minimumPerCategory": policy.minimum_usable_labels_per_category,
            "categories": category_rows,
        },
        "complexityCoverage": {
            **_requirement(
                covered_complexities, policy.minimum_complexity_bands
            ),
            "minimumPerBand": policy.minimum_usable_labels_per_complexity_band,
            "bands": complexity_rows,
        },
        "humanGold": human_gold,
        "goldProvenance": {
            key: int(provenance[key]) for key in GOLD_PROVENANCE_CLASSES
        },
        "qualityStates": {
            key: int(quality_states[key]) for key in EVIDENCE_QUALITY_STATES
        },
        "chronology": {
            "usable": chronology_usable,
            "oldestTimestamp": timestamped[0].isoformat() if timestamped else None,
            "newestTimestamp": timestamped[-1].isoformat() if timestamped else None,
            "timestampedIndependentGroups": len(timestamped),
            "timestampedHumanGoldGroups": len(human_timestamped),
            "oldestHumanGoldTimestamp": (
                human_timestamped[0].isoformat() if human_timestamped else None
            ),
            "newestHumanGoldTimestamp": (
                human_timestamped[-1].isoformat() if human_timestamped else None
            ),
            "trainingClassBalance": {
                label: int(chronological_train_balance[label])
                for label in ("DIRECT", "DELEGATE")
            },
            "evaluationClassBalance": {
                label: int(chronological_evaluation_balance[label])
                for label in ("DIRECT", "DELEGATE")
            },
        },
        "sealedHoldout": dict(holdout_summary or {
            "sealed": False,
            "cohortCount": 0,
            "latest": None,
        }),
        "nextCollectionTargets": acquisition_targets(
            classes=classes,
            categories=sampling_categories,
            complexities=complexities,
            human_gold_balance=gold_balance,
            thresholds=policy,
        ),
    }


def acquisition_targets(
    *,
    classes: Mapping[str, int],
    categories: Mapping[str, Mapping[str, int]],
    complexities: Mapping[str, Mapping[str, int]],
    human_gold_balance: Mapping[str, int],
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    """Build hidden sampling weights from policy deficits, never gold labels."""
    policy = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    class_deficits = {
        label: max(
            0,
            policy.minimum_independent_usable_groups_per_class
            - int(classes.get(label, 0)),
        )
        for label in ("DIRECT", "DELEGATE")
    }
    category_deficits = {
        name: max(
            0,
            policy.minimum_usable_labels_per_category - sum(map(
                int, categories.get(name, {}).values()
            )),
        )
        for name in TARGET_CATEGORIES
    }
    complexity_deficits = {
        name: max(
            0,
            policy.minimum_usable_labels_per_complexity_band
            - sum(map(int, balance.values())),
        )
        for name, balance in complexities.items()
    }
    return {
        "classDeficits": class_deficits,
        "categoryDeficits": category_deficits,
        "complexityDeficits": complexity_deficits,
        "humanGoldClassDeficits": {
            label: max(
                0,
                policy.minimum_human_gold_groups_per_class
                - int(human_gold_balance.get(label, 0)),
            )
            for label in ("DIRECT", "DELEGATE")
        },
    }


def chronological_partition(
    rows: Sequence[Mapping[str, Any]],
    *,
    sealed_group_fingerprints: set[str] | frozenset[str] = frozenset(),
) -> dict[str, list[str]]:
    """Partition groups by trusted event time with sealed groups always held out."""
    by_group: dict[str, Mapping[str, Any]] = {}
    latest_by_group: dict[str, dt.datetime] = {}
    for row in rows:
        timestamp = _parse_time(row.get("created_at"))
        if timestamp is None:
            continue
        group = str(row.get("group_fingerprint") or row.get("record_id"))
        if group not in latest_by_group or timestamp > latest_by_group[group]:
            latest_by_group[group] = timestamp
    for row in rows:
        if row.get("label") not in {"DIRECT", "DELEGATE"}:
            continue
        if not bool(row.get("label_independent")):
            continue
        if _parse_time(row.get("created_at")) is None:
            continue
        group = str(row.get("group_fingerprint") or row.get("record_id"))
        current = by_group.get(group)
        if current is None:
            by_group[group] = row
    # A family becomes available only when its newest member exists.  This
    # prevents a later unlabeled paraphrase from leaking into an older epoch.
    ordered = sorted(
        by_group,
        key=lambda group: (
            latest_by_group[group], group
        ),
    )
    unsealed = [group for group in ordered if group not in sealed_group_fingerprints]
    train_end = int(len(unsealed) * 0.70)
    validation_end = int(len(unsealed) * 0.90)
    return {
        "train": unsealed[:train_end],
        "validation": unsealed[train_end:validation_end],
        "futureHoldout": [
            group for group in ordered if group in sealed_group_fingerprints
        ],
        "unsealedNewest": unsealed[validation_end:],
    }
