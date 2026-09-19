"""Blind human-gold review contract, sampling taxonomy, and agreement metrics."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .features import decision_profile, forbidden_payload_paths


RUBRIC_VERSION = "direct-delegate-human-rubric-v1"
BLIND_REVIEW_SCHEMA_VERSION = 1
BLIND_REVIEW_KIND = "quattro-intelligence-blind-review"
REVIEW_CHOICES = ("DIRECT", "DELEGATE", "UNCERTAIN", "SKIP")
REASON_CATEGORIES = (
    "answerable_from_request_context",
    "external_information_required",
    "repository_inspection_required",
    "modification_required",
    "execution_required",
    "verification_required",
    "multi_step_orchestration_required",
    "boundary_or_insufficient_context",
)
TARGET_CATEGORIES = (
    "conversational_trivial",
    "factual_explanatory",
    "current_information_retrieval",
    "repository_inspection",
    "small_code_modification",
    "substantial_code_modification",
    "debugging",
    "test_build_verification",
    "research",
    "tool_orchestration",
    "multi_step_implementation",
    "complex_reasoning_no_execution",
)

_DEBUGGING = re.compile(
    r"(?i)\b(?:bug|broken|crash|exception|traceback|failure|failing|debug|root cause|regression)\b"
)
_TEST_BUILD = re.compile(
    r"(?i)\b(?:test|pytest|unittest|build|compile|lint|type[- ]?check|verify|validate)\b"
)
_TRIVIAL = re.compile(
    r"(?i)^(?:hi|hello|hey|thanks|thank you|good (?:morning|afternoon|evening)|ok|okay)[.!? ]*$"
)
_FACTUAL = re.compile(
    r"(?i)\b(?:what is|who is|define|explain|how does|why does|summari[sz]e|describe)\b"
)


def sampling_category(request: str) -> str:
    """Classify request text for sampling without using route or outcome evidence."""
    text = " ".join(str(request).split())[:32_000]
    profile = decision_profile(text)
    if _TRIVIAL.search(text):
        return "conversational_trivial"
    if profile["current_information_required"]:
        return "current_information_retrieval"
    if profile["repository_required"] and profile["modification_required"]:
        if profile["multi_step_required"] or profile["complexity"] == "high":
            return "substantial_code_modification"
        return "small_code_modification"
    if _DEBUGGING.search(text):
        return "debugging"
    if profile["multi_step_required"] and profile["modification_required"]:
        return "multi_step_implementation"
    if _TEST_BUILD.search(text) and (
        profile["execution_required"] or profile["verification_required"]
    ):
        return "test_build_verification"
    if profile["repository_required"]:
        return "repository_inspection"
    if profile["multi_step_required"] or (
        profile["tool_required"] and profile["execution_required"]
    ):
        return "tool_orchestration"
    if profile["retrieval_required"]:
        return "research"
    if profile["complexity"] in {"medium", "high"} and not profile["execution_required"]:
        return "complex_reasoning_no_execution"
    if _FACTUAL.search(text):
        return "factual_explanatory"
    return "conversational_trivial"


def sampling_bucket(request: str) -> str:
    """Return a hidden acquisition bucket derived only from the request contract."""
    profile = decision_profile(request)
    delegate_dimensions = sum(bool(profile[name]) for name in (
        "repository_required",
        "retrieval_required",
        "execution_required",
        "modification_required",
        "verification_required",
        "multi_step_required",
    ))
    if delegate_dimensions >= 2:
        return "easy_delegate"
    if delegate_dimensions == 0 and profile.get("direct_signal"):
        return "easy_direct"
    return "boundary"


def public_review_item(item_id: str, request: str) -> dict[str, Any]:
    """Build the complete reviewer-visible item; no hidden evidence is serialized."""
    profile = decision_profile(request)
    return {
        "itemId": item_id,
        "request": str(request),
        "requirements": {
            "repository": bool(profile["repository_required"]),
            "retrieval": bool(profile["retrieval_required"]),
            "currentInformation": bool(profile["current_information_required"]),
            "modification": bool(profile["modification_required"]),
            "execution": bool(profile["execution_required"]),
            "verification": bool(profile["verification_required"]),
            "multiStep": bool(profile["multi_step_required"]),
        },
        "label": None,
        "reasonCategory": None,
        "note": "",
        "reviewStatus": "pending",
    }


def blind_review_payload(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "schemaVersion": BLIND_REVIEW_SCHEMA_VERSION,
        "kind": BLIND_REVIEW_KIND,
        "rubricVersion": RUBRIC_VERSION,
        "instructions": (
            "Judge only the sanitized request and explicitly stated pre-routing "
            "requirements. DIRECT means a reliable answer can be produced from the "
            "request context without external execution. DELEGATE means the request "
            "requires tools, retrieval, repository work, modification, execution, "
            "verification, or substantial orchestration. Use UNCERTAIN when the request "
            "does not support a reliable binary judgment."
        ),
        "reviewChoices": list(REVIEW_CHOICES),
        "reasonCategories": list(REASON_CATEGORIES),
        "reviewCount": len(items),
        "items": [dict(item) for item in items],
        "progress": {
            "direct": 0,
            "delegate": 0,
            "uncertain": 0,
            "pending": len(items),
            "total": len(items),
        },
    }
    validate_blind_review_payload(payload)
    return payload


def review_progress(payload: Mapping[str, Any]) -> dict[str, int]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("blind review input must contain an items list")
    result = {"direct": 0, "delegate": 0, "uncertain": 0, "pending": 0}
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("blind review items must be objects")
        label = item.get("label")
        if label == "DIRECT":
            result["direct"] += 1
        elif label == "DELEGATE":
            result["delegate"] += 1
        elif label == "UNCERTAIN":
            result["uncertain"] += 1
        else:
            result["pending"] += 1
    result["total"] = len(items)
    return result


def validate_blind_review_payload(payload: Mapping[str, Any]) -> None:
    """Reject review artifacts that could reveal hidden routing evidence."""
    allowed_top = {
        "schemaVersion",
        "kind",
        "rubricVersion",
        "instructions",
        "reviewChoices",
        "reasonCategories",
        "reviewCount",
        "items",
        "progress",
    }
    if set(payload) != allowed_top:
        raise ValueError("blind review payload contains non-contract top-level fields")
    if payload.get("schemaVersion") != BLIND_REVIEW_SCHEMA_VERSION:
        raise ValueError("blind review payload has an incompatible schema")
    if payload.get("kind") != BLIND_REVIEW_KIND:
        raise ValueError("blind review payload has an incompatible kind")
    if payload.get("rubricVersion") != RUBRIC_VERSION:
        raise ValueError("blind review payload has an unsupported rubric version")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 500:
        raise ValueError("blind review payload has an invalid item list")
    allowed_item = {
        "itemId", "request", "requirements", "label", "reasonCategory", "note",
        "reviewStatus",
    }
    allowed_requirements = {
        "repository", "retrieval", "currentInformation", "modification",
        "execution", "verification", "multiStep",
    }
    item_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping) or set(item) != allowed_item:
            raise ValueError(f"blind review item {index} contains non-contract fields")
        item_id = item.get("itemId")
        if not isinstance(item_id, str) or not re.fullmatch(r"br_[0-9a-f]{32}", item_id):
            raise ValueError(f"blind review item {index} has an invalid opaque id")
        if item_id in item_ids:
            raise ValueError("blind review payload contains duplicate item ids")
        item_ids.add(item_id)
        request = item.get("request")
        if not isinstance(request, str) or not request or len(request) > 32_000:
            raise ValueError(f"blind review item {index} has an invalid request")
        requirements = item.get("requirements")
        if not isinstance(requirements, Mapping) or set(requirements) != allowed_requirements:
            raise ValueError(f"blind review item {index} has invalid requirements")
        if not all(isinstance(value, bool) for value in requirements.values()):
            raise ValueError(f"blind review item {index} requirements must be boolean")
        label = item.get("label")
        if label not in {None, "DIRECT", "DELEGATE", "UNCERTAIN"}:
            raise ValueError(f"blind review item {index} has an invalid label")
        status = item.get("reviewStatus")
        expected = "pending" if label is None else "completed"
        if status != expected:
            raise ValueError(f"blind review item {index} has an invalid status")
        reason = item.get("reasonCategory")
        if reason is not None and reason not in REASON_CATEGORIES:
            raise ValueError(f"blind review item {index} has an invalid reason category")
        if not isinstance(item.get("note"), str) or len(str(item.get("note"))) > 2_000:
            raise ValueError(f"blind review item {index} has an invalid note")
    findings = forbidden_payload_paths(payload)
    if findings:
        raise ValueError(f"blind review payload leaks hidden evidence: {findings}")


def deterministic_sample_order(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: str,
    category_counts: Mapping[str, int],
    bucket_counts: Mapping[str, int] | None = None,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Stratify acquisition while returning a route-evidence-oblivious order."""
    buckets: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        category = sampling_category(str(row.get("request_text") or ""))
        bucket = sampling_bucket(str(row.get("request_text") or ""))
        buckets.setdefault((category, bucket), []).append(row)
    for (category, bucket), members in buckets.items():
        members.sort(key=lambda row: hashlib.sha256(
            f"{seed}:{category}:{bucket}:{row.get('record_id')}".encode("utf-8")
        ).hexdigest())
    selected: list[Mapping[str, Any]] = []
    mutable_counts = Counter({str(key): int(value) for key, value in category_counts.items()})
    mutable_bucket_counts = Counter({
        str(key): int(value) for key, value in (bucket_counts or {}).items()
    })
    while len(selected) < limit:
        available = [key for key, members in buckets.items() if members]
        if not available:
            break
        category, bucket = min(available, key=lambda value: (
            mutable_counts[value[0]],
            mutable_bucket_counts[value[1]],
            TARGET_CATEGORIES.index(value[0])
            if value[0] in TARGET_CATEGORIES else len(TARGET_CATEGORIES),
            ("easy_direct", "easy_delegate", "boundary").index(value[1]),
            value,
        ))
        selected.append(buckets[(category, bucket)].pop(0))
        mutable_counts[category] += 1
        mutable_bucket_counts[bucket] += 1
    selected.sort(key=lambda row: hashlib.sha256(
        f"{seed}:display:{row.get('record_id')}".encode("utf-8")
    ).hexdigest())
    return selected


def _kappa(observed: float, expected: float) -> float | None:
    if math.isclose(1.0 - expected, 0.0):
        return None
    return round((observed - expected) / (1.0 - expected), 6)


def agreement_metrics(votes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute nominal agreement without forcing disputed records to consensus."""
    by_record: dict[str, list[str]] = {}
    for vote in votes:
        verdict = str(vote.get("verdict") or "")
        if verdict not in {"DIRECT", "DELEGATE", "UNCERTAIN"}:
            continue
        by_record.setdefault(str(vote.get("record_id") or ""), []).append(verdict)
    repeated = [values for values in by_record.values() if len(values) >= 2]
    unanimous = sum(len(set(values)) == 1 for values in repeated)
    agreement_rate = unanimous / len(repeated) if repeated else None
    two_rater = [values for values in repeated if len(values) == 2]
    categories = ("DIRECT", "DELEGATE", "UNCERTAIN")
    cohen = None
    if two_rater:
        observed = sum(values[0] == values[1] for values in two_rater) / len(two_rater)
        first = Counter(values[0] for values in two_rater)
        second = Counter(values[1] for values in two_rater)
        expected = sum(
            first[value] / len(two_rater) * second[value] / len(two_rater)
            for value in categories
        )
        cohen = _kappa(observed, expected)
    fleiss_by_count: dict[str, float | None] = {}
    for rater_count in sorted({len(values) for values in repeated}):
        cohort = [values for values in repeated if len(values) == rater_count]
        if not cohort or rater_count < 2:
            continue
        observed = sum(
            sum(count * (count - 1) for count in Counter(values).values())
            / (rater_count * (rater_count - 1))
            for values in cohort
        ) / len(cohort)
        totals = Counter(value for values in cohort for value in values)
        total_votes = len(cohort) * rater_count
        expected = sum((totals[value] / total_votes) ** 2 for value in categories)
        fleiss_by_count[str(rater_count)] = _kappa(observed, expected)
    return {
        "multiReviewedRecordCount": len(repeated),
        "unanimousRecordCount": unanimous,
        "agreementRate": round(agreement_rate, 6) if agreement_rate is not None else None,
        "cohenKappaTwoReviewer": cohen,
        "fleissKappaByRaterCount": fleiss_by_count,
    }
