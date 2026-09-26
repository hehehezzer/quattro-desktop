"""Best-effort, secret-sanitized runtime telemetry and shadow inference."""

from __future__ import annotations

import hashlib
import math
import pathlib
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ..privacy import redact_secret_text
from .classical import DirectDelegateModel
from .features import decision_profile
from .store import IntelligenceStore


MAX_REQUEST_CHARS = 32_000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL_CREDENTIALS = re.compile(r"(?i)\bhttps?://[^\s/@:]+:[^\s/@]+@")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("coding", re.compile(r"(?i)\b(code|repo|repository|implement|fix|test|build|debug|refactor|file)\b")),
    ("research", re.compile(r"(?i)\b(research|sources?|citations?|investigate|compare|evidence)\b")),
    ("reasoning", re.compile(r"(?i)\b(reason|analy[sz]e|architecture|trade-?offs?|root cause|prove)\b")),
)


def redact_request_credentials(text: str) -> tuple[str, bool]:
    """Detect secrets independently of normalization and retention limits."""
    safe, redacted = redact_secret_text(text)
    safe, url_count = _URL_CREDENTIALS.subn("https://[REDACTED]@", safe)
    safe, bearer_count = _BEARER.subn("Bearer [REDACTED]", safe)
    return safe, bool(redacted or url_count or bearer_count)


def sanitize_request(value: str) -> tuple[str, bool]:
    """Redact common credential shapes and bound retained training text."""
    text = value if isinstance(value, str) else str(value)
    safe, redacted = redact_request_credentials(text)
    safe, control_count = _CONTROL.subn(" ", safe)
    safe = safe[:MAX_REQUEST_CHARS]
    return safe, bool(redacted or control_count or len(text) > len(safe))


def request_fingerprint(value: str) -> str:
    normalized = " ".join(value.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def project_fingerprint(project: pathlib.Path | str | None) -> str | None:
    if project is None:
        return None
    normalized = str(pathlib.Path(project).expanduser().resolve(strict=False))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def category_for_request(value: str) -> str:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(value):
            return category
    return "general"


def _enum_value(value: Any, default: str = "unknown") -> str:
    candidate = getattr(value, "value", value)
    return str(candidate) if candidate is not None else default


def _profile_fields(profile: Mapping[str, Any] | None, request: str,
                    decision_features: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or {}
    safe = decision_features if decision_features is not None else decision_profile(request)
    task_type = str(profile.get("task_type") or profile.get("taskType") or "unknown")
    return {
        "task_type": task_type,
        "complexity": safe["complexity"],
        "category": safe["category"],
        "task_category": safe["task_category"],
        "repository_required": safe["repository_required"],
        "retrieval_required": safe["retrieval_required"],
        "tool_required": safe["tool_required"],
        "current_information_required": safe["current_information_required"],
        "execution_required": safe["execution_required"],
        "modification_required": safe["modification_required"],
        "verification_required": safe["verification_required"],
        "multi_step_required": safe["multi_step_required"],
        "context_tokens": max(
            0,
            int(profile.get("final_request_tokens") or profile.get("finalRequestTokens") or 0),
        ),
    }


def shadow_predict(
    store: IntelligenceStore,
    *,
    request: str,
    profile: Mapping[str, Any] | None,
    repository_present: bool,
    model_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run safe advisory inference with the active shadow model."""
    active = store.active_shadow_model()
    if not active:
        return {"error": "model_unavailable"}
    artifact = pathlib.Path(str(active["artifact_path"]))
    started = time.perf_counter()
    try:
        model = DirectDelegateModel.load(artifact)
        # Legacy artifacts remain readable for offline ablations, but they
        # contain repository-presence/context fields that are not part of the
        # request-time contract.  Never let one become a live shadow input.
        if model.feature_set == "legacy_full":
            return {
                "model_version": str(active["model_version"]),
                "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
                "error": "unsafe_model_features",
            }
        prediction = model.predict(
            request,
            profile=profile or {},
            repository_present=repository_present,
            **({"model_input": model_input} if model_input is not None else {}),
        )
    except (OSError, TypeError, ValueError, KeyError, OverflowError):
        return {
            "model_version": str(active["model_version"]),
            "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
            "error": "inference_failed",
        }
    return {
        "prediction": prediction["prediction"],
        "confidence": prediction["confidence"],
        "model_version": str(active["model_version"]),
        "latency_ms": round((time.perf_counter() - started) * 1_000, 3),
        "error": None,
    }


def record_routing_telemetry(
    database_path: pathlib.Path,
    *,
    request: str,
    production_decision: str,
    routing_reason: str,
    production_confidence: float | None,
    selected_worker: str | None,
    selected_model: str | None,
    selected_provider: str | None,
    selected_account: str | None,
    project: pathlib.Path | None,
    repository_present: bool,
    profile: Mapping[str, Any] | None = None,
    source_task_id: str | None = None,
    source_kind: str = "runtime",
    record_id: str | None = None,
    entrypoint: str = "unknown",
    decision_applied: bool = True,
    run_shadow: bool = True,
    shadow_result: Mapping[str, Any] | None = None,
    decision_features: Mapping[str, Any] | None = None,
    group_fingerprint: str | None = None,
    alternatives: Sequence[Mapping[str, Any] | str] = (),
    created_at: str | None = None,
) -> str | None:
    """Record one routing decision; all errors fail open to production routing."""
    try:
        safe_request, redacted = sanitize_request(request)
        fields = _profile_fields(profile, safe_request, decision_features)
        store = IntelligenceStore(database_path, busy_timeout_ms=100)
        shadow = dict(shadow_result) if shadow_result is not None else (
            shadow_predict(
                store,
                request=safe_request,
                profile=fields,
                repository_present=repository_present,
                model_input=decision_features,
            )
            if run_shadow else {"error": "historical_backfill"}
        )
        return store.record_routing({
            "record_id": record_id,
            "source_kind": source_kind,
            "source_task_id": source_task_id,
            "entrypoint": entrypoint,
            "decision_applied": decision_applied,
            "request_text": safe_request,
            "request_fingerprint": request_fingerprint(safe_request),
            "group_fingerprint": group_fingerprint or request_fingerprint(safe_request),
            "request_redacted": redacted,
            "request_length": len(safe_request),
            "estimated_tokens": max(0, math.ceil(len(safe_request) / 4)),
            **fields,
            "repository_present": repository_present,
            "project_fingerprint": project_fingerprint(project),
            "production_decision": production_decision,
            "selected_worker": selected_worker,
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "selected_account": selected_account,
            "routing_reason": routing_reason[:500],
            "production_confidence": production_confidence,
            "alternatives": alternatives,
            "created_at": created_at,
            "ml_prediction": shadow.get("prediction"),
            "ml_confidence": shadow.get("confidence"),
            "ml_model_version": shadow.get("model_version"),
            "inference_latency_ms": shadow.get("latency_ms"),
            "inference_error_code": shadow.get("error"),
        })
    except (OSError, TypeError, ValueError, KeyError, sqlite3.Error):
        return None


def update_execution_telemetry(
    database_path: pathlib.Path,
    record_id: str | None,
    payload: Mapping[str, Any],
) -> None:
    """Update outcome evidence without ever affecting the execution lifecycle."""
    if not record_id:
        return
    try:
        IntelligenceStore(database_path, busy_timeout_ms=100).update_execution(record_id, payload)
    except (OSError, TypeError, ValueError, KeyError, sqlite3.Error):
        return
