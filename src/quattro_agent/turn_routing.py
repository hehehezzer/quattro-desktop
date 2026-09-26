"""Canonical request-boundary routing: one analysis, one policy, one locked plan.

Frontends supply presentation metadata and runtime constraints, not routing
answers. Downstream transports consume the returned plan without re-analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence

from .delegation import TaskDelegationDecision, classify_task_request
from .intelligence.features import extract_decision_features, SAFE_FEATURES
from .intelligence.telemetry import sanitize_request, redact_request_credentials
from .jev import serialize_features
from .jev_shadow import annotate
from .model_registry import (
    ExecutionPlan, ModelTarget, build_execution_plan, execution_target_for_route,
    select_execution_target,
)
from .routing import RoutingDecision, RoutingTier
from .routing_intelligence import (
    ContextProfile, RoutingTierName, profile_task, task_profile_from_dict,
    make_pre_routing_input,
)
from .routing_signals import classify_with_signals
from .errors import ConfigError

CREDENTIAL_RESPONSE = (
    "No approved local credential lookup is configured for this session. "
    "Use the OmniRoute dashboard credential source or its password reset procedure."
)
_SECRET = re.compile(r"(?i)\b(password|passwd|api[ _-]?key|access[ _-]?token|secret|credential)\b")
_DEEP = re.compile(r"(?i)\b(prove|derive|rigorous|trade.?offs?|detailed analysis)\b")


def active_account_health(path: Path) -> dict:
    """Existing private health snapshot, bounded and read-only at the turn gate."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(256_001)
        if len(raw) > 256_000:
            return {}
        payload = json.loads(raw)
        rows = payload.get('routes', {}) if isinstance(payload, dict) else {}
        if not isinstance(rows, dict):
            return {}
        active = {}
        now = datetime.now(timezone.utc)
        for route, row in rows.items():
            if not isinstance(route, str) or not isinstance(row, dict):
                continue
            try:
                expires = datetime.fromisoformat(str(row.get('expiresAt')))
                expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if expires > now:
                active[route] = row
        return active
    except (OSError, ValueError, TypeError):
        return {}


@dataclass(frozen=True, slots=True)
class TurnRoutingFeatures:
    """Immutable local state. Classifiers see only the allowlisted projections."""
    request: str = field(repr=False)
    local_json: str = field(repr=False)
    state_json: str
    profile_json: str
    gate: TaskDelegationDecision
    sensitive: bool
    credential_lookup: bool
    extraction_ms: float
    schema_version: str = "quattro-turn-features-v1"

    def local_projection(self) -> dict:
        return json.loads(self.local_json)


def extract_turn_features(request: str, *, agent="codex", workflow="general-task",
                          policy_name="workspace-write", config=None,
                          write_scopes=()) -> TurnRoutingFeatures:
    started = time.perf_counter()
    if not isinstance(request, str) or len(request) > 64_000 or '\x00' in request:
        raise ValueError("turn input exceeds supported bounds")
    # Existing lexical extractors are collected once here. No model or telemetry
    # adapter may invoke them again for this evaluation.
    safe, _normalized = sanitize_request(request)
    _, redacted = redact_request_credentials(request)
    requirements = extract_decision_features(safe)
    model_input = {"request_text": safe, "request_length": len(safe),
                   "estimated_tokens": (len(safe) + 3) // 4,
                   **{name: requirements[name] for name in SAFE_FEATURES
                      if name not in {"request_text", "request_length", "estimated_tokens"}}}
    gate = classify_task_request(request, preferred_agent=agent)
    sensitive = bool(redacted or _SECRET.search(request) and re.search(
        r"(?i)\b(my|dashboard|show|retrieve|look up|find|stored|configured)\b", request,
    ))
    lookup = bool(_SECRET.search(request) and (
        gate.decision == "DIRECT" and sensitive or re.search(
            r"(?i)\b(show|read|find|retrieve|search|inspect|look up)\b.{0,160}"
            r"\b(password|credential|api[ _-]?key|secret|token)\b", request,
        )
    ))
    if lookup:
        sensitive = True
        gate = TaskDelegationDecision("DIRECT", "credential_lookup_requires_approved_source", 1.0, None)
    profile = profile_task(
        request, agent=agent, workflow=workflow, policy_name=policy_name,
        write_scopes=write_scopes,
        quality_thresholds=(config or {}).get("routing", {}).get("qualityThresholds"),
    )
    return TurnRoutingFeatures(
        request, json.dumps(model_input, sort_keys=True, separators=(",", ":")),
        serialize_features(requirements, request=safe),
        json.dumps(profile.to_dict(), sort_keys=True, separators=(",", ":")),
        gate, sensitive, lookup, (time.perf_counter() - started) * 1000,
    )


def profile_from_plan(plan: ExecutionPlan):
    """Read a frozen profile; legacy plans project only their existing contract.

    This is not inference: no request text or classifier is consulted.
    """
    snapshot = json.loads(plan.profile_json)
    if snapshot:
        return task_profile_from_dict(snapshot)
    return task_profile_from_dict({
        "task_type": plan.task_category,
        "complexity": {"simple": "low", "moderate": "medium", "complex": "high"}.get(
            plan.task_complexity, plan.task_complexity,
        ),
        "ambiguity": "low", "risk": "low", "scope": "local",
        "reasoning_depth": "low", "verification_strength": "moderate",
        "context_requirement": "small", "estimated_tokens": plan.context.budget_tokens,
        "task_context_tokens": plan.context.budget_tokens, "protocol_overhead_tokens": 0,
        "final_request_tokens": plan.context.budget_tokens,
        "context_profile": "CHAT_MINIMAL" if plan.context.strategy == "minimal" else "CODE_SIMPLE",
        "required_capabilities": sorted({"conversation", *plan.required_tools}),
        "minimum_quality": {"FAST": .45, "STANDARD": .65, "REASONING": .80}[plan.target.tier],
        "tier": plan.target.tier, "signals": ["legacy_locked_plan_projection"], "scores": {},
    })


@dataclass(frozen=True, slots=True)
class RoutedTurn:
    """Routing evidence plus exactly one immutable execution contract."""
    plan: ExecutionPlan
    routing: RoutingDecision
    decision: TaskDelegationDecision
    features: TurnRoutingFeatures
    fast_guard: str
    routing_ms: float


def route_turn(*, request: str, config: Mapping, registry: Sequence[ModelTarget],
               account: str, database: Path, selected_model: str | None = None,
               agent="codex", workflow="general-task", policy_name="workspace-write",
               features: TurnRoutingFeatures | None = None, execution_type: str | None = None,
               minimal_direct: bool = True, direct_fallback: bool = False, unavailable_routes=frozenset(),
               plan_id: str | None = None, write_scopes=(),
               effort_resolver: Callable | None = None,
               runtime_filter: Callable | None = None) -> RoutedTurn:
    """The sole request routing/selection entrypoint for native and harness paths.

    ``execution_type`` is a hard entrypoint constraint (explicit durable worker
    tasks), not a probabilistic override. ``features`` is only for ingestion that
    must choose direct versus durable handling before allocating resources.
    """
    started = time.perf_counter()
    features = features or extract_turn_features(
        request, agent=agent, workflow=workflow, policy_name=policy_name,
        config=config, write_scopes=write_scopes,
    )
    if features.request != request:
        raise ConfigError("routing features belong to a different request")
    decision = features.gate
    if execution_type is not None:
        decision = TaskDelegationDecision(execution_type, decision.reason, decision.confidence,
                                          agent if execution_type == "DELEGATE" else None)
    if features.credential_lookup and decision.decision != "DIRECT":
        raise ConfigError("credential lookup cannot enter a delegated lifecycle")
    profile = task_profile_from_dict(json.loads(features.profile_json))
    if minimal_direct and decision.decision == "DIRECT":
        tier = "STANDARD" if len(request) > 4_000 or _DEEP.search(request) else "FAST"
        profile = replace(profile, tier=RoutingTierName(tier),
                          required_capabilities=("conversation",), context_profile=ContextProfile.CHAT_MINIMAL)
    baseline = RoutingDecision(RoutingTier(profile.tier.value), decision.reason,
                               {"FAST": "low", "STANDARD": "medium", "REASONING": "high"}[profile.tier.value],
                               task_profile=profile.to_dict())
    accounts = (frozenset(str(row["id"]) for row in config["accounts"] if row.get("enabled", True))
                if "accounts" in config else frozenset({account}))
    selected_model = selected_model or "auto"
    guard_started = time.perf_counter()
    guard = "eligible"
    if features.sensitive:
        guard = "protected_local"
    elif decision.decision == "DIRECT" and (decision.confidence >= .90 or not any(
        features.local_projection()[name] for name in ("tool_required", "multi_step_required", "retrieval_required")
    )):
        guard = "conclusive_direct"
    elif selected_model != "auto":
        guard = "explicit_target"
    elif profile.tier.value == "REASONING":
        guard = "deterministic_ceiling"
    elif profile.complexity.value == "low":
        guard = "conclusive_requirements"
    guard_ms = (time.perf_counter() - guard_started) * 1000
    constraints = unavailable_routes
    if runtime_filter and guard != "protected_local":
        constraints = frozenset(constraints) | frozenset(runtime_filter(baseline))
    def select(proposed):
        candidate = task_profile_from_dict(proposed.task_profile)
        if selected_model not in {"auto", "auto/coding:cheap", "auto/coding", "auto/reasoning"}:
            target = execution_target_for_route(candidate, registry, selected_model, available_accounts=accounts)
            if target is None or target.route in constraints:
                raise ConfigError("selected model is not an available approved Quattro target")
            return target
        return select_execution_target(
            candidate, registry, preferred_account=account, available_accounts=accounts,
            unavailable_routes=constraints, selection_tier={
                "auto/coding:cheap": "FAST", "auto/coding": "STANDARD", "auto/reasoning": "REASONING",
            }.get(selected_model),
        )
    def available(proposed):
        try:
            return bool(select(proposed))
        except (ConfigError, ValueError):
            return False
    final = classify_with_signals(
        pre_routing_input=make_pre_routing_input(
            request=request, working_directory="", repository_present=False,
            explicit_model=selected_model, routing_mode="auto" if selected_model == "auto" else "manual",
            agent=agent, workflow=workflow, policy_name=policy_name,
        ), config=config, database=database, execution=decision.decision,
        baseline_override=baseline, can_select=available,
        canonical_features=features, eligible=guard == "eligible",
    )
    selection_started = time.perf_counter()
    target = select(final)
    effort = (effort_resolver(final, target) if effort_resolver else
              "high" if "astra" in target.model and target.tier == "STANDARD" else
              {"FAST": "low", "STANDARD": "medium", "REASONING": "high"}[target.tier])
    final = replace(final, tier=RoutingTier(target.tier), reasoning_effort=effort)
    plan = build_execution_plan(
        task_profile_from_dict(final.task_profile), target, registry,
        reasoning_effort=effort, plan_id=plan_id or str(uuid.uuid4()),
        direct=minimal_direct and decision.decision == "DIRECT", direct_fallback=direct_fallback,
    )
    annotate(
        turn_id=plan.plan_id, plan_id=plan.plan_id, fast_guard_result=guard,
        feature_extraction_ms=features.extraction_ms, fast_guard_ms=guard_ms,
        target_selection_ms=(time.perf_counter() - selection_started) * 1000,
        routing_total_ms=(time.perf_counter() - started) * 1000,
        final_decision={"execution": decision.decision, "worker": decision.required_agent,
                        "provider": target.provider, "account": target.account, "model": target.model,
                        "reasoning_effort": effort},
    )
    return RoutedTurn(plan, final, decision, features, guard, (time.perf_counter() - started) * 1000)
