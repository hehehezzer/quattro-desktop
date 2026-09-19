"""Independent, abstention-capable automatic labeling for silver evidence."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .features import decision_profile
from .store import IntelligenceStore

RUBRIC_VERSION = "silver-consensus-v1"

_DIRECT_CONTRACT = re.compile(
    r"(?i)\b(?:explain|define|summari[sz]e|compare|contrast|draft|rewrite|"
    r"brainstorm|describe|reason about|conceptual|pros and cons)\b"
)
_DELEGATE_CONTRACT = re.compile(
    r"(?i)\b(?:inspect|locate|find the (?:file|symbol|implementation)|implement|"
    r"modify|edit|patch|run (?:the )?(?:tests?|build|command)|execute|browse|"
    r"research (?:the )?(?:current|latest)|verify (?:the )?(?:current|live|actual)|"
    r"use (?:the )?(?:tool|terminal|browser)|check (?:the )?(?:repo|logs?|runtime))\b"
)
_DIRECT_BOUNDARY = re.compile(
    r"(?i)\b(?:without|no) (?:browsing|tools?|execution|repository inspection|"
    r"external sources?|current information)\b"
)


def _capability_judge(request: str) -> tuple[str | None, float]:
    features = decision_profile(request)
    hard = sum(bool(features[name]) for name in (
        "repository_required",
        "retrieval_required",
        "tool_required",
        "current_information_required",
        "execution_required",
        "modification_required",
        "verification_required",
    ))
    if hard >= 2 or features["modification_required"] or features["repository_required"]:
        return "DELEGATE", min(0.99, 0.86 + hard * 0.02)
    if features["direct_signal"] and hard == 0:
        return "DIRECT", 0.92
    return None, 0.0


def _contract_judge(request: str) -> tuple[str | None, float]:
    direct = bool(_DIRECT_CONTRACT.search(request))
    delegate = bool(_DELEGATE_CONTRACT.search(request))
    if delegate and not (direct and _DIRECT_BOUNDARY.search(request)):
        return "DELEGATE", 0.94
    if direct and not delegate:
        return "DIRECT", 0.91
    return None, 0.0


def _boundary_judge(request: str) -> tuple[str | None, float]:
    features = decision_profile(request)
    if _DIRECT_BOUNDARY.search(request) and not any(
        features[name] for name in (
            "repository_required", "current_information_required",
            "modification_required", "verification_required",
        )
    ):
        return "DIRECT", 0.96
    if (
        features["tool_required"]
        and features["execution_required"]
        and (_DELEGATE_CONTRACT.search(request) or features["multi_step_required"])
    ):
        return "DELEGATE", 0.93
    if features["direct_signal"] and not any(
        features[name] for name in (
            "repository_required", "retrieval_required", "tool_required",
            "current_information_required", "execution_required",
        )
    ):
        return "DIRECT", 0.90
    return None, 0.0


def judge_request(request: str) -> dict[str, Any]:
    """Return silver only for unanimous independent non-abstaining judges."""
    results = {
        "capability_rubric": _capability_judge(request),
        "task_contract": _contract_judge(request),
        "boundary_rubric": _boundary_judge(request),
    }
    labels = [label for label, _confidence in results.values() if label is not None]
    unanimous = len(labels) == len(results) and len(set(labels)) == 1
    confidence = min(
        (confidence for label, confidence in results.values() if label is not None),
        default=0.0,
    )
    return {
        "label": labels[0] if unanimous and confidence >= 0.90 else None,
        "confidence": round(confidence, 6) if unanimous else 0.0,
        "consensus": "unanimous" if unanimous else "uncertain",
        "judges": {
            name: {"label": label, "confidence": confidence}
            for name, (label, confidence) in results.items()
        },
    }


def auto_adjudicate_unlabeled(store: IntelligenceStore) -> dict[str, Any]:
    labels = {str(row["record_id"]) for row in store.labeled_records()}
    reviews = store.latest_reviews()
    promoted: Counter[str] = Counter()
    excluded = 0
    skipped = 0
    for record in store.list_records():
        record_id = str(record["record_id"])
        if record_id in labels or record_id in reviews:
            skipped += 1
            continue
        if record.get("source_kind") in {"probe_gold", "curated_benchmark"}:
            skipped += 1
            continue
        result = judge_request(str(record.get("request_text") or ""))
        store.record_adjudication_votes(
            record_id,
            rubric_version=RUBRIC_VERSION,
            request_fingerprint=str(record["request_fingerprint"]),
            votes=result["judges"],
        )
        label = result["label"]
        if label in {"DIRECT", "DELEGATE"}:
            store.label_record(
                record_id,
                label,
                source="silver",
                notes=(
                    "Unanimous decision-time consensus from three independent "
                    "abstention-capable rubrics; production routing was not an input."
                ),
                confidence=float(result["confidence"]),
                labeling_method="silver_consensus_v1",
            )
            promoted[label] += 1
        else:
            store.exclude_record(
                record_id,
                source="silver",
                notes="Excluded because automatic decision-time judges did not reach unanimity.",
            )
            excluded += 1
    return {
        "promoted": sum(promoted.values()),
        "promotedBalance": dict(sorted(promoted.items())),
        "excluded": excluded,
        "skipped": skipped,
        "policy": "three_independent_rubrics_unanimous_min_confidence_0.90",
        "rubricVersion": RUBRIC_VERSION,
    }


def quarantine_adjudication(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    components: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("label_conflict"):
            components.setdefault(str(row.get("group_fingerprint")), []).append(row)
    recovered = 0
    excluded = 0
    retained = 0
    reasons: Counter[str] = Counter()
    categories: dict[str, dict[str, Any]] = {}
    for members in components.values():
        human_labels = {
            str(row.get("reviewed_label")) for row in members
            if row.get("reviewed_label") in {"DIRECT", "DELEGATE"}
            and row.get("reviewed_label_source") in {
                "human_verified", "reviewed_outcome", "human_gold"
            }
        }
        consensus = {
            str(result["label"])
            for result in (judge_request(str(row.get("request_text") or "")) for row in members)
            if result["label"] in {"DIRECT", "DELEGATE"}
        }
        if len(human_labels) > 1:
            retained += len(members)
            reasons["conflicting_human_gold_is_immutable"] += len(members)
            categories["conflicting_human_gold"] = {
                "why": "connected component contains conflicting accepted human labels",
                "repairable": False,
                "provenanceProven": True,
                "safeFeaturesRecomputed": True,
                "disposition": "retained_quarantined",
                "rowCount": reasons["conflicting_human_gold_is_immutable"],
            }
        elif len(consensus) != 1:
            retained += len(members)
            reasons["automatic_consensus_uncertain"] += len(members)
        else:
            retained += len(members)
            reasons["component_linkage_requires_quarantine"] += len(members)
    uncertain_rows = [
        row for row in rows
        if row.get("review_outcome") == "EXCLUDE" and not row.get("label_conflict")
    ]
    if uncertain_rows:
        categories["uncertain_or_ambiguous"] = {
            "why": "independent review or adjudication abstained",
            "repairable": False,
            "provenanceProven": True,
            "safeFeaturesRecomputed": True,
            "disposition": "retained_excluded",
            "rowCount": len(uncertain_rows),
        }
    return {
        "componentCount": len(components),
        "recovered": recovered,
        "excluded": excluded,
        "stillQuarantined": retained,
        "reasons": dict(sorted(reasons.items())),
        "categories": categories,
        "dispositionCounts": {
            "restored": recovered,
            "retainedQuarantined": retained,
            "retainedExcluded": len(uncertain_rows),
        },
    }
