"""Historical extraction and immutable DIRECT/DELEGATE dataset versions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..routing_intelligence import profile_task
from .features import (
    decision_profile,
    feature_audit,
    forbidden_payload_paths,
    project_model_input,
)
from .maturity import data_maturity
from .readiness import DEFAULT_PROMOTION_THRESHOLDS, PromotionThresholds
from .store import DATASET_SCHEMA_VERSION, FEATURE_SCHEMA_VERSION, IntelligenceStore
from .telemetry import (
    record_routing_telemetry,
    request_fingerprint,
    sanitize_request,
    update_execution_telemetry,
)


def _decode(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _duration_ms(started_at: str | None, completed_at: str | None) -> float | None:
    started = _parse_time(started_at)
    completed = _parse_time(completed_at)
    if not started or not completed:
        return None
    return max(0.0, (completed - started).total_seconds() * 1_000)


def _split(group_fingerprint: str) -> str:
    bucket = int(hashlib.sha256(group_fingerprint.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "validation"
    return "test"


REAL_LABEL_SOURCES = frozenset({"human_gold", "human_verified", "reviewed_outcome"})
TRAINING_LABEL_SOURCES = frozenset({"human_gold", "probe_gold", "silver"})
SUPPORTED_DATASET_SCHEMA_VERSIONS = frozenset({
    "direct-delegate-dataset-v2",
    "direct-delegate-dataset-v3",
    "direct-delegate-dataset-v4",
    "direct-delegate-dataset-v5",
    "direct-delegate-dataset-v6",
    "direct-delegate-dataset-v7",
    "direct-delegate-dataset-v8",
    "direct-delegate-dataset-v9",
    DATASET_SCHEMA_VERSION,
})
# Kept as a public compatibility mapping for existing callers.  New code
# should pass a PromotionThresholds instance to dataset_quality instead of
# copying readiness constants into another module.
READINESS_REQUIREMENTS = DEFAULT_PROMOTION_THRESHOLDS.dataset_requirements()

_NEAR_DUPLICATE_TOKEN = re.compile(r"[a-z0-9_./-]+")
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.80
SEMANTIC_DUPLICATE_THRESHOLD = 0.75
SEMANTIC_REPRESENTATION_VERSION = "deterministic-concept-bigrams-v1"
INDEPENDENT_LABEL_METHODS = frozenset({
    "blind_human_review_v1",
    "blind_human_review_v2",
    "probe_contract",
    "probe_contract_v1",
    "probe_contract_v2",
    "legacy_probe_contract",
    "silver_consensus",
    "silver_consensus_v1",
})


def label_is_independent(source: str, method: str) -> bool:
    if source not in TRAINING_LABEL_SOURCES:
        return False
    return method in INDEPENDENT_LABEL_METHODS


def canonical_label_source(source: Any, *, excluded: bool = False) -> str:
    if excluded:
        return "excluded"
    value = str(source or "")
    if value in {"human_verified", "reviewed_outcome", "human_gold"}:
        return "human_gold"
    if value in {"curated_benchmark", "probe_gold"}:
        return "probe_gold"
    if value == "silver":
        return "silver"
    return "excluded"


def _request_tokens(value: Any) -> frozenset[str]:
    return frozenset(_NEAR_DUPLICATE_TOKEN.findall(str(value).lower())[:256])


def _near_duplicate_pairs(
    records: Sequence[Mapping[str, Any]],
    *,
    threshold: float = NEAR_DUPLICATE_JACCARD_THRESHOLD,
) -> list[tuple[int, int, float]]:
    token_sets = [_request_tokens(record.get("request_text")) for record in records]
    pairs: list[tuple[int, int, float]] = []
    for left in range(len(records)):
        left_tokens = token_sets[left]
        if len(left_tokens) < 2:
            continue
        for right in range(left + 1, len(records)):
            if records[left].get("request_fingerprint") == records[right].get(
                "request_fingerprint"
            ):
                continue
            right_tokens = token_sets[right]
            if len(right_tokens) < 2:
                continue
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / len(union) if union else 0.0
            if similarity >= threshold:
                pairs.append((left, right, similarity))
    return pairs


_SEMANTIC_PHRASES = (
    (re.compile(r"(?i)\bapi\s+(?:route|endpoint)\b"), " endpoint "),
    (re.compile(r"(?i)\bweb\s+service\s+route\b"), " endpoint "),
    (re.compile(r"(?i)\bunit\s+tests?\b"), " test "),
    (re.compile(r"(?i)\btest\s+suite\b"), " test "),
    (re.compile(r"(?i)\bsource\s+tree\b"), " repository "),
    (re.compile(r"(?i)\bcode\s*base\b"), " repository "),
)
_SEMANTIC_CONCEPTS = {
    "repair": "fix",
    "correct": "fix",
    "resolve": "fix",
    "mend": "fix",
    "broken": "fix",
    "buggy": "fix",
    "route": "endpoint",
    "handler": "endpoint",
    "api": "endpoint",
    "repo": "repository",
    "project": "repository",
    "codebase": "repository",
    "inspect": "examine",
    "review": "examine",
    "check": "examine",
    "investigate": "examine",
    "verify": "validate",
    "confirm": "validate",
    "testing": "test",
    "tests": "test",
    "builds": "build",
    "compile": "build",
    "latest": "current",
    "recent": "current",
    "newest": "current",
    "lookup": "research",
    "search": "research",
    "retrieve": "research",
}
_SEMANTIC_STOPWORDS = frozenset({
    "a", "an", "and", "are", "be", "can", "could", "for", "from", "i", "in",
    "is", "it", "of", "on", "please", "that", "the", "this", "to", "we", "with",
    "would", "you",
})


def _semantic_tokens(value: Any) -> frozenset[str]:
    text = " ".join(str(value).lower().split())[:32_000]
    for pattern, replacement in _SEMANTIC_PHRASES:
        text = pattern.sub(replacement, text)
    tokens = [
        _SEMANTIC_CONCEPTS.get(token, token)
        for token in _NEAR_DUPLICATE_TOKEN.findall(text)[:256]
        if len(token) > 1 and token not in _SEMANTIC_STOPWORDS
    ]
    return frozenset(tokens)


def _semantic_duplicate_pairs(
    records: Sequence[Mapping[str, Any]],
    *,
    threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
    lexical_pairs: Sequence[tuple[int, int, float]] | None = None,
) -> list[tuple[int, int, float]]:
    """Find deterministic concept-level paraphrases missed by lexical Jaccard."""
    representations = [_semantic_tokens(record.get("request_text")) for record in records]
    lexical = {
        (left, right)
        for left, right, _score in (
            _near_duplicate_pairs(records) if lexical_pairs is None else lexical_pairs
        )
    }
    pairs: list[tuple[int, int, float]] = []
    for left in range(len(records)):
        left_terms = representations[left]
        if len(left_terms) < 2:
            continue
        for right in range(left + 1, len(records)):
            if (left, right) in lexical:
                continue
            if records[left].get("request_fingerprint") == records[right].get(
                "request_fingerprint"
            ):
                continue
            right_terms = representations[right]
            if len(right_terms) < 2:
                continue
            union = left_terms | right_terms
            similarity = len(left_terms & right_terms) / len(union) if union else 0.0
            if similarity >= threshold:
                pairs.append((left, right, similarity))
    return pairs


def _target_counts(total: int) -> dict[str, int]:
    validation = max(1, round(total * 0.15)) if total >= 3 else 0
    test = max(1, round(total * 0.15)) if total >= 3 else 0
    if validation + test >= total:
        test = max(0, total - validation - 1)
    return {"train": total - validation - test, "validation": validation, "test": test}


def _stratified_group_splits(
    records: Sequence[Mapping[str, Any]],
    *,
    frozen_assignments: Mapping[str, str] | None = None,
) -> dict[str, str]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["component_fingerprint"]), []).append(record)
    assignments: dict[str, str] = dict(frozen_assignments or {})
    strata: dict[str, list[tuple[str, list[Mapping[str, Any]]]]] = {}
    for group, members in grouped.items():
        hints = {
            str(member.get("split_hint")) for member in members
            if member.get("split_hint") in {"train", "validation", "test"}
        }
        if len(hints) > 1:
            raise ValueError("connected component has conflicting explicit split hints")
        if hints:
            hinted = next(iter(hints))
            if group in assignments and assignments[group] != hinted:
                raise ValueError(
                    "connected component conflicts with a frozen split assignment"
                )
            assignments[group] = hinted
            continue
        sources = {
            str(member.get("label_source")) for member in members
            if member.get("label") in {"DIRECT", "DELEGATE"}
        }
        if sources and sources <= {"silver"}:
            assignments[group] = "train"
            continue
        labels = Counter(
            str(member["label"])
            for member in members
            if member.get("label") in {"DIRECT", "DELEGATE"}
        )
        if not labels:
            assignments[group] = _split(group)
            continue
        stratum = labels.most_common(1)[0][0]
        strata.setdefault(stratum, []).append((group, members))
    for stratum, groups in strata.items():
        groups = [item for item in groups if item[0] not in assignments]
        groups.sort(key=lambda item: hashlib.sha256(
            f"{stratum}:{item[0]}".encode("utf-8")
        ).hexdigest())
        label_total = sum(
            sum(member.get("label") == stratum for member in members)
            for _group, members in groups
        )
        targets = _target_counts(label_total)
        current = Counter()
        for group, members in groups:
            weight = sum(member.get("label") == stratum for member in members)
            candidates = sorted(
                targets,
                key=lambda split: (
                    (current[split] + weight) / max(1, targets[split]),
                    current[split] - targets[split],
                    {"train": 0, "validation": 1, "test": 2}[split],
                ),
            )
            selected = candidates[0]
            assignments[group] = selected
            current[selected] += weight
    return assignments


def _chronological_blind_group_splits(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Create one global temporal boundary only when blind chronology is credible."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        if (
            row.get("labeling_method") == "blind_human_review_v2"
            and row.get("label") in {"DIRECT", "DELEGATE"}
        ):
            grouped.setdefault(str(row["component_fingerprint"]), []).append(row)
    ordered: list[tuple[dt.datetime, str, str]] = []
    for group, members in grouped.items():
        timestamps = [
            _parse_time(str(row.get("created_at") or "")) for row in members
        ]
        if not timestamps or any(value is None for value in timestamps):
            return {}
        labels = {str(row["label"]) for row in members}
        if len(labels) != 1:
            continue
        ordered.append((
            max(value for value in timestamps if value is not None),
            group,
            next(iter(labels)),
        ))
    ordered.sort(key=lambda item: (item[0], item[1]))
    if len(ordered) < 60:
        return {}
    train_end = int(len(ordered) * 0.70)
    validation_end = int(len(ordered) * 0.85)
    cohorts = {
        "train": ordered[:train_end],
        "validation": ordered[train_end:validation_end],
        "test": ordered[validation_end:],
    }
    if any(
        Counter(label for _timestamp, _group, label in members)[candidate] < minimum
        for split, members in cohorts.items()
        for candidate in ("DIRECT", "DELEGATE")
        for minimum in (
            10 if split == "train" else 4 if split == "test" else 1,
        )
    ):
        return {}
    return {
        group: split
        for split, members in cohorts.items()
        for _timestamp, group, _label in members
    }


def dataset_quality(
    rows: Sequence[Mapping[str, Any]],
    *,
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    policy = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    labeled = [row for row in rows if row.get("label") in {"DIRECT", "DELEGATE"}]
    real = [row for row in labeled if row.get("label_source") in REAL_LABEL_SOURCES]
    by_source: dict[str, list[Mapping[str, Any]]] = {
        source: [row for row in labeled if row.get("label_source") == source]
        for source in ("human_gold", "probe_gold", "silver")
    }
    source_priority = {"human_gold": 0, "probe_gold": 1, "silver": 2}
    usable_by_group: dict[str, Mapping[str, Any]] = {}
    for row in labeled:
        if not bool(row.get("label_independent")):
            continue
        group = str(row["group_fingerprint"])
        current = usable_by_group.get(group)
        if current is None or source_priority.get(
            str(row.get("label_source")), 9
        ) < source_priority.get(str(current.get("label_source")), 9):
            usable_by_group[group] = row
    independent_usable = list(usable_by_group.values())
    legacy_or_unproven = [
        row for row in labeled if not bool(row.get("label_independent"))
    ]
    usable_balance = Counter(str(row["label"]) for row in independent_usable)
    usable_split_balance = {
        split: dict(sorted(Counter(
            str(row["label"])
            for row in independent_usable if row.get("split") == split
        ).items()))
        for split in ("train", "validation", "test")
    }
    usable_task_categories = Counter(
        str(row.get("task_category") or "unknown") for row in independent_usable
    )
    usable_categories = Counter(
        str(row.get("category") or "unknown") for row in independent_usable
    )
    excluded = [
        row for row in rows
        if row.get("review_outcome") == "EXCLUDE"
        and row.get("source_kind") != "curated_benchmark"
    ]
    independent_real: list[Mapping[str, Any]] = []
    seen_groups: set[str] = set()
    for row in real:
        if not bool(row.get("label_independent", False)):
            continue
        group = str(row["group_fingerprint"])
        if group in seen_groups:
            continue
        seen_groups.add(group)
        independent_real.append(row)
    excluded_groups = {str(row["group_fingerprint"]) for row in excluded}
    real_balance = Counter(str(row["label"]) for row in independent_real)
    split_balance = {
        split: dict(sorted(Counter(
            str(row["label"]) for row in independent_real if row.get("split") == split
        ).items()))
        for split in ("train", "validation", "test")
    }
    categories = Counter(str(row.get("category") or "unknown") for row in independent_real)
    complexities = Counter(str(row.get("complexity") or "unknown") for row in independent_real)
    coding = Counter(
        "coding" if str(row.get("category") or "unknown") == "coding" else "non_coding"
        for row in independent_real
    )
    retrieval = Counter(
        "required" if bool(row.get("retrieval_required")) else "not_required"
        for row in independent_real
    )
    tool_requirement = Counter(
        "unknown" if row.get("tool_required") is None
        else "required" if bool(row.get("tool_required")) else "not_required"
        for row in independent_real
    )
    source_kinds = Counter(str(row.get("source_kind") or "unknown") for row in independent_real)
    entrypoints = Counter(str(row.get("entrypoint") or "unknown") for row in independent_real)
    providers = Counter(str(row.get("selected_provider") or "unknown") for row in independent_real)
    models = Counter(str(row.get("selected_model") or "unknown") for row in independent_real)
    group_labels: dict[str, set[str]] = {}
    for row in rows:
        candidate = row.get("reviewed_label") if row.get("label_conflict") else row.get("label")
        if candidate not in {"DIRECT", "DELEGATE"}:
            continue
        group_labels.setdefault(str(row["group_fingerprint"]), set()).add(str(candidate))
    conflicting_groups = sum(len(values) > 1 for values in group_labels.values())
    duplicate_rows = len(rows) - len({str(row["request_fingerprint"]) for row in rows})
    near_pairs = _near_duplicate_pairs(rows)
    semantic_pairs = _semantic_duplicate_pairs(rows, lexical_pairs=near_pairs)
    exact_splits: dict[str, set[str]] = {}
    for row in rows:
        exact_splits.setdefault(str(row["request_fingerprint"]), set()).add(
            str(row.get("split") or "unknown")
        )
    cross_split_exact = sum(len(values) > 1 for values in exact_splits.values())
    cross_split_near_pairs = sum(
        rows[left].get("split") != rows[right].get("split")
        for left, right, _similarity in near_pairs
    )
    cross_split_semantic_pairs = sum(
        rows[left].get("split") != rows[right].get("split")
        for left, right, _similarity in semantic_pairs
    )
    outcome_known = sum(row.get("outcome_success") is not None for row in independent_real)
    duplicate_stats = {
        "potentialNearDuplicatePairs": len(near_pairs),
        "potentialNearDuplicateCrossSplitPairs": cross_split_near_pairs,
        "semanticNearDuplicatePairs": len(semantic_pairs),
        "semanticNearDuplicateCrossSplitPairs": cross_split_semantic_pairs,
        "exactDuplicateCrossSplitFingerprints": cross_split_exact,
    }
    maturity_times = [
        parsed for parsed in (
            _parse_time(str(row.get("created_at") or "")) for row in rows
        )
        if parsed is not None
    ]
    # Dataset manifests are immutable.  Anchor the maturity snapshot to the
    # newest observed record rather than wall-clock time so repeating an
    # extraction produces byte-identical artifacts.  The standalone
    # ``data_maturity`` API accepts an explicit current time for live freshness
    # dashboards.
    maturity_now = max(maturity_times) if maturity_times else dt.datetime(
        1970, 1, 1, tzinfo=dt.timezone.utc
    )
    maturity = data_maturity(
        rows,
        thresholds=policy,
        now=maturity_now,
        duplicate_stats=duplicate_stats,
    )
    reasons: list[str] = list(maturity.get("blockingReasons") or ())
    requirements = policy.dataset_requirements()
    if len(independent_usable) < requirements["minimumIndependentUsableGroups"]:
        reasons.append(
            f"need at least {requirements['minimumIndependentUsableGroups']} independent usable "
            f"groups; found {len(independent_usable)}"
        )
    for label in ("DIRECT", "DELEGATE"):
        if usable_balance[label] < requirements["minimumIndependentUsableGroupsPerClass"]:
            reasons.append(
                f"need at least {requirements['minimumIndependentUsableGroupsPerClass']} "
                f"independent usable {label} groups; found {usable_balance[label]}"
            )
        for split, requirement_key in (
            ("validation", "minimumValidationPerClass"),
            ("test", "minimumTestPerClass"),
        ):
            minimum = requirements[requirement_key]
            count = usable_split_balance[split].get(label, 0)
            if count < minimum:
                reasons.append(
                    f"need at least {minimum} usable {label} labels in {split}; found {count}"
                )
    covered_categories = sum(
        count >= requirements["minimumUsableLabelsPerCategory"]
        for count in usable_task_categories.values()
    )
    if covered_categories < requirements["minimumCategories"]:
        reasons.append(
            f"need {requirements['minimumCategories']} categories with at least "
            f"{requirements['minimumUsableLabelsPerCategory']} usable groups; "
            f"found {covered_categories}"
        )
    dominant_category = (
        usable_categories.most_common(1)[0] if usable_categories else ("unknown", 0)
    )
    dominant_rate = (
        dominant_category[1] / len(independent_usable) if independent_usable else 0.0
    )
    if dominant_rate > requirements["maximumDominantCategoryRate"]:
        reasons.append(
            f"dominant category {dominant_category[0]} represents {dominant_rate:.6f} "
            f"of independent real groups; maximum is "
            f"{requirements['maximumDominantCategoryRate']:.2f}"
        )
    if cross_split_exact:
        reasons.append(
            f"found {cross_split_exact} exact duplicate fingerprints across splits"
        )
    if cross_split_near_pairs:
        reasons.append(
            f"found {cross_split_near_pairs} potential near-duplicate pairs across splits"
        )
    if cross_split_semantic_pairs:
        reasons.append(
            f"found {cross_split_semantic_pairs} semantic near-duplicate pairs across splits"
        )
    sparse_categories = dict(sorted(
        (name, count) for name, count in usable_task_categories.items()
        if count < requirements["minimumUsableLabelsPerCategory"]
    ))
    selection_bias = []
    if source_kinds:
        source_name, source_count = source_kinds.most_common(1)[0]
        if source_count / len(independent_real) > 0.60:
            selection_bias.append(
                f"source kind {source_name} represents "
                f"{source_count / len(independent_real):.6f} of independent real groups"
            )
    if coding["coding"] / len(independent_real) > 0.60 if independent_real else False:
        selection_bias.append("coding workloads exceed 60% of independent real groups")
    if complexities["unknown"]:
        selection_bias.append(
            f"{complexities['unknown']} independent real groups have unknown complexity"
        )
    model_input_failures: list[dict[str, str]] = []
    for row in independent_usable:
        try:
            projected = project_model_input(row)
        except (KeyError, TypeError, ValueError) as error:
            model_input_failures.append({
                "recordId": str(row.get("record_id") or "unknown"),
                "error": str(error),
            })
            continue
        findings = forbidden_payload_paths({
            key: value for key, value in projected.items() if key != "request_text"
        })
        if findings:
            model_input_failures.append({
                "recordId": str(row.get("record_id") or "unknown"),
                "error": f"forbidden projected paths: {findings}",
            })
    if model_input_failures:
        reasons.append(
            f"found {len(model_input_failures)} model-input projection failures"
        )
    timestamped = [
        row for row in independent_usable if _parse_time(str(row.get("created_at") or ""))
    ]
    timestamps = sorted(
        _parse_time(str(row.get("created_at") or ""))
        for row in timestamped
    )
    chronology = {
        "timestampedIndependentGroupCount": len(timestamped),
        "missingTimestampCount": len(independent_usable) - len(timestamped),
        "coverageRate": round(
            len(timestamped) / len(independent_usable), 6
        ) if independent_usable else 0.0,
        "earliestTimestamp": timestamps[0].isoformat() if timestamps else None,
        "latestTimestamp": timestamps[-1].isoformat() if timestamps else None,
    }
    independent_human_chronology = [
        row for row in independent_real
        if bool(row.get("label_independent"))
        and _parse_time(str(row.get("created_at") or ""))
    ]
    independent_human_chronology.sort(key=lambda row: (
        _parse_time(str(row.get("created_at") or "")),
        str(row.get("group_fingerprint") or row.get("record_id")),
    ))
    chronological_human_balance = Counter(
        str(row["label"]) for row in independent_human_chronology
    )
    chronology_cutoff = int(len(independent_human_chronology) * 0.70)
    chronological_train = independent_human_chronology[:chronology_cutoff]
    chronological_evaluation = independent_human_chronology[chronology_cutoff:]
    chronological_train_balance = Counter(str(row["label"]) for row in chronological_train)
    chronological_evaluation_balance = Counter(
        str(row["label"]) for row in chronological_evaluation
    )
    chronology["independenceProvenHumanGoldGroupCount"] = len(
        independent_human_chronology
    )
    chronology["independenceProvenHumanGoldClassBalance"] = dict(sorted(
        chronological_human_balance.items()
    ))
    chronology["chronologicalTrainingClassBalance"] = dict(sorted(
        chronological_train_balance.items()
    ))
    chronology["chronologicalEvaluationClassBalance"] = dict(sorted(
        chronological_evaluation_balance.items()
    ))
    chronology["chronologicalCutoffTimestamp"] = (
        str(chronological_evaluation[0].get("created_at") or "")
        if chronological_evaluation else None
    )
    split_timestamps = {
        split: sorted(
            _parse_time(str(row.get("created_at") or ""))
            for row in independent_human_chronology
            if row.get("split") == split
        )
        for split in ("train", "validation", "test")
    }
    split_temporal_order = bool(
        all(split_timestamps[split] for split in ("train", "validation", "test"))
        and split_timestamps["train"][-1] <= split_timestamps["validation"][0]
        and split_timestamps["validation"][-1] <= split_timestamps["test"][0]
    )
    chronology["splitTemporalOrder"] = split_temporal_order
    chronology["credibleHumanGoldChronology"] = (
        len(independent_human_chronology) >= 60
        and all(chronological_train_balance[label] >= 10 for label in ("DIRECT", "DELEGATE"))
        and all(chronological_evaluation_balance[label] >= 10 for label in ("DIRECT", "DELEGATE"))
        and split_temporal_order
    )
    if not chronology["credibleHumanGoldChronology"]:
        reasons.append(
            "chronological independent human-gold evaluation is not yet credible"
        )
    human_gold_ready = bool(
        chronology["credibleHumanGoldChronology"]
        and all(chronological_human_balance[label] > 0 for label in ("DIRECT", "DELEGATE"))
    )
    candidate_gates = {
        "independentUsableGroups": len(independent_usable) >= requirements[
            "minimumIndependentUsableGroups"
        ],
        "directGroups": usable_balance["DIRECT"] >= requirements[
            "minimumIndependentUsableGroupsPerClass"
        ],
        "delegateGroups": usable_balance["DELEGATE"] >= requirements[
            "minimumIndependentUsableGroupsPerClass"
        ],
        "validationPerClass": all(
            usable_split_balance["validation"].get(label, 0)
            >= requirements["minimumValidationPerClass"]
            for label in ("DIRECT", "DELEGATE")
        ),
        "testPerClass": all(
            usable_split_balance["test"].get(label, 0)
            >= requirements["minimumTestPerClass"]
            for label in ("DIRECT", "DELEGATE")
        ),
        "categoryCoverage": covered_categories >= requirements["minimumCategories"],
        "blindHumanGoldBothClasses": all(
            chronological_human_balance[label] > 0 for label in ("DIRECT", "DELEGATE")
        ),
        "credibleChronology": bool(chronology["credibleHumanGoldChronology"]),
        "zeroDecisionOutcomeLeakage": not model_input_failures,
        "zeroCrossSplitContamination": not (
            cross_split_exact or cross_split_near_pairs or cross_split_semantic_pairs
        ),
        "featureSchemaFrozen": True,
        "labelCompleteness": bool(
            maturity.get("candidateGates", {}).get("labelCompleteness")
        ),
        "classBalance": bool(maturity.get("candidateGates", {}).get("classBalance")),
        "featureCoverage": bool(
            maturity.get("candidateGates", {}).get("featureCoverage")
        ),
        "zeroLeakageRejections": bool(
            maturity.get("candidateGates", {}).get("zeroLeakageRejections")
        ),
    }
    # Promotion reporting consumes the same historical gate names as the
    # dataset-quality report.  Merge them into the maturity snapshot so the
    # standalone readiness report does not mistake an omitted measurement for
    # a hidden pass/fail state.
    maturity["candidateGates"] = dict(maturity.get("candidateGates") or {}) | candidate_gates
    reasons = list(dict.fromkeys(reasons))
    return {
        "status": "READY" if not reasons else "BLOCKED_BY_DATA",
        "requirements": dict(requirements),
        "reasons": reasons,
        "totalGroupCount": len({str(row["group_fingerprint"]) for row in rows}),
        "verifiedLabelCount": len(labeled),
        "independenceProvenLabelCount": sum(
            bool(row.get("label_independent")) for row in labeled
        ),
        "legacyOrUnprovenLabelCount": len(legacy_or_unproven),
        "usableIndependentGroupCount": len(independent_usable),
        "usableIndependentClassBalance": dict(sorted(Counter(
            str(row["label"]) for row in independent_usable
        ).items())),
        "usableIndependentSplitClassBalance": usable_split_balance,
        "usableIndependentTaskCategoryBalance": dict(sorted(
            usable_task_categories.items()
        )),
        "usableIndependentCategoryBalance": dict(sorted(Counter(
            str(row.get("category") or "unknown") for row in independent_usable
        ).items())),
        "usableIndependentComplexityBalance": dict(sorted(Counter(
            str(row.get("complexity") or "unknown") for row in independent_usable
        ).items())),
        "usableIndependentRetrievalRequirementBalance": dict(sorted(Counter(
            "required" if bool(row.get("retrieval_required")) else "not_required"
            for row in independent_usable
        ).items())),
        "usableIndependentToolRequirementBalance": dict(sorted(Counter(
            "required" if bool(row.get("tool_required")) else "not_required"
            for row in independent_usable
        ).items())),
        "labelSourceCounts": {
            source: len(values) for source, values in by_source.items()
        } | {"excluded": sum(row.get("label_source") == "excluded" for row in rows)},
        "independentGroupsByLabelSource": {
            source: len({str(row["group_fingerprint"]) for row in values})
            for source, values in by_source.items()
        },
        "independenceProvenGroupsByLabelSource": {
            source: len({
                str(row["group_fingerprint"])
                for row in independent_usable
                if row.get("label_source") == source
            })
            for source in ("human_gold", "probe_gold", "silver")
        },
        "labelingMethodCounts": dict(sorted(Counter(
            str(row.get("labeling_method") or "unknown") for row in labeled
        ).items())),
        "classBalanceByLabelSource": {
            source: dict(sorted(Counter(str(row["label"]) for row in values).items()))
            for source, values in by_source.items()
        },
        "reviewedRealLabelCount": len(real),
        "reviewedRealIndependentGroupCount": len(independent_real),
        "excludedAmbiguousIndependentGroupCount": len(excluded_groups),
        "reviewedRealClassBalance": dict(sorted(real_balance.items())),
        "reviewedRealSplitClassBalance": split_balance,
        "reviewedRealCategoryBalance": dict(sorted(categories.items())),
        "reviewedRealComplexityBalance": dict(sorted(complexities.items())),
        "reviewedRealCodingBalance": dict(sorted(coding.items())),
        "reviewedRealRetrievalRequirementBalance": dict(sorted(retrieval.items())),
        "reviewedRealToolRequirementBalance": dict(sorted(tool_requirement.items())),
        "reviewedRealSourceKindBalance": dict(sorted(source_kinds.items())),
        "reviewedRealEntrypointBalance": dict(sorted(entrypoints.items())),
        "reviewedRealProviderBalance": dict(sorted(providers.items())),
        "reviewedRealModelBalance": dict(sorted(models.items())),
        "sparseCategories": sparse_categories,
        "dominantCategory": {
            "category": dominant_category[0],
            "count": dominant_category[1],
            "rate": round(dominant_rate, 6),
        },
        "missingComplexityCount": complexities["unknown"],
        "selectionBiasWarnings": selection_bias,
        "reviewedRealOutcomeCoverage": {
            "known": outcome_known,
            "unknown": len(independent_real) - outcome_known,
            "rate": round(outcome_known / len(independent_real), 6) if independent_real else 0.0,
        },
        "duplicateRequestRows": duplicate_rows,
        "duplicateRowsCollapsedForModeling": (
            sum(bool(row.get("label_independent")) for row in labeled)
            - len(independent_usable)
        ),
        "duplicateRequestRate": round(duplicate_rows / len(rows), 6) if rows else 0.0,
        "potentialNearDuplicatePairs": len(near_pairs),
        "nearDuplicateJaccardThreshold": NEAR_DUPLICATE_JACCARD_THRESHOLD,
        "potentialNearDuplicateCrossSplitPairs": cross_split_near_pairs,
        "exactDuplicateCrossSplitFingerprints": cross_split_exact,
        "semanticNearDuplicatePairs": len(semantic_pairs),
        "semanticNearDuplicateThreshold": SEMANTIC_DUPLICATE_THRESHOLD,
        "semanticRepresentationVersion": SEMANTIC_REPRESENTATION_VERSION,
        "semanticNearDuplicateCrossSplitPairs": cross_split_semantic_pairs,
        "crossSplitContaminationPrevented": len(near_pairs) + len(semantic_pairs),
        "conflictingLabelGroups": conflicting_groups,
        "quarantinedConflictGroupCount": conflicting_groups,
        "chronologicalCoverage": chronology,
        "humanGoldReady": human_gold_ready,
        "humanGoldReadyStatement": f"HUMAN GOLD READY: {'YES' if human_gold_ready else 'NO'}",
        "candidateGates": candidate_gates,
        "labelQualityAudit": {
            "excludedAmbiguousRows": len(excluded),
            "excludedAmbiguousIndependentGroups": len(excluded_groups),
            "conflictingLabelGroups": conflicting_groups,
            "duplicateRequestRows": duplicate_rows,
            "potentialNearDuplicatePairs": len(near_pairs),
            "potentialNearDuplicateCrossSplitPairs": cross_split_near_pairs,
            "semanticNearDuplicatePairs": len(semantic_pairs),
            "semanticNearDuplicateCrossSplitPairs": cross_split_semantic_pairs,
            "suspiciousRepeatedPatternCount": (
                len(near_pairs) + len(semantic_pairs) + duplicate_rows
            ),
        },
        "futureInformationLeakage": {
            "passed": not model_input_failures,
            "featureAudit": feature_audit(),
            "defaultFeatureSet": "safe_metadata",
            "projectedInputFailureCount": len(model_input_failures),
            "projectedInputFailures": model_input_failures[:20],
            "rawPostDecisionEvidenceExcludedBeforeModeling": True,
        },
        "dataMaturity": maturity,
    }


def _atomic_lines(path: pathlib.Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        for row in rows
    )
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"immutable dataset artifact is not a regular file: {path}")
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"immutable dataset artifact differs from existing file: {path}")
        os.chmod(path, 0o600)
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def load_dataset(path: pathlib.Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise ValueError("dataset must not be a symbolic link")
    if path.stat().st_size > 100_000_000:
        raise ValueError("dataset exceeds 100 MB")
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"dataset line {line_number} is not an object")
        if value.get("schema_version") not in SUPPORTED_DATASET_SCHEMA_VERSIONS:
            raise ValueError(f"dataset line {line_number} has an incompatible schema version")
        if value.get("feature_version") not in {
            FEATURE_SCHEMA_VERSION,
            "direct-delegate-features-v1",
        }:
            raise ValueError(f"dataset line {line_number} has an incompatible feature version")
        identifier = value.get("record_id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError(f"dataset line {line_number} has an invalid or duplicate record id")
        identifiers.add(identifier)
        if value.get("split") not in {"train", "validation", "test"}:
            raise ValueError(f"dataset line {line_number} has an invalid split")
        if value.get("label") not in {None, "DIRECT", "DELEGATE"}:
            raise ValueError(f"dataset line {line_number} has an invalid label")
        if value.get("schema_version") == DATASET_SCHEMA_VERSION and value.get(
            "label_source"
        ) not in {"human_gold", "probe_gold", "silver", "excluded"}:
            raise ValueError(f"dataset line {line_number} has an invalid label source")
        if value.get("schema_version") == DATASET_SCHEMA_VERSION:
            if not isinstance(value.get("labeling_method"), str):
                raise ValueError(
                    f"dataset line {line_number} is missing labeling method provenance"
                )
            if not isinstance(value.get("label_independent"), bool):
                raise ValueError(
                    f"dataset line {line_number} is missing independence provenance"
                )
            if value.get("label") in {"DIRECT", "DELEGATE"} and not isinstance(
                value.get("label_confidence"), (int, float)
            ):
                raise ValueError(
                    f"dataset line {line_number} is missing label confidence"
                )
            provenance = value.get("feature_provenance")
            if provenance not in {"text_recomputed_v2", "probe_contract_v2"}:
                raise ValueError(
                    f"dataset line {line_number} has invalid feature provenance"
                )
            if provenance == "text_recomputed_v2":
                reconstructed = decision_profile(str(value.get("request_text") or ""))
                for field in (
                    "repository_required", "retrieval_required", "tool_required",
                    "current_information_required", "execution_required",
                    "modification_required", "verification_required",
                    "multi_step_required", "complexity", "category", "task_category",
                ):
                    if value.get(field) != reconstructed[field]:
                        raise ValueError(
                            f"dataset line {line_number} has non-reproducible "
                            f"decision-time feature {field}"
                        )
            elif (
                value.get("source_kind") not in {"probe_gold", "curated_benchmark"}
                or value.get("production_decision") is not None
                or bool(value.get("decision_applied"))
            ):
                raise ValueError(
                    f"dataset line {line_number} has an invalid probe feature contract"
                )
        request = value.get("request_text")
        if not isinstance(request, str) or len(request) > 32_000:
            raise ValueError(f"dataset line {line_number} has invalid request text")
        rows.append(value)
    return rows


def dataset_identity(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    canonical = json.dumps(list(rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"dd-dataset-{digest[:16]}", digest


def validate_dataset_identity(path: pathlib.Path, rows: Sequence[Mapping[str, Any]]) -> str:
    version, _digest = dataset_identity(rows)
    if path.stem != version:
        raise ValueError(
            f"dataset content version mismatch: expected {version}, found {path.stem}"
        )
    return version


def _authoritative_prior_splits(output_directory: pathlib.Path) -> dict[str, str]:
    """Freeze previously materialized membership before any evaluation rerun."""
    candidates = sorted(
        output_directory.glob("dd-dataset-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        manifest_path = path.with_suffix(".manifest.json")
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest_payload, dict) or (
            manifest_payload.get("quality", {}).get("status") != "READY"
        ):
            continue
        mapping: dict[str, str] = {}
        compatible = False
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    mapping = {}
                    break
                if row.get("schema_version") != DATASET_SCHEMA_VERSION:
                    mapping = {}
                    break
                compatible = True
                fingerprint = row.get("request_fingerprint")
                split = row.get("split")
                if isinstance(fingerprint, str) and split in {
                    "train", "validation", "test"
                }:
                    mapping[fingerprint] = str(split)
        except (OSError, json.JSONDecodeError):
            continue
        if compatible and mapping:
            return mapping
    return {}


class DatasetBuilder:
    """Build ML datasets while leaving TaskStore as execution source of truth."""

    def __init__(self, store: IntelligenceStore) -> None:
        self.store = store

    def sync_task_history(self, task_store_path: pathlib.Path) -> dict[str, int]:
        """Sanitize and project durable runs into the separate evidence store."""
        if not task_store_path.is_file():
            return {"scanned": 0, "created": 0, "updated": 0, "skipped": 0}
        connection = sqlite3.connect(f"file:{task_store_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        counters = Counter(scanned=0, created=0, updated=0, skipped=0)
        try:
            tasks = connection.execute("SELECT * FROM tasks ORDER BY created_at, task_id")
            for task in tasks:
                counters["scanned"] += 1
                private = _decode(task["private_payload_json"])
                display = _decode(task["display_metadata_json"])
                prompt = str(private.get("prompt") or "")
                if not prompt.strip():
                    counters["skipped"] += 1
                    continue
                routing = private.get("routing") if isinstance(private.get("routing"), dict) else {}
                profile = routing.get("task_profile") if isinstance(routing.get("task_profile"), dict) else {}
                if not profile:
                    profile = profile_task(prompt).to_dict()
                delegation = private.get("delegation") if isinstance(private.get("delegation"), dict) else {}
                pre_routing_input = (
                    private.get("preRoutingInput")
                    if isinstance(private.get("preRoutingInput"), dict) else {}
                )
                logical_session = str(private.get("logicalSessionId") or task["task_id"])
                group = hashlib.sha256(logical_session.encode("utf-8")).hexdigest()
                existing = self.store.record_for_task(str(task["task_id"]))
                deterministic_record_id = "task_" + hashlib.sha256(
                    str(task["task_id"]).encode("utf-8")
                ).hexdigest()[:24]
                if existing and existing["source_kind"] != "historical_task":
                    record_id = str(existing["record_id"])
                else:
                    record_id = record_routing_telemetry(
                        self.store.path,
                        request=prompt,
                        production_decision="DELEGATE",
                        routing_reason=(
                            str(delegation.get("reason"))
                            if delegation.get("decision") == "DELEGATE"
                            else "durable_execution_entrypoint"
                        ),
                        production_confidence=(
                            float(delegation["confidence"])
                            if isinstance(delegation.get("confidence"), (int, float)) else None
                        ),
                        selected_worker=str(task["agent"]),
                        selected_model=display.get("effectiveModelRoute") or display.get("modelRoute"),
                        selected_provider=display.get("actualProvider") or (
                            "omniroute" if task["agent"] == "codex" else "pi"
                        ),
                        selected_account=private.get("accountId"),
                        project=pathlib.Path(str(task["project_path"])),
                        repository_present=bool(pre_routing_input.get("repositoryPresent")),
                        profile=profile,
                        source_task_id=str(task["task_id"]),
                        source_kind="historical_task",
                        record_id=(str(existing["record_id"]) if existing else deterministic_record_id),
                        entrypoint=str(private.get("mode") or task["workflow"]),
                        decision_applied=delegation.get("decision") == "DELEGATE",
                        run_shadow=False,
                        group_fingerprint=group,
                        alternatives=(),
                        created_at=str(task["created_at"]),
                    )
                if not record_id:
                    counters["skipped"] += 1
                    continue
                counters["updated" if existing else "created"] += 1
                runs = connection.execute(
                    "SELECT * FROM runs WHERE task_id = ? ORDER BY attempt",
                    (task["task_id"],),
                ).fetchall()
                latest = runs[-1] if runs else None
                events = connection.execute(
                    """SELECT * FROM (
                           SELECT * FROM events WHERE task_id = ?
                           ORDER BY sequence DESC LIMIT 1000
                       ) ORDER BY sequence""",
                    (task["task_id"],),
                ).fetchall()
                steps = connection.execute(
                    "SELECT name,state FROM steps WHERE task_id = ? ORDER BY position",
                    (task["task_id"],),
                ).fetchall()
                validation_status = None
                retrieval_used = False
                chunk_ids: list[str] = []
                fallback_used = None
                input_tokens = None
                output_tokens = None
                context_tokens = None
                tools = [f"agent.{task['agent']}"]
                context_failure = None
                for event in events:
                    payload = _decode(event["display_payload_json"])
                    if event["event_type"] == "validation.completed":
                        validation_status = payload.get("status")
                    elif event["event_type"] == "context.assembled":
                        if isinstance(payload.get("finalRequestTokens"), int):
                            context_tokens = max(0, int(payload["finalRequestTokens"]))
                        retrieved = payload.get("retrievedContext")
                        if isinstance(retrieved, dict):
                            retrieval_used = int(retrieved.get("selectedChunks", 0) or 0) > 0
                            methods = retrieved.get("methods")
                            if isinstance(methods, list):
                                tools.extend(f"retrieval.{method}" for method in methods)
                            values = retrieved.get("selectedChunkIds")
                            if isinstance(values, list):
                                chunk_ids = [str(item) for item in values[:100]]
                            if retrieved.get("failureClassification"):
                                context_failure = str(retrieved["failureClassification"])
                    elif event["event_type"] == "routing.omniroute_selected":
                        fallback_used = bool(payload.get("fallbackUsed"))
                    elif event["event_type"] == "delegation.worker_usage":
                        input_tokens = int(payload.get("inputTokens", 0) or 0)
                        output_tokens = int(payload.get("outputTokens", 0) or 0)
                test_states = [str(row["state"]) for row in steps if "test" in str(row["name"]).lower()]
                build_states = [str(row["state"]) for row in steps if "build" in str(row["name"]).lower()]
                terminal_state = str(task["state"])
                terminal_failures = {"failed", "cancelled", "timed_out", "interrupted"}
                success = (
                    True if terminal_state == "succeeded"
                    else False if terminal_state in terminal_failures
                    else None
                )
                update_execution_telemetry(self.store.path, record_id, {
                    "selected_worker": str(task["agent"]),
                    "selected_model": display.get("actualModel") or display.get("effectiveModelRoute"),
                    "selected_provider": display.get("actualProvider") or (
                        "omniroute" if task["agent"] == "codex" else "pi"
                    ),
                    "selected_account": private.get("accountId"),
                    "context_tokens": context_tokens,
                    "retrieval_used": retrieval_used,
                    "retrieved_chunk_ids": chunk_ids,
                    "tools": tools,
                    "retries": max(0, len(runs) - 1),
                    "fallback_used": fallback_used,
                    "execution_time_ms": (
                        _duration_ms(latest["started_at"], latest["completed_at"])
                        if latest else None
                    ),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "failure_category": (
                        task["terminal_code"] if success is False else context_failure
                    ),
                    "success": success,
                    "validation_status": validation_status,
                    "test_status": (
                        "Passed" if test_states and all(state == "passed" for state in test_states)
                        else "Failed" if any(state == "failed" for state in test_states)
                        else "Not Run"
                    ),
                    "build_status": (
                        "Passed" if build_states and all(state == "passed" for state in build_states)
                        else "Failed" if any(state == "failed" for state in build_states)
                        else "Not Run"
                    ),
                    "evaluator_result": validation_status,
                    "retry_outcome": terminal_state if len(runs) > 1 else "not_attempted",
                })
        finally:
            connection.close()
        return dict(counters)

    def import_curated(self, path: pathlib.Path) -> dict[str, int]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        examples = payload.get("examples") if isinstance(payload, dict) else None
        if not isinstance(examples, list):
            raise ValueError("curated label file must contain an examples list")
        created = 0
        for index, example in enumerate(examples):
            if not isinstance(example, dict):
                raise ValueError(f"curated example {index} is not an object")
            request = example.get("request")
            label = example.get("label")
            if not isinstance(request, str) or label not in {"DIRECT", "DELEGATE"}:
                raise ValueError(f"curated example {index} has invalid request or label")
            safe, redacted = sanitize_request(request)
            fingerprint = request_fingerprint(safe)
            record_id = f"curated_{fingerprint[:24]}"
            profile = example.get("features") if isinstance(example.get("features"), dict) else {}
            safe_features = decision_profile(safe, profile)
            self.store.record_routing({
                "record_id": record_id,
                "source_kind": "curated_benchmark",
                "source_task_id": None,
                "entrypoint": "curated_benchmark",
                "decision_applied": False,
                "request_text": safe,
                "request_fingerprint": fingerprint,
                "group_fingerprint": fingerprint,
                "request_redacted": redacted,
                "request_length": len(safe),
                "estimated_tokens": (len(safe) + 3) // 4,
                "task_type": str(profile.get("task_type") or "unknown"),
                "complexity": safe_features["complexity"],
                "category": safe_features["category"],
                "task_category": safe_features["task_category"],
                "repository_present": bool(profile.get("repository_present")),
                "project_fingerprint": None,
                "repository_required": safe_features["repository_required"],
                "retrieval_required": safe_features["retrieval_required"],
                "tool_required": safe_features["tool_required"],
                "current_information_required": safe_features[
                    "current_information_required"
                ],
                "execution_required": safe_features["execution_required"],
                "modification_required": safe_features["modification_required"],
                "verification_required": safe_features["verification_required"],
                "multi_step_required": safe_features["multi_step_required"],
                "context_tokens": int(profile.get("context_tokens", 0) or 0),
                "production_decision": None,
                "routing_reason": "curated_ground_truth_only",
            })
            self.store.label_record(
                record_id,
                str(label),
                source="curated_benchmark",
                notes=str(example.get("rationale") or "")[:2_000],
            )
            created += 1
        return {"imported": created}

    def extract(self, output_directory: pathlib.Path) -> dict[str, Any]:
        output_directory = output_directory.expanduser().resolve(strict=False)
        prior_splits = _authoritative_prior_splits(output_directory)
        records = self.store.list_records()
        labels = {row["record_id"]: row for row in self.store.labeled_records()}
        reviews = self.store.latest_reviews()
        blind_resolutions = self.store.blind_human_resolutions()
        parents = list(range(len(records)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        owners: dict[str, int] = {}
        for index, record in enumerate(records):
            for key in (
                f"request:{record['request_fingerprint']}",
                f"session:{record['group_fingerprint']}",
            ):
                if key in owners:
                    union(index, owners[key])
                else:
                    owners[key] = index
        near_pairs = _near_duplicate_pairs(records)
        for left, right, _similarity in near_pairs:
            union(left, right)
        for left, right, _similarity in _semantic_duplicate_pairs(
            records, lexical_pairs=near_pairs
        ):
            union(left, right)
        component_keys: dict[int, list[str]] = {}
        for index, record in enumerate(records):
            component_keys.setdefault(find(index), []).extend((
                f"request:{record['request_fingerprint']}",
                f"session:{record['group_fingerprint']}",
            ))
        component_fingerprints = {
            root: hashlib.sha256("|".join(sorted(set(keys))).encode("utf-8")).hexdigest()
            for root, keys in component_keys.items()
        }
        prepared: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            group = component_fingerprints[find(index)]
            label = labels.get(record["record_id"])
            review = reviews.get(record["record_id"])
            blind_resolution = blind_resolutions.get(record["record_id"])
            safe_features = decision_profile(
                record["request_text"],
                record if record.get("source_kind") in {
                    "probe_gold", "curated_benchmark"
                } else None,
            )
            source = (
                "human_gold"
                if blind_resolution is not None
                else canonical_label_source(
                    label.get("label_source") if label else None,
                    excluded=bool(review and review.get("outcome") == "EXCLUDE"),
                )
            )
            labeling_method = (
                "blind_human_review_v2"
                if blind_resolution is not None
                else str(
                    label.get("labeling_method") if label else "excluded_or_unlabeled"
                )
            )
            independent = label_is_independent(source, labeling_method)
            accepted_label = (
                str(blind_resolution["label"])
                if blind_resolution is not None
                else label.get("verified_label") if label else None
            )
            prepared.append({
                "component_fingerprint": group,
                "schema_version": DATASET_SCHEMA_VERSION,
                "feature_version": FEATURE_SCHEMA_VERSION,
                "feature_provenance": (
                    "probe_contract_v2"
                    if record.get("source_kind") in {"probe_gold", "curated_benchmark"}
                    else "text_recomputed_v2"
                ),
                "record_id": record["record_id"],
                "source_kind": record["source_kind"],
                "entrypoint": record["entrypoint"],
                "decision_applied": record["decision_applied"],
                "request_text": record["request_text"],
                "request_fingerprint": record["request_fingerprint"],
                "group_fingerprint": group,
                "request_length": record["request_length"],
                "estimated_tokens": record["estimated_tokens"],
                "task_type": record["task_type"],
                "complexity": safe_features["complexity"],
                "category": safe_features["category"],
                "task_category": safe_features["task_category"],
                "repository_present": record["repository_present"],
                "repository_required": safe_features["repository_required"],
                "retrieval_required": safe_features["retrieval_required"],
                "tool_required": safe_features["tool_required"],
                "current_information_required": safe_features[
                    "current_information_required"
                ],
                "execution_required": safe_features["execution_required"],
                "modification_required": safe_features["modification_required"],
                "verification_required": safe_features["verification_required"],
                "multi_step_required": safe_features["multi_step_required"],
                "split_hint": (
                    record.get("split_hint")
                ),
                "context_tokens": record["context_tokens"],
                "production_decision": record["production_decision"],
                "selected_worker": record.get("selected_worker"),
                "selected_model": record.get("selected_model"),
                "selected_provider": record.get("selected_provider"),
                "selected_account": record.get("selected_account"),
                "tools": list(record.get("tools") or ()),
                "retrieval_used": record.get("retrieval_used"),
                "ml_prediction": record["ml_prediction"],
                "ml_confidence": record["ml_confidence"],
                "outcome_success": record["success"],
                "validation_status": record["validation_status"],
                "failure_category": record["failure_category"],
                "created_at": record.get("created_at"),
                "label": accepted_label,
                "label_source": source,
                "label_trust": source,
                "label_confidence": (
                    1.0
                    if blind_resolution is not None
                    else float(label.get("label_confidence", 1.0)) if label else None
                ),
                "labeling_method": labeling_method,
                "label_independent": independent,
                "exclusion_reason": (
                    str(review.get("notes") or review.get("outcome"))
                    if review and review.get("outcome") == "EXCLUDE" else None
                ),
                "reviewed_label": accepted_label,
                "reviewed_label_source": (
                    "human_gold"
                    if blind_resolution is not None
                    else label.get("label_source") if label else None
                ),
                "label_conflict": False,
                "review_outcome": review.get("outcome") if review else None,
                "review_status": review.get("review_status") if review else None,
                "reviewed_at": (
                    blind_resolution.get("created_at")
                    if blind_resolution is not None
                    else review.get("reviewed_at") if review else None
                ),
                "split": None,
            })
        component_labels: dict[str, set[str]] = {}
        for row in prepared:
            if row.get("label") in {"DIRECT", "DELEGATE"}:
                component_labels.setdefault(
                    str(row["component_fingerprint"]), set()
                ).add(str(row["label"]))
        conflicting_components = {
            component for component, values in component_labels.items()
            if len(values) > 1
        }
        for row in prepared:
            if str(row["component_fingerprint"]) not in conflicting_components:
                continue
            row["label_conflict"] = True
            row["label"] = None
            row["label_source"] = "excluded"
            row["label_trust"] = "excluded"
            row["label_independent"] = False
            row["exclusion_reason"] = "conflicting_labels_in_connected_component"
        frozen_assignments: dict[str, str] = {}
        for row in prepared:
            group = str(row["component_fingerprint"])
            prior = prior_splits.get(str(row["request_fingerprint"]))
            if prior is None:
                continue
            existing = frozen_assignments.get(group)
            if existing is not None and existing != prior:
                raise ValueError(
                    "semantic duplicate component crosses the frozen split manifest"
                )
            frozen_assignments[group] = prior
        chronological_assignments = _chronological_blind_group_splits(prepared)
        for group, split in chronological_assignments.items():
            existing = frozen_assignments.get(group)
            if existing is not None and existing != split:
                raise ValueError(
                    "chronological blind split conflicts with frozen final-test membership"
                )
            frozen_assignments[group] = split
        split_groups = _stratified_group_splits(
            prepared,
            frozen_assignments=frozen_assignments,
        )
        rows: list[dict[str, Any]] = []
        for row in prepared:
            row["split"] = split_groups[str(row.pop("component_fingerprint"))]
            rows.append(row)
        dataset_version, digest = dataset_identity(rows)
        dataset_path = output_directory / f"{dataset_version}.jsonl"
        manifest_path = output_directory / f"{dataset_version}.manifest.json"
        split_manifest_path = output_directory / f"{dataset_version}.splits.json"
        _atomic_lines(dataset_path, rows)
        split_manifest = {
            "schemaVersion": 1,
            "datasetVersion": dataset_version,
            "strategy": "connected_exact_lexical_semantic_group_stratified_70_15_15",
            "chronologicalBlindBoundaryApplied": bool(chronological_assignments),
            "assignments": [
                {
                    "groupFingerprint": group,
                    "split": split,
                }
                for group, split in sorted(split_groups.items())
            ],
        }
        split_manifest_digest = hashlib.sha256(
            json.dumps(
                split_manifest,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        split_manifest["contentSha256"] = split_manifest_digest
        _atomic_lines(split_manifest_path, [split_manifest])
        labeled = [row for row in rows if row["label"] is not None]
        quarantined_conflicts = [row for row in rows if row["label_conflict"]]
        quality = dataset_quality(rows)
        manifest = {
            "datasetVersion": dataset_version,
            "datasetSchemaVersion": DATASET_SCHEMA_VERSION,
            "featureVersion": FEATURE_SCHEMA_VERSION,
            "contentSha256": digest,
            "recordCount": len(rows),
            "labeledCount": len(labeled),
            "unlabeledCount": len(rows) - len(labeled),
            "quarantinedConflictRowCount": len(quarantined_conflicts),
            "classBalance": dict(sorted(Counter(row["label"] for row in labeled).items())),
            "splitCounts": dict(sorted(Counter(row["split"] for row in labeled).items())),
            "labelSources": dict(sorted(Counter(row["label_source"] for row in labeled).items())),
            "reviewOutcomeBalance": dict(sorted(Counter(
                str(row.get("review_outcome") or "pending") for row in rows
            ).items())),
            "splitClassBalance": {
                split: dict(sorted(Counter(
                    row["label"] for row in labeled if row["split"] == split
                ).items()))
                for split in ("train", "validation", "test")
            },
            "categoryBalance": dict(sorted(Counter(
                str(row.get("category") or "unknown") for row in labeled
            ).items())),
            "complexityBalance": dict(sorted(Counter(
                str(row.get("complexity") or "unknown") for row in labeled
            ).items())),
            "codingBalance": dict(sorted(Counter(
                "coding" if str(row.get("category") or "unknown") == "coding"
                else "non_coding" for row in labeled
            ).items())),
            "retrievalRequirementBalance": dict(sorted(Counter(
                "required" if bool(row.get("retrieval_required")) else "not_required"
                for row in labeled
            ).items())),
            "toolRequirementBalance": dict(sorted(Counter(
                "unknown" if row.get("tool_required") is None
                else "required" if bool(row.get("tool_required")) else "not_required"
                for row in labeled
            ).items())),
            "providerBalance": dict(sorted(Counter(
                str(row.get("selected_provider") or "unknown") for row in labeled
            ).items())),
            "modelBalance": dict(sorted(Counter(
                str(row.get("selected_model") or "unknown") for row in labeled
            ).items())),
            "productionDecisionBalance": dict(sorted(Counter(
                str(row.get("production_decision") or "UNKNOWN") for row in rows
            ).items())),
            "splitStrategy": (
                "connected_exact_lexical_semantic_group_stratified_70_15_15"
            ),
            "splitManifestFingerprint": split_manifest_digest,
            "splitManifestGroupCount": len(split_groups),
            "chronologicalBlindBoundaryApplied": bool(chronological_assignments),
            "splitManifestPath": str(split_manifest_path),
            "leakageGuard": (
                "identical, lexical-near, and deterministic semantic-near requests plus "
                "all linked session groups share one split; model features exclude "
                "post-decision evidence"
            ),
            "quality": quality,
            "datasetPath": str(dataset_path),
        }
        _atomic_lines(manifest_path, [manifest])
        self.store.save_dataset_manifest(dataset_version, manifest)
        return manifest | {"manifestPath": str(manifest_path)}
