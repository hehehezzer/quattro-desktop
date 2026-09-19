"""Leakage-safe decision-time features for DIRECT/DELEGATE intelligence."""

from __future__ import annotations

import re
import json
from collections.abc import Mapping
from typing import Any


_REPOSITORY = re.compile(
    r"(?i)(?:\b(?:repo(?:sitory)?|codebase|working tree|source tree)\b|"
    r"\b(?:locate|find|inspect|open|read|search|trace)\b.{0,80}\b(?:file|symbol|class|function|"
    r"module|readme|config|manifest|path|implementation)\b|"
    r"\b(?:file|symbol|class|function|module|readme|config|manifest|path)\b.{0,80}"
    r"\b(?:in|inside|within|from)\b.{0,40}\b(?:repo(?:sitory)?|codebase|project)\b)"
)
_RETRIEVAL = re.compile(
    r"(?i)\b(?:browse|search (?:the )?web|web search|research|look up|lookup|fetch|retrieve|"
    r"find (?:current|official|recent|the latest)|sources?|citations?|official docs?|"
    r"multiple sources|external state)\b"
)
_CURRENT_INFORMATION = re.compile(
    r"(?i)(?:\b(?:latest|newest|up[- ]to[- ]date|today(?:'s)?|as of)\b|"
    r"\b(?:current|recent|live|present)\b.{0,40}\b(?:status|state|version|release|"
    r"guidance|documentation|price|weather|news|availability|information)\b)"
)
_MODIFICATION = re.compile(
    r"(?i)(?:\b(?:modify|edit|fix|implement|patch|refactor|migrate|install|configure|"
    r"upgrade|replace|rename|deploy)\b|\b(?:change|update|add|remove|delete|create|write)\b"
    r".{0,60}\b(?:code|file|module|class|function|parser|implementation|config|"
    r"repository|repo|migration|test|script|service|application)\b)"
)
_EXECUTION = re.compile(
    r"(?i)\b(?:run|execute|build|test|lint|compile|benchmark|profile|debug|reproduce|"
    r"inspect|investigate|trace|locate|query|measure|capture|download|upload|"
    r"start|stop|restart|apply|commit|merge)\b"
)
_VERIFICATION = re.compile(
    r"(?i)(?:\b(?:verify|validate|confirm|check|audit|reproduce|test|build)\b.{0,70}"
    r"\b(?:state|status|output|result|logs?|implementation|behavior|environment|system|"
    r"service|build|tests?)\b|\binspect (?:the )?(?:state|output|result|logs?)\b|"
    r"\bcompare (?:the )?(?:result|output)\b)"
)
_TOOL = re.compile(
    r"(?i)\b(?:tool|terminal|command|shell|browser|logs?|filesystem|git|docker|"
    r"kubectl|pytest|npm|cargo)\b"
)
_MULTI_STEP = re.compile(
    r"(?i)(?:\b(?:first|then|next|after that|finally|step \d+|end[- ]to[- ]end|multi[- ]step)\b|"
    r"(?:\b(?:inspect|find|research|verify|run|modify|implement|build|test)\b.{0,100}){2,})"
)
_DIRECT = re.compile(
    r"(?i)\b(?:explain|define|what is|how does|why does|compare|contrast|summari[sz]e|"
    r"rewrite|draft|brainstorm|reason about|analy[sz]e conceptually|pros and cons|"
    r"give an example|outline|describe)\b"
)
_REASONING = re.compile(
    r"(?i)\b(?:reason|analy[sz]e|compare|trade[- ]offs?|architecture|root cause|"
    r"security|concurrency|strategy|decision|evaluate)\b"
)
_CODING = re.compile(
    r"(?i)\b(?:code|repo(?:sitory)?|codebase|source|file|symbol|function|class|module|"
    r"implementation|test suite|build|compile|debug|refactor|api endpoint|database migration)\b"
)


SAFE_FEATURES = (
    "request_text",
    "request_length",
    "estimated_tokens",
    "repository_required",
    "retrieval_required",
    "tool_required",
    "current_information_required",
    "execution_required",
    "modification_required",
    "verification_required",
    "multi_step_required",
    "complexity",
    "category",
    "task_category",
)

QUESTIONABLE_FEATURES = (
    "repository_present",
    "context_tokens",
    "entrypoint",
    "source_kind",
    "task_type",
    "scope",
    "risk",
    "tier",
)

LEAKAGE_FEATURES = (
    "production_decision",
    "routing_reason",
    "production_confidence",
    "decision_applied",
    "selected_worker",
    "selected_model",
    "selected_provider",
    "selected_account",
    "tools",
    "retrieval_used",
    "retrieved_chunk_ids",
    "ml_prediction",
    "ml_confidence",
    "outcome_success",
    "validation_status",
    "test_status",
    "build_status",
    "failure_category",
    "execution_time_ms",
    "retries",
    "fallback_used",
)

MODEL_INPUT_FIELDS = SAFE_FEATURES

_FORBIDDEN_NORMALIZED_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", value.lower())
    for value in (
        *QUESTIONABLE_FEATURES,
        *LEAKAGE_FEATURES,
        "router_decision",
        "router_reason",
        "router_confidence",
        "router_tier",
        "route_decision",
        "route_reason",
        "actual_worker",
        "actual_model",
        "actual_provider",
        "actual_account",
        "actual_tools",
        "actual_retrieval",
        "execution_success",
        "execution_failure",
        "latency_ms",
        "retry_count",
        "final_request_tokens",
        "final_context_tokens",
        "shadow_prediction",
        "shadow_confidence",
    )
)
_ALLOWED_COMPLEXITIES = frozenset({"low", "medium", "high"})
_ALLOWED_CATEGORIES = frozenset({"coding", "research", "reasoning", "general"})
_ALLOWED_TASK_CATEGORIES = frozenset({
    "general", "explanation", "comparison", "reasoning", "summarization",
    "drafting", "conceptual_analysis", "repository_inspection",
    "repository_modification", "repository_verification", "file_lookup",
    "implementation", "verification", "tool_execution", "test_build_execution",
    "tool_investigation", "external_research", "current_information_research",
    "multi_source_verification", "multi_step_execution", "system_investigation",
    "noncoding_execution", "security_review", "ambiguous",
})


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def forbidden_payload_paths(payload: Any, *, path: str = "$") -> list[str]:
    """Find forbidden aliases recursively in untrusted candidate feature payloads."""
    findings: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if _normalized_key(key) in _FORBIDDEN_NORMALIZED_KEYS:
                findings.append(child)
            findings.extend(forbidden_payload_paths(value, path=child))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            findings.extend(forbidden_payload_paths(value, path=f"{path}[{index}]"))
    elif isinstance(payload, str) and len(payload) <= 32_000 and payload.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return findings
        findings.extend(forbidden_payload_paths(decoded, path=f"{path}<json>"))
    return findings


def project_model_input(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete allowlisted decision-time view consumed by ML."""
    request = str(row.get("request_text") or "")
    # Runtime records may contain a profile object assembled after routing.
    # Only the explicit, non-production probe contract is allowed to override
    # text-derived fields.  This keeps the public helper useful for controlled
    # probe ingestion while preventing a caller from smuggling a post-decision
    # value through an otherwise safe-looking key such as ``complexity``.
    trusted_contract = (
        row
        if row.get("feature_provenance") == "probe_contract_v2"
        and not bool(row.get("decision_applied"))
        else None
    )
    derived = decision_profile(request, trusted_contract)
    result = {
        "request_text": request,
        "request_length": len(request),
        "estimated_tokens": max(0, (len(request) + 3) // 4),
        **{name: derived[name] for name in SAFE_FEATURES if name not in {
            "request_text", "request_length", "estimated_tokens"
        }},
    }
    validate_model_input(result)
    return result


def validate_model_input(payload: Mapping[str, Any]) -> None:
    """Fail closed if a model-facing payload leaves the decision-time allowlist."""
    keys = set(payload)
    expected = set(MODEL_INPUT_FIELDS)
    if keys != expected:
        extra = sorted(keys - expected)
        missing = sorted(expected - keys)
        raise ValueError(
            f"invalid model input fields; extra={extra}, missing={missing}"
        )
    findings = forbidden_payload_paths({
        key: value for key, value in payload.items() if key != "request_text"
    })
    if findings:
        raise ValueError(f"forbidden model input fields: {findings}")
    if any(isinstance(value, (Mapping, list, tuple)) for value in payload.values()):
        raise ValueError("model input fields must be scalar decision-time values")
    if str(payload["complexity"]) not in _ALLOWED_COMPLEXITIES:
        raise ValueError("model input complexity is outside the decision-time vocabulary")
    if str(payload["category"]) not in _ALLOWED_CATEGORIES:
        raise ValueError("model input category is outside the decision-time vocabulary")
    if str(payload["task_category"]) not in _ALLOWED_TASK_CATEGORIES:
        raise ValueError("model input task category is outside the decision-time vocabulary")


def _task_category(
    text: str,
    *,
    repository: bool,
    retrieval: bool,
    current: bool,
    modification: bool,
    verification: bool,
    execution: bool,
) -> str:
    if repository and modification:
        return "repository_modification"
    if repository and verification:
        return "repository_verification"
    if repository:
        return "repository_inspection"
    if current and retrieval:
        return "current_information_research"
    if retrieval:
        return "external_research"
    if modification:
        return "implementation"
    if verification:
        return "verification"
    if execution:
        return "tool_execution"
    if re.search(r"(?i)\b(?:summari[sz]e|condense|key points)\b", text):
        return "summarization"
    if re.search(r"(?i)\b(?:draft|write|rewrite|compose)\b", text):
        return "drafting"
    if re.search(r"(?i)\b(?:compare|contrast|versus|vs\.?|trade[- ]offs?)\b", text):
        return "comparison"
    if _REASONING.search(text):
        return "reasoning"
    if _DIRECT.search(text):
        return "explanation"
    return "general"


def extract_decision_features(request: str) -> dict[str, Any]:
    """Infer only features available before routing from sanitized request text."""
    text = " ".join(str(request).split())[:32_000]
    repository = bool(_REPOSITORY.search(text))
    current = bool(_CURRENT_INFORMATION.search(text))
    modification = bool(_MODIFICATION.search(text))
    verification = bool(_VERIFICATION.search(text))
    explicit_execution = bool(_EXECUTION.search(text))
    retrieval = bool(_RETRIEVAL.search(text) or repository or current)
    execution = bool(explicit_execution or modification or repository)
    tool = bool(_TOOL.search(text) or retrieval or execution or verification)
    multi_step = bool(_MULTI_STEP.search(text))
    independent_dimensions = sum((
        repository,
        current,
        modification,
        verification,
        multi_step,
        bool(retrieval and not repository and not current),
        bool(explicit_execution and not repository and not modification),
    ))
    if multi_step or independent_dimensions >= 3 or re.search(
        r"(?i)\b(?:system investigation|incident|production outage|security audit|"
        r"architecture migration|across multiple|end[- ]to[- ]end)\b",
        text,
    ):
        complexity = "high"
    elif independent_dimensions >= 1 or _REASONING.search(text):
        complexity = "medium"
    else:
        complexity = "low"
    if _CODING.search(text) or repository:
        category = "coding"
    elif retrieval or current:
        category = "research"
    elif _REASONING.search(text) or _DIRECT.search(text):
        category = "reasoning"
    else:
        category = "general"
    return {
        "repository_required": repository,
        "retrieval_required": retrieval,
        "tool_required": tool,
        "current_information_required": current,
        "execution_required": execution,
        "modification_required": modification,
        "verification_required": verification,
        "multi_step_required": multi_step,
        "complexity": complexity,
        "category": category,
        "task_category": _task_category(
            text,
            repository=repository,
            retrieval=retrieval,
            current=current,
            modification=modification,
            verification=verification,
            execution=execution,
        ),
        "direct_signal": bool(_DIRECT.search(text)),
    }


def decision_profile(request: str, supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge trusted explicit contract fields over text-derived decision features."""
    result = extract_decision_features(request)
    supplied = supplied or {}
    aliases = {
        "repository_required": ("repository_required", "repositoryRequired"),
        "retrieval_required": ("retrieval_required", "retrievalRequired"),
        "tool_required": ("tool_required", "toolRequired"),
        "current_information_required": (
            "current_information_required", "currentInformationRequired"
        ),
        "execution_required": ("execution_required", "executionRequired"),
        "modification_required": ("modification_required", "modificationRequired"),
        "verification_required": ("verification_required", "verificationRequired"),
        "multi_step_required": ("multi_step_required", "multiStepRequired"),
    }
    for target, names in aliases.items():
        for name in names:
            if name in supplied and supplied[name] is not None:
                result[target] = bool(supplied[name])
                break
    for name in ("complexity", "category", "task_category"):
        if supplied.get(name):
            result[name] = str(supplied[name])
    return result


def feature_audit() -> dict[str, list[str]]:
    return {
        "safeAtDecisionTime": list(SAFE_FEATURES),
        "questionable": list(QUESTIONABLE_FEATURES),
        "leakageOrPostDecision": list(LEAKAGE_FEATURES),
        "defaultModelExcludes": list(QUESTIONABLE_FEATURES + LEAKAGE_FEATURES),
        "modelInputAllowlist": list(MODEL_INPUT_FIELDS),
    }
