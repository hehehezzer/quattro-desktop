"""Evidence-aware, deterministic routing intelligence owned by Quattro Core.

This module never dispatches provider requests.  It profiles a task, evaluates
sanitized candidate metadata supplied by OmniRoute, combines curated public
benchmark evidence with privacy-safe Quattro outcomes, and produces an
auditable requirement/preference decision for the existing OmniRoute route.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ROUTING_POLICY_VERSION = "quattro-routing-v2"
BENCHMARK_NORMALIZATION_VERSION = "benchmark-normalization-v1"
EVIDENCE_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
MAX_EVIDENCE_BYTES = 2_000_000
MAX_EVIDENCE_RECORDS = 2_000
LOCAL_OUTCOME_FULL_CONFIDENCE_SAMPLES = 20

QUALITY_WEIGHTS = {"metadata": 0.25, "benchmark": 0.50, "local": 0.25}
QUALITY_THRESHOLDS = {"FAST": 0.45, "STANDARD": 0.65, "REASONING": 0.80}

BENCHMARK_DIMENSIONS = (
    "coding_score",
    "reasoning_score",
    "agentic_tool_use_score",
    "repository_task_score",
    "long_context_score",
    "instruction_following_score",
)

ALLOWLISTED_BENCHMARK_SOURCES = {
    "swe-bench": ("swebench.com", "github.com", "raw.githubusercontent.com"),
    "livecodebench": ("livecodebench.github.io", "github.com", "raw.githubusercontent.com"),
    "terminal-bench": ("terminal-bench.com", "github.com", "raw.githubusercontent.com"),
    "official-model-card": (
        "openai.com", "developers.openai.com", "anthropic.com", "ai.google.dev",
        "deepmind.google", "mistral.ai",
    ),
}
SOURCE_RELIABILITY = {
    "swe-bench": 1.0,
    "livecodebench": 0.95,
    "terminal-bench": 0.90,
    "official-model-card": 0.90,
}

PERCENTAGE_BENCHMARKS = {
    "swe-bench", "swe-bench verified", "livecodebench", "terminalbench", "terminal-bench",
}


def normalize_benchmark_score(benchmark: str, raw_score: float) -> float:
    """Normalize one allowlisted benchmark independently and audibly.

    The supported public leaderboards publish percentage success/pass rates.
    Official model-card evidence must provide an already normalized dimension;
    ambiguous scales are rejected instead of guessed.
    """
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        raise ValueError("benchmark score must be numeric")
    score = float(raw_score)
    if not math.isfinite(score):
        raise ValueError("benchmark score must be finite")
    name = benchmark.strip().lower()
    if name in PERCENTAGE_BENCHMARKS:
        if not 0 <= score <= 100:
            raise ValueError("percentage benchmark score must be within [0,100]")
        return score / 100
    if name.startswith("official:"):
        if not 0 <= score <= 1:
            raise ValueError("official normalized score must be within [0,1]")
        return score
    raise ValueError("benchmark normalization method is not registered")


class Level(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Scope(StrEnum):
    LOCAL = "local"
    MODULE = "module"
    MULTI_MODULE = "multi_module"
    SYSTEM = "system"


class VerificationStrength(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class ContextClass(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


class RoutingTierName(StrEnum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    REASONING = "REASONING"


class PreferenceMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


class Availability(StrEnum):
    AVAILABLE = "available"
    RETRY = "retry"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    COOLDOWN = "cooldown"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class TaskProfile:
    task_type: str
    complexity: Level
    ambiguity: Level
    risk: Risk
    scope: Scope
    reasoning_depth: Level
    verification_strength: VerificationStrength
    context_requirement: ContextClass
    estimated_tokens: int
    required_capabilities: tuple[str, ...]
    minimum_quality: float
    tier: RoutingTierName
    signals: tuple[str, ...]
    scores: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "complexity", "ambiguity", "risk", "scope", "reasoning_depth",
            "verification_strength", "context_requirement", "tier",
        ):
            value[key] = str(value[key])
        value["required_capabilities"] = list(self.required_capabilities)
        value["signals"] = list(self.signals)
        value["scores"] = dict(self.scores)
        return value


def task_profile_from_dict(value: Mapping[str, Any]) -> TaskProfile:
    """Validate and reconstruct a profile from a persisted decision snapshot."""
    return TaskProfile(
        task_type=str(value["task_type"]),
        complexity=Level(str(value["complexity"])),
        ambiguity=Level(str(value["ambiguity"])),
        risk=Risk(str(value["risk"])),
        scope=Scope(str(value["scope"])),
        reasoning_depth=Level(str(value["reasoning_depth"])),
        verification_strength=VerificationStrength(str(value["verification_strength"])),
        context_requirement=ContextClass(str(value["context_requirement"])),
        estimated_tokens=int(value["estimated_tokens"]),
        required_capabilities=tuple(str(item) for item in value["required_capabilities"]),
        minimum_quality=float(value["minimum_quality"]),
        tier=RoutingTierName(str(value["tier"])),
        signals=tuple(str(item) for item in value["signals"]),
        scores={str(key): int(score) for key, score in dict(value["scores"]).items()},
    )


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    source: str
    source_url: str
    benchmark: str
    provider: str
    canonical_model: str
    model_version: str
    variant: str
    source_date: str
    retrieved_at: str
    confidence: float
    dimensions: Mapping[str, float]
    normalization_version: str = BENCHMARK_NORMALIZATION_VERSION
    raw_metric: str | float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"dimensions": dict(self.dimensions)}


@dataclass(frozen=True, slots=True)
class LocalOutcomeStats:
    provider: str
    model: str
    task_type: str
    tier: str
    samples: int
    execution_successes: int
    validated_successes: int
    validation_observed: int
    retries: int
    escalations: int
    latency_ms_total: float
    cost_total: float
    cost_observed: int = 0
    cost_unknown: int = 0

    @property
    def validated_success_rate(self) -> float | None:
        if self.validation_observed <= 0:
            return None
        return self.validated_successes / self.validation_observed

    @property
    def confidence(self) -> float:
        return min(1.0, self.validation_observed / LOCAL_OUTCOME_FULL_CONFIDENCE_SAMPLES)


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    provider: str
    model: str
    capabilities: frozenset[str]
    practical_input_limit: int | None
    availability: Availability
    retry_eligible: bool
    metadata_quality: float
    input_cost_per_million: float | None
    output_cost_per_million: float | None
    expected_input_tokens: int
    expected_output_tokens: int
    latency_ms: float
    stable_key: str = ""


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    provider: str
    model: str
    eligible: bool
    rejection_reasons: tuple[str, ...]
    quality_estimate: float | None
    quality_components: Mapping[str, float]
    expected_completion_cost: float | None
    latency_ms: float
    quality_confidence: float = 0.0
    pricing_state: str = "unknown"
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "rejection_reasons": list(self.rejection_reasons),
            "quality_components": dict(self.quality_components),
        }


@dataclass(frozen=True, slots=True)
class ModelSelection:
    selected_provider: str | None
    selected_model: str | None
    rationale: str
    candidates: tuple[CandidateDecision, ...]
    policy_version: str = ROUTING_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "rationale": self.rationale,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "policy_version": self.policy_version,
        }


_TRIVIAL_OPERATION = re.compile(
    r"\b(?:fix\s+(?:a\s+)?typo|rename\s+[\w.`/-]+\s+to\s+[\w.`/-]+|"
    r"format|reformat|update\s+(?:the\s+)?docs?|documentation only|change\s+(?:a\s+)?label)\b",
    re.IGNORECASE,
)
_MECHANICAL_READ = re.compile(
    r"\b(?:find|search|locate|list|read|inspect|summari[sz]e|explain|grep)\b",
    re.IGNORECASE,
)
_MUTATION = re.compile(
    r"\b(?:implement(?:ed|ing|ation)?|add|create|modify|edit|change|update|fix|rename|refactor|migrate|delete|remove|"
    r"deploy|install|commit|write|patch|replace)\b", re.IGNORECASE,
)
_DIAGNOSIS = re.compile(
    r"\b(?:debug|diagnos(?:e|is)|investigate|root cause|intermittent|flaky|unknown|why|"
    r"cannot reproduce|nondeterministic)\b", re.IGNORECASE,
)
_ARCHITECTURE = re.compile(
    r"\b(?:architecture|architectural|system design|distributed|cross[- ]cutting|"
    r"trade-?offs?|redesign)\b", re.IGNORECASE,
)
_SECURITY = re.compile(
    r"\b(?:authentication|authorization|security|vulnerability|bypass|privilege|tenant|"
    r"injection|secret|credential|permission|access control|threat model)\b", re.IGNORECASE,
)
_CONCURRENCY = re.compile(
    r"\b(?:concurren(?:cy|t)|race condition|deadlock|atomic(?:ity)?|lock contention|"
    r"distributed transaction)\b", re.IGNORECASE,
)
_DATABASE = re.compile(
    r"\b(?:database|schema|migration|backfill|ddl|table|column|index|data migration)\b",
    re.IGNORECASE,
)
_INFRASTRUCTURE = re.compile(
    r"\b(?:production|infrastructure|terraform|kubernetes|k8s|docker|deployment|ci/?cd|"
    r"systemd|firewall|dns|load balancer)\b", re.IGNORECASE,
)
_DESTRUCTIVE = re.compile(
    r"\b(?:drop|truncate|destroy|wipe|purge|force[- ]push|reset --hard|delete all|"
    r"irreversible|data loss)\b", re.IGNORECASE,
)
_MULTI_SCOPE = re.compile(
    r"\b(?:multi[- ](?:file|module|service|repository)|across (?:the )?(?:repo|codebase|system)|"
    r"end[- ]to[- ]end|cross[- ]module|several modules|many files)\b", re.IGNORECASE,
)
_SYSTEM_SCOPE = re.compile(
    r"\b(?:system[- ]wide|whole (?:repository|codebase|platform)|all services|architecture)\b",
    re.IGNORECASE,
)
_RESEARCH = re.compile(r"\b(?:research|web search|find sources|compare sources|official docs)\b", re.IGNORECASE)
_VISION = re.compile(r"\b(?:image|screenshot|photo|visual|diagram)\b", re.IGNORECASE)
_STRUCTURED = re.compile(r"\b(?:json|yaml|structured output|schema-valid|machine-readable)\b", re.IGNORECASE)
_STRONG_VALIDATION = re.compile(
    r"\b(?:unit tests?|integration tests?|build|lint|typecheck|acceptance criteria|reproduce)\b",
    re.IGNORECASE,
)
_WEAK_VALIDATION = re.compile(
    r"\b(?:cannot test|no tests?|manual only|subjective|unknown environment|without reproducing|cannot reproduce)\b",
    re.IGNORECASE,
)


def _level(score: int, medium: int, high: int) -> Level:
    if score >= high:
        return Level.HIGH
    if score >= medium:
        return Level.MEDIUM
    return Level.LOW


def _context_class(tokens: int) -> ContextClass:
    if tokens >= 100_000:
        return ContextClass.VERY_LARGE
    if tokens >= 32_000:
        return ContextClass.LARGE
    if tokens >= 8_000:
        return ContextClass.MEDIUM
    return ContextClass.SMALL


def _task_type(text: str, mutation: bool) -> str:
    if _TRIVIAL_OPERATION.search(text) and re.search(r"\b(?:docs?|documentation|readme)\b", text, re.I):
        return "documentation"
    if not mutation and _MECHANICAL_READ.search(text):
        return "repository_read"
    if _SECURITY.search(text):
        return "security"
    if _CONCURRENCY.search(text):
        return "concurrency"
    if _DATABASE.search(text) and re.search(r"\b(?:migration|schema|backfill|ddl)\b", text, re.I):
        return "database_migration"
    if _ARCHITECTURE.search(text):
        return "architecture"
    if _DIAGNOSIS.search(text):
        return "debugging"
    if _RESEARCH.search(text):
        return "research"
    if re.search(r"\b(?:docs?|documentation|readme)\b", text, re.I):
        return "documentation"
    return "implementation" if mutation else "conversation"


def profile_task(
    request: str,
    *,
    agent: str = "codex",
    workflow: str = "general-task",
    policy_name: str = "workspace-write",
    conversation_tokens: int = 0,
    retrieved_tokens: int = 0,
    tool_schema_tokens: int = 0,
    output_reserve_tokens: int = 2_000,
    write_scopes: Sequence[str] = (),
    quality_thresholds: Mapping[str, float] | None = None,
) -> TaskProfile:
    """Build a transparent multi-signal profile without calling a classifier model."""
    text = " ".join(request.split())[:16_000]
    prompt_tokens = max(1, math.ceil(len(text) / 4))
    estimated_tokens = max(1, prompt_tokens + max(0, conversation_tokens) + max(0, retrieved_tokens)
                           + max(0, tool_schema_tokens) + max(0, output_reserve_tokens))
    if re.search(r"\b(?:huge|very large|entire|whole)\b.{0,32}\b(?:context|repository|codebase)\b", text, re.I):
        estimated_tokens = max(estimated_tokens, 100_000)
    signals: list[str] = []
    mutation = bool(_MUTATION.search(text))
    if re.search(
        r"\b(?:do not|don't|without)\s+(?:modify|change|edit|write|update|delete|remove)\b",
        text,
        re.IGNORECASE,
    ):
        mutation = len(list(_MUTATION.finditer(text))) > 1
    trivial = bool(_TRIVIAL_OPERATION.search(text))
    mechanical_read = bool(_MECHANICAL_READ.search(text)) and not mutation
    diagnosis = bool(_DIAGNOSIS.search(text))
    architecture = bool(_ARCHITECTURE.search(text))
    security = bool(_SECURITY.search(text))
    concurrency = bool(_CONCURRENCY.search(text))
    database = bool(_DATABASE.search(text))
    infrastructure = bool(_INFRASTRUCTURE.search(text))
    destructive = bool(_DESTRUCTIVE.search(text))
    multi_scope = bool(_MULTI_SCOPE.search(text)) or len(write_scopes) >= 3
    system_scope = bool(_SYSTEM_SCOPE.search(text))

    complexity_score = 0
    reasoning_score = 0
    ambiguity_score = 0
    risk_score = 0
    scope_score = 0

    if mutation:
        complexity_score += 1
        signals.append("mutation")
    if diagnosis:
        complexity_score += 2
        reasoning_score += 2
        ambiguity_score += 2
        signals.append("diagnosis")
    if architecture:
        complexity_score += 3
        reasoning_score += 3
        scope_score += 2
        signals.append("architecture")
    if security:
        risk_score += 3
        reasoning_score += 2
        signals.append("security_sensitive")
    if concurrency:
        complexity_score += 3
        reasoning_score += 3
        risk_score += 2
        signals.append("concurrency")
    if database:
        complexity_score += 2
        risk_score += 2
        scope_score += 1
        signals.append("database_change")
    if infrastructure:
        complexity_score += 2
        risk_score += 2
        scope_score += 2
        signals.append("infrastructure_impact")
    if destructive:
        risk_score += 4
        signals.append("destructive_potential")
    if multi_scope:
        complexity_score += 2
        scope_score += 2
        signals.append("multi_module_scope")
    if system_scope:
        complexity_score += 2
        scope_score += 3
        signals.append("system_scope")
    if re.search(r"\b(?:unclear|ambiguous|not sure|unknown requirements?|figure out)\b", text, re.I):
        ambiguity_score += 2
        signals.append("explicit_ambiguity")
    if diagnosis and re.search(r"\b(?:intermittent|flaky|unknown|cannot reproduce|nondeterministic)\b", text, re.I):
        ambiguity_score += 1
        signals.append("diagnostic_uncertainty")
    if estimated_tokens >= 32_000:
        complexity_score += 2
        reasoning_score += 1
        signals.append("large_context")
    if policy_name in {"audit-read-only", "review-untrusted"} and "security" in workflow:
        risk_score = max(risk_score, 4)
        reasoning_score = max(reasoning_score, 3)
        signals.append("security_review_workflow")
    if agent == "pi" and workflow == "codex-pi-delegation":
        complexity_score = min(complexity_score, 1)
        reasoning_score = min(reasoning_score, 1)
        risk_score = min(risk_score, 1)
        signals.append("bounded_read_only_delegation")

    # Operation semantics dominate stray nouns. A clearly localized mechanical
    # edit stays cheap unless the request also asks to diagnose or change the
    # sensitive system named by those nouns.
    if trivial and not diagnosis and not architecture and not concurrency and not destructive:
        complexity_score = min(complexity_score, 1)
        reasoning_score = min(reasoning_score, 1)
        scope_score = min(scope_score, 0)
        if not re.search(r"\b(?:bypass|vulnerability|harden|migrate|production)\b", text, re.I):
            risk_score = 0
        signals.append("localized_mechanical_operation")
    elif mechanical_read and not diagnosis and not architecture and not concurrency:
        complexity_score = min(complexity_score, 0)
        reasoning_score = min(reasoning_score, 0)
        scope_score = 0
        risk_score = 0
        signals.append("localized_mechanical_read")

    if trivial or mechanical_read:
        scope = Scope.LOCAL
    elif system_scope or scope_score >= 3:
        scope = Scope.SYSTEM
    elif multi_scope or scope_score >= 2:
        scope = Scope.MULTI_MODULE
    elif mutation or write_scopes:
        scope = Scope.MODULE
    else:
        scope = Scope.LOCAL

    verification = VerificationStrength.MODERATE
    if _STRONG_VALIDATION.search(text) or trivial or (_MECHANICAL_READ.search(text) and not mutation):
        verification = VerificationStrength.STRONG
        signals.append("strong_validation")
    if _WEAK_VALIDATION.search(text) or (diagnosis and not _STRONG_VALIDATION.search(text)):
        verification = VerificationStrength.WEAK
        reasoning_score += 1
        signals.append("weak_validation")

    complexity = _level(complexity_score + scope_score, 2, 5)
    ambiguity = _level(ambiguity_score, 1, 3)
    reasoning_depth = _level(reasoning_score, 2, 4)
    if destructive and (security or infrastructure or database):
        risk = Risk.CRITICAL
    elif risk_score >= 5:
        risk = Risk.CRITICAL
    elif risk_score >= 3:
        risk = Risk.HIGH
    elif risk_score >= 1:
        risk = Risk.MEDIUM
    else:
        risk = Risk.LOW

    if (
        risk in {Risk.HIGH, Risk.CRITICAL}
        or reasoning_depth is Level.HIGH
        or scope is Scope.SYSTEM
        or verification is VerificationStrength.WEAK and complexity is Level.HIGH
        or verification is VerificationStrength.WEAK and ambiguity is Level.HIGH
        or architecture or concurrency
        or estimated_tokens >= 100_000 and mutation
        or task_type_requires_reasoning(_task_type(text, mutation))
    ):
        tier = RoutingTierName.REASONING
    elif (
        complexity is Level.LOW and ambiguity is Level.LOW and risk is Risk.LOW
        and scope is Scope.LOCAL and verification is VerificationStrength.STRONG
    ):
        tier = RoutingTierName.FAST
    else:
        tier = RoutingTierName.STANDARD

    capabilities = {"conversation"}
    if mutation or diagnosis or architecture or database or security:
        capabilities.add("coding")
    if workflow != "direct-response" and (mutation or diagnosis or architecture or database or security):
        capabilities.update({"repository_read", "shell", "tool_calling"})
    if mutation:
        capabilities.update({"repository_write", "git"})
    if _RESEARCH.search(text):
        capabilities.add("research")
    if estimated_tokens >= 32_000:
        capabilities.add("long_context")
    if _VISION.search(text):
        capabilities.add("vision")
    if _STRUCTURED.search(text):
        capabilities.add("structured_output")

    thresholds = dict(QUALITY_THRESHOLDS)
    if quality_thresholds:
        for key in thresholds:
            raw = quality_thresholds.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0 <= raw <= 1:
                thresholds[key] = float(raw)
    return TaskProfile(
        task_type=_task_type(text, mutation),
        complexity=complexity,
        ambiguity=ambiguity,
        risk=risk,
        scope=scope,
        reasoning_depth=reasoning_depth,
        verification_strength=verification,
        context_requirement=_context_class(estimated_tokens),
        estimated_tokens=estimated_tokens,
        required_capabilities=tuple(sorted(capabilities)),
        minimum_quality=thresholds[tier.value],
        tier=tier,
        signals=tuple(dict.fromkeys(signals)),
        scores={
            "complexity": complexity_score,
            "ambiguity": ambiguity_score,
            "risk": risk_score,
            "scope": scope_score,
            "reasoning": reasoning_score,
        },
    )


def task_type_requires_reasoning(task_type: str) -> bool:
    return task_type in {"security", "concurrency", "database_migration", "architecture"}


def canonical_model_identity(provider: str, model: str) -> tuple[str, str, str, str]:
    """Return provider, canonical model, variant and reasoning effort.

    Variant suffixes deliberately remain distinct; evidence for a base model is
    not silently assigned to lite/high/web variants.
    """
    provider_id = provider.strip().lower()
    raw = model.strip().lower()
    effort = "default"
    for candidate in ("ultra", "max", "xhigh", "high", "medium", "low"):
        if raw.endswith(f":{candidate}") or raw.endswith(f"-{candidate}"):
            effort = candidate
            break
    variant = "base"
    for candidate in ("lite", "mini", "nano", "flash", "pro", "web", "preview"):
        if re.search(rf"(?:^|[-:/]){candidate}(?:$|[-:/])", raw):
            variant = candidate
            break
    canonical = re.sub(r"^(?:[^/]+/)", "", raw)
    return provider_id, canonical, variant, effort


def model_identity_record(provider: str, model: str) -> dict[str, Any]:
    provider_id, canonical, variant, effort = canonical_model_identity(provider, model)
    aliases = sorted({model.strip(), canonical, f"{provider_id}/{canonical}"} - {""})
    return {
        "provider": provider_id,
        "canonical_model": canonical,
        "variant": variant,
        "reasoning_effort": effort,
        "external_aliases": aliases,
    }


def validate_benchmark_evidence(value: Mapping[str, Any]) -> BenchmarkEvidence:
    required = {
        "source", "source_url", "benchmark", "provider", "canonical_model",
        "model_version", "variant", "source_date", "retrieved_at", "confidence", "dimensions",
    }
    if set(value) - (required | {"normalization_version", "raw_metric"}) or not required <= set(value):
        raise ValueError("benchmark record has missing or unknown fields")
    source = str(value["source"])
    if source not in ALLOWLISTED_BENCHMARK_SOURCES:
        raise ValueError("benchmark source is not allowlisted")
    source_url = str(value["source_url"])
    from urllib.parse import urlsplit
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWLISTED_BENCHMARK_SOURCES[source]:
        raise ValueError("benchmark URL is not an allowlisted HTTPS source")
    dimensions = value["dimensions"]
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ValueError("benchmark dimensions must be a non-empty object")
    normalized_dimensions: dict[str, float] = {}
    for key, raw in dimensions.items():
        if key not in BENCHMARK_DIMENSIONS:
            raise ValueError(f"unknown benchmark dimension: {key}")
        score = float(raw)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("normalized benchmark scores must be within [0,1]")
        normalized_dimensions[key] = score
    confidence = float(value["confidence"])
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("benchmark confidence must be within [0,1]")
    timestamps: dict[str, datetime] = {}
    for field_name in ("source_date", "retrieved_at"):
        try:
            parsed_time = datetime.fromisoformat(str(value[field_name]).replace("Z", "+00:00"))
            timestamps[field_name] = (
                parsed_time.replace(tzinfo=timezone.utc)
                if parsed_time.tzinfo is None else parsed_time
            )
        except ValueError as error:
            raise ValueError(f"invalid {field_name}") from error
    if timestamps["source_date"] > timestamps["retrieved_at"]:
        raise ValueError("benchmark source date cannot be after retrieval time")
    normalization = str(value.get("normalization_version", BENCHMARK_NORMALIZATION_VERSION))
    if normalization != BENCHMARK_NORMALIZATION_VERSION:
        raise ValueError("unsupported benchmark normalization version")
    raw_metric = value.get("raw_metric")
    if raw_metric is not None and (
        not isinstance(raw_metric, (str, int, float))
        or isinstance(raw_metric, bool)
        or len(str(raw_metric)) > 200
    ):
        raise ValueError("benchmark raw metric is invalid")
    return BenchmarkEvidence(
        source=source,
        source_url=source_url,
        benchmark=str(value["benchmark"])[:120],
        provider=str(value["provider"])[:120],
        canonical_model=str(value["canonical_model"])[:200],
        model_version=str(value["model_version"])[:120],
        variant=str(value["variant"])[:80],
        source_date=str(value["source_date"]),
        retrieved_at=str(value["retrieved_at"]),
        confidence=min(confidence, SOURCE_RELIABILITY[source]),
        dimensions=normalized_dimensions,
        normalization_version=normalization,
        raw_metric=raw_metric,
    )


def load_benchmark_cache(path: Path) -> tuple[BenchmarkEvidence, ...]:
    if path.is_symlink():
        raise ValueError("benchmark cache must not be a symlink")
    try:
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("benchmark cache exceeds the size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("benchmark cache is invalid") from error
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "records"}:
        raise ValueError("benchmark cache schema is invalid")
    if payload["schema_version"] != EVIDENCE_SCHEMA_VERSION or not isinstance(payload["records"], list):
        raise ValueError("unsupported benchmark cache schema")
    if len(payload["records"]) > MAX_EVIDENCE_RECORDS:
        raise ValueError("benchmark cache contains too many records")
    return tuple(validate_benchmark_evidence(record) for record in payload["records"])


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def save_benchmark_cache(path: Path, records: Iterable[BenchmarkEvidence]) -> str:
    rows = sorted(
        (record.to_dict() for record in records),
        key=lambda row: (row["provider"], row["canonical_model"], row["benchmark"], row["source_date"]),
    )
    if len(rows) > MAX_EVIDENCE_RECORDS:
        raise ValueError("benchmark cache contains too many records")
    payload = {"schema_version": EVIDENCE_SCHEMA_VERSION, "records": rows}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) + 1 > MAX_EVIDENCE_BYTES:
        raise ValueError("benchmark cache exceeds the size limit")
    _atomic_json(path, payload)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def benchmark_quality(
    candidate: ModelCandidate,
    profile: TaskProfile,
    records: Sequence[BenchmarkEvidence],
    *,
    now: datetime | None = None,
) -> tuple[float | None, float]:
    now = now or datetime.now(timezone.utc)
    provider, canonical, variant, _effort = canonical_model_identity(candidate.provider, candidate.model)
    dimensions = {
        "coding_score": 1.0 if "coding" in profile.required_capabilities else 0.2,
        "repository_task_score": 1.0 if "repository_read" in profile.required_capabilities else 0.1,
        "agentic_tool_use_score": 1.0 if "tool_calling" in profile.required_capabilities else 0.1,
        "reasoning_score": {Level.LOW: 0.2, Level.MEDIUM: 0.6, Level.HIGH: 1.0}[profile.reasoning_depth],
        "long_context_score": 1.0 if "long_context" in profile.required_capabilities else 0.1,
        "instruction_following_score": 0.5,
    }
    weighted_score = 0.0
    total_weight = 0.0
    observations: list[tuple[float, float]] = []
    for record in records:
        if record.provider.lower() not in {"*", provider}:
            continue
        if record.canonical_model.lower() != canonical:
            continue
        identity_confidence = 1.0 if record.variant.lower() == variant else 0.5
        try:
            source_time = datetime.fromisoformat(record.source_date.replace("Z", "+00:00"))
            if source_time.tzinfo is None:
                source_time = source_time.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - source_time).total_seconds() / 86_400)
        except ValueError:
            continue
        freshness = max(0.25, math.exp(-age_days / 365.0))
        evidence_confidence = record.confidence * identity_confidence * freshness
        for dimension, relevance in dimensions.items():
            if relevance <= 0 or dimension not in record.dimensions:
                continue
            weight = relevance * evidence_confidence
            weighted_score += record.dimensions[dimension] * weight
            total_weight += weight
            observations.append((record.dimensions[dimension], weight))
    if total_weight <= 0:
        return None, 0.0
    score = weighted_score / total_weight
    variance = sum(weight * (value - score) ** 2 for value, weight in observations) / total_weight
    agreement = max(0.25, 1.0 - 2.0 * math.sqrt(max(0.0, variance)))
    return score, min(1.0, total_weight) * agreement


def local_quality(stats: LocalOutcomeStats | None) -> tuple[float | None, float]:
    if stats is None or stats.validated_success_rate is None:
        return None, 0.0
    return stats.validated_success_rate, stats.confidence


def quality_estimate(
    candidate: ModelCandidate,
    profile: TaskProfile,
    benchmark_records: Sequence[BenchmarkEvidence],
    local_stats: LocalOutcomeStats | None,
    quality_weights: Mapping[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    configured = dict(QUALITY_WEIGHTS)
    if quality_weights:
        for key in configured:
            raw = quality_weights.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
                configured[key] = float(raw)
    benchmark, benchmark_confidence = benchmark_quality(candidate, profile, benchmark_records)
    local, local_confidence = local_quality(local_stats)
    components = {"metadata": min(1.0, max(0.0, candidate.metadata_quality))}
    weights = {"metadata": configured["metadata"]}
    if benchmark is not None:
        components["benchmark"] = benchmark
        weights["benchmark"] = configured["benchmark"] * benchmark_confidence
    if local is not None:
        components["local"] = local
        weights["local"] = configured["local"] * local_confidence
    total = sum(weights.values())
    score = sum(components[key] * weight for key, weight in weights.items()) / max(total, 1e-9)
    return min(1.0, max(0.0, score)), components | {
        "benchmark_confidence": benchmark_confidence,
        "local_confidence": local_confidence,
    }


def initial_attempt_cost(candidate: ModelCandidate) -> float | None:
    if candidate.input_cost_per_million is None or candidate.output_cost_per_million is None:
        return None
    return (
        candidate.expected_input_tokens * candidate.input_cost_per_million
        + candidate.expected_output_tokens * candidate.output_cost_per_million
    ) / 1_000_000


def expected_completion_cost(candidate: ModelCandidate, success_probability: float) -> float | None:
    probability = min(0.999, max(0.05, success_probability))
    attempt = initial_attempt_cost(candidate)
    if attempt is None:
        return None
    # Geometric expected attempts, bounded at three to match Quattro's bounded
    # retry/escalation policy. This captures retry cost without claiming an
    # unbounded theoretical tail.
    expected_attempts = min(3.0, 1.0 / probability)
    escalation_probability = max(0.0, 1.0 - probability)
    escalation_reserve = attempt * 1.5 * escalation_probability
    return attempt * expected_attempts + escalation_reserve


def evaluate_candidates(
    profile: TaskProfile,
    candidates: Sequence[ModelCandidate],
    benchmark_records: Sequence[BenchmarkEvidence] = (),
    local_outcomes: Mapping[tuple[str, str, str, str], LocalOutcomeStats] | None = None,
    *,
    preference: PreferenceMode = PreferenceMode.BALANCED,
    quality_weights: Mapping[str, float] | None = None,
    local_outcome_min_samples: int = 5,
) -> ModelSelection:
    decisions: list[CandidateDecision] = []
    local_outcomes = local_outcomes or {}
    required_quality = profile.minimum_quality + (0.05 if preference is PreferenceMode.QUALITY else 0.0)
    for candidate in candidates:
        reasons: list[str] = []
        if (
            not candidate.provider or not candidate.model
            or "\x00" in candidate.provider or "\x00" in candidate.model
        ):
            reasons.append("invalid_identity")
        if (
            candidate.input_cost_per_million is not None
            and (
                not math.isfinite(candidate.input_cost_per_million)
                or candidate.input_cost_per_million < 0
            )
        ) or (
            candidate.output_cost_per_million is not None
            and (
                not math.isfinite(candidate.output_cost_per_million)
                or candidate.output_cost_per_million < 0
            )
        ) or (
            candidate.expected_input_tokens < 0
            or candidate.expected_output_tokens < 0
        ):
            reasons.append("invalid_pricing")
        missing = sorted(set(profile.required_capabilities) - set(candidate.capabilities))
        if missing:
            reasons.append("missing_capability:" + missing[0])
        if candidate.practical_input_limit is None:
            reasons.append("unknown_context_limit")
        elif (
            candidate.practical_input_limit > 0
            and profile.estimated_tokens > candidate.practical_input_limit
        ):
            reasons.append("insufficient_context")
        if candidate.availability is not Availability.AVAILABLE and not (
            candidate.availability is Availability.RETRY and candidate.retry_eligible
        ):
            reasons.append("unavailable:" + candidate.availability.value)

        stats = local_outcomes.get((candidate.provider, candidate.model, profile.task_type, profile.tier.value))
        if stats is not None and stats.validation_observed < max(1, local_outcome_min_samples):
            stats = None
        estimate, components = quality_estimate(
            candidate, profile, benchmark_records, stats, quality_weights
        )
        if estimate < required_quality:
            reasons.append("below_quality_threshold")
        cost = None if reasons else expected_completion_cost(candidate, estimate)
        quality_confidence = min(1.0, max(
            float(components.get("benchmark_confidence", 0.0)),
            float(components.get("local_confidence", 0.0)),
            QUALITY_WEIGHTS["metadata"],
        ))
        pricing_state = (
            "unknown" if candidate.input_cost_per_million is None or candidate.output_cost_per_million is None
            else "known"
        )
        decisions.append(CandidateDecision(
            provider=candidate.provider,
            model=candidate.model,
            eligible=not reasons,
            rejection_reasons=tuple(reasons),
            quality_estimate=estimate,
            quality_components=components,
            expected_completion_cost=cost,
            latency_ms=(
                max(0.0, candidate.latency_ms)
                if math.isfinite(candidate.latency_ms) else math.inf
            ),
            quality_confidence=quality_confidence,
            pricing_state=pricing_state,
        ))

    eligible = [decision for decision in decisions if decision.eligible]
    eligible.sort(key=lambda decision: (
        decision.expected_completion_cost if decision.expected_completion_cost is not None else math.inf,
        decision.latency_ms * (0.5 if profile.tier is RoutingTierName.FAST else 1.0),
        decision.provider,
        decision.model,
    ))
    ranks = {(decision.provider, decision.model): index + 1 for index, decision in enumerate(eligible)}
    decisions = [
        replace(decision, rank=ranks.get((decision.provider, decision.model)))
        for decision in decisions
    ]
    eligible = [decision for decision in decisions if decision.eligible]
    eligible.sort(key=lambda decision: decision.rank or math.inf)
    if not eligible:
        return ModelSelection(None, None, "no candidate satisfied every hard gate and quality floor", tuple(decisions))
    winner = eligible[0]
    return ModelSelection(
        winner.provider,
        winner.model,
        "lowest expected completion cost among candidates satisfying capabilities, context, availability, and quality",
        tuple(decisions),
    )


def routing_snapshot(
    profile: TaskProfile,
    *,
    route: str,
    configured_model: str | None,
    preference: PreferenceMode = PreferenceMode.BALANCED,
    benchmark_version: str = "none",
    local_outcomes_version: str = "none",
    candidate_metadata_version: str = "omniroute-interface-unavailable",
    selection: ModelSelection | None = None,
    compatibility_mode: str = "standard",
    actual_selection: Mapping[str, Any] | None = None,
    adaptive_overhead_ms: float = 0.0,
    adaptive_cache_hit: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "benchmark_normalization_version": BENCHMARK_NORMALIZATION_VERSION,
        "task_profile": profile.to_dict(),
        "preference_mode": preference.value,
        "configured_model": configured_model,
        "effective_route": route,
        "candidate_metadata_version": candidate_metadata_version,
        "benchmark_snapshot_version": benchmark_version,
        "local_outcome_stats_version": local_outcomes_version,
        "selection": selection.to_dict() if selection else None,
        "compatibility_mode": compatibility_mode,
        "actual_selection": dict(actual_selection) if actual_selection else None,
        "adaptive_overhead_ms": max(0.0, float(adaptive_overhead_ms)),
        "adaptive_cache_hit": bool(adaptive_cache_hit),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return payload | {"decision_id": "route-" + hashlib.sha256(canonical).hexdigest()[:20]}


def replay_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported routing snapshot schema")
    if snapshot.get("routing_policy_version") != ROUTING_POLICY_VERSION:
        raise ValueError("routing policy version is not available for deterministic replay")
    profile_data = snapshot.get("task_profile")
    if not isinstance(profile_data, Mapping):
        raise ValueError("routing snapshot has no task profile")
    tier = str(profile_data.get("tier"))
    route = {
        "FAST": "auto/coding:cheap",
        "STANDARD": "auto/coding",
        "REASONING": "auto/reasoning",
    }.get(tier)
    configured = snapshot.get("configured_model")
    expected = str(snapshot.get("effective_route"))
    replayed = route if configured == "auto" else str(configured or "configured default")
    selection = snapshot.get("selection")
    preferred = []
    if isinstance(selection, Mapping) and isinstance(selection.get("candidates"), list):
        preferred = [
            f"{row.get('provider')}/{row.get('model')}"
            for row in selection["candidates"]
            if isinstance(row, Mapping) and row.get("eligible") is True and row.get("rank") is not None
        ]
        preferred.sort(key=lambda candidate: next(
            int(row["rank"]) for row in selection["candidates"]
            if isinstance(row, Mapping) and f"{row.get('provider')}/{row.get('model')}" == candidate
        ))
    return {
        "decision_id": snapshot.get("decision_id"),
        "policy_version": ROUTING_POLICY_VERSION,
        "expected_route": expected,
        "replayed_route": replayed,
        "matches": replayed == expected,
        "compatibility_mode": snapshot.get("compatibility_mode", "standard"),
        "preferred_candidates": preferred,
        "actual_selection": snapshot.get("actual_selection"),
    }


def outcome_key(provider: str, model: str, task_type: str, tier: str) -> str:
    return "\0".join((provider, model, task_type, tier))


def load_local_outcomes(path: Path) -> dict[tuple[str, str, str, str], LocalOutcomeStats]:
    if path.is_symlink():
        raise ValueError("local outcome store must not be a symlink")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("local outcome store is invalid") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1 or not isinstance(payload.get("aggregates"), Mapping):
        raise ValueError("local outcome store schema is invalid")
    result: dict[tuple[str, str, str, str], LocalOutcomeStats] = {}
    for key, row in payload["aggregates"].items():
        parts = str(key).split("\0")
        if len(parts) != 4 or not isinstance(row, Mapping):
            raise ValueError("local outcome aggregate is invalid")
        numeric = {name: row.get(name, 0) for name in (
            "samples", "execution_successes", "validated_successes", "validation_observed",
            "retries", "escalations", "latency_ms_total", "cost_total",
            "cost_observed", "cost_unknown",
        )}
        if "cost_observed" not in row and "cost_unknown" not in row:
            # Legacy schema stored an unconditional numeric zero even when no
            # cost metadata existed. Treat every legacy sample as unknown; do
            # not reinterpret that sentinel as a free request.
            numeric["cost_unknown"] = numeric["samples"]
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 for value in numeric.values()):
            raise ValueError("local outcome counters must be non-negative numbers")
        result[tuple(parts)] = LocalOutcomeStats(
            parts[0], parts[1], parts[2], parts[3],
            int(numeric["samples"]), int(numeric["execution_successes"]),
            int(numeric["validated_successes"]), int(numeric["validation_observed"]),
            int(numeric["retries"]), int(numeric["escalations"]),
            float(numeric["latency_ms_total"]), float(numeric["cost_total"]),
            int(numeric["cost_observed"]), int(numeric["cost_unknown"]),
        )
    return result


def record_local_outcome(
    path: Path,
    *,
    provider: str,
    model: str,
    task_type: str,
    tier: str,
    execution_success: bool,
    validated_success: bool | None,
    retries: int = 0,
    escalations: int = 0,
    latency_ms: float = 0,
    cost: float | None = None,
) -> LocalOutcomeStats:
    if any(not value or "\x00" in value for value in (provider, model, task_type, tier)):
        raise ValueError("local outcome identity fields must be non-empty and NUL-free")
    if retries < 0 or escalations < 0:
        raise ValueError("local outcome retry counters must be non-negative")
    if (
        not math.isfinite(latency_ms) or latency_ms < 0
        or cost is not None and (not math.isfinite(cost) or cost < 0)
    ):
        raise ValueError("local outcome latency and cost must be finite non-negative numbers")
    existing = load_local_outcomes(path)
    key_tuple = (provider[:120], model[:200], task_type[:80], tier[:20])
    prior = existing.get(key_tuple, LocalOutcomeStats(*key_tuple, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0))
    updated = LocalOutcomeStats(
        *key_tuple,
        prior.samples + 1,
        prior.execution_successes + int(execution_success),
        prior.validated_successes + int(validated_success is True),
        prior.validation_observed + int(validated_success is not None),
        prior.retries + max(0, retries),
        prior.escalations + max(0, escalations),
        prior.latency_ms_total + max(0.0, latency_ms),
        prior.cost_total + (max(0.0, cost) if cost is not None else 0.0),
        prior.cost_observed + int(cost is not None),
        prior.cost_unknown + int(cost is None),
    )
    existing[key_tuple] = updated
    aggregates = {
        outcome_key(*key): {
            "samples": row.samples,
            "execution_successes": row.execution_successes,
            "validated_successes": row.validated_successes,
            "validation_observed": row.validation_observed,
            "retries": row.retries,
            "escalations": row.escalations,
            "latency_ms_total": row.latency_ms_total,
            "cost_total": row.cost_total,
            "cost_observed": row.cost_observed,
            "cost_unknown": row.cost_unknown,
        }
        for key, row in sorted(existing.items())
    }
    _atomic_json(path, {"schema_version": 1, "aggregates": aggregates})
    return updated
