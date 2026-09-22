"""Validated Quattro-owned execution targets and deterministic selection.

The registry contains policy and non-secret resource aliases only.  Provider
credentials remain in their native stores.  Every route is cross-checked
against the installed Codex catalog before it can be selected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .errors import ConfigError
from .routing_intelligence import TaskProfile


MAX_POLICY_BYTES = 256_000
_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_ROUTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


@dataclass(frozen=True, slots=True)
class ModelTarget:
    route: str
    provider: str
    account: str
    model: str
    capabilities: frozenset[str]
    tiers: frozenset[str]
    context_limit: int
    cost_rank: int
    priority: int
    reliability: float | None = None


@dataclass(frozen=True, slots=True)
class ExecutionTarget:
    mode: str
    provider: str
    account: str
    model: str
    route: str
    tier: str
    reason: str
    fallbacks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fallbacks"] = list(self.fallbacks)
        return value


@dataclass(frozen=True, slots=True)
class ContextDecision:
    """Quattro-owned semantic context contract."""

    strategy: str
    budget_tokens: int
    conversation_budget_tokens: int
    retrieval_budget_tokens: int


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Final authoritative decision handed to the inference gateway.

    A gateway may retry transport for this exact target, but changing any target
    field or reasoning effort requires Quattro to issue a new plan.
    """

    plan_id: str
    task_category: str
    task_complexity: str
    target: ExecutionTarget
    reasoning_effort: str
    context: ContextDecision
    required_tools: tuple[str, ...]
    fallback_allowed: bool
    fallback_targets: tuple[ExecutionTarget, ...]
    routing_locked: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "task": {"category": self.task_category, "complexity": self.task_complexity},
            "target": self.target.to_dict(),
            "reasoning": {"effort": self.reasoning_effort},
            "context": {
                "strategy": self.context.strategy,
                "budgetTokens": self.context.budget_tokens,
                "conversationBudgetTokens": self.context.conversation_budget_tokens,
                "retrievalBudgetTokens": self.context.retrieval_budget_tokens,
            },
            "tools": {"required": list(self.required_tools)},
            "fallback": {
                "allowed": self.fallback_allowed,
                "targets": [item.to_dict() for item in self.fallback_targets],
            },
            "routingLocked": self.routing_locked,
        }


def build_execution_plan(
    profile: TaskProfile,
    target: ExecutionTarget,
    targets: Sequence[ModelTarget],
    *,
    reasoning_effort: str,
    plan_id: str,
) -> ExecutionPlan:
    """Materialize one immutable plan from an already selected exact target."""
    if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
        raise ConfigError("execution plan reasoning effort is unsupported")
    by_route = {item.route: item for item in targets}

    def exact(route: str, reason: str) -> ExecutionTarget:
        item = by_route.get(route)
        if item is None:
            raise ConfigError(f"execution plan fallback is not approved: {route}")
        return ExecutionTarget(
            mode="FALLBACK", provider=item.provider, account=item.account,
            model=item.model, route=item.route, tier=profile.tier.value,
            reason=reason, fallbacks=(),
        )

    fallback_targets = tuple(
        exact(route, f"Quattro fallback from {target.route}") for route in target.fallbacks
    )
    strategy = {
        "CHAT_MINIMAL": "minimal",
        "CODE_SIMPLE": "normal",
        "REPOSITORY_EXECUTION": "deep",
        "SECURITY_REVIEW": "deep",
        "DESIGN": "normal",
    }.get(profile.context_profile.value, "normal")
    budget = max(profile.final_request_tokens, profile.task_context_tokens)
    retrieval = 0 if strategy == "minimal" else max(0, budget // (2 if strategy == "deep" else 3))
    conversation = max(0, budget - retrieval)
    tool_capabilities = {"shell", "git", "tool_calling", "repository_read", "repository_write"}
    required_tools = tuple(sorted(set(profile.required_capabilities) & tool_capabilities))
    return ExecutionPlan(
        plan_id=plan_id,
        task_category=profile.task_type,
        task_complexity=profile.complexity.value,
        target=target,
        reasoning_effort=reasoning_effort,
        context=ContextDecision(strategy, budget, conversation, retrieval),
        required_tools=required_tools,
        fallback_allowed=bool(fallback_targets),
        fallback_targets=fallback_targets,
    )


def fallback_execution_plan(plan: ExecutionPlan, index: int, *, reason: str) -> ExecutionPlan:
    """Create a new auditable Quattro plan for one approved fallback target."""
    if not plan.fallback_allowed or index < 0 or index >= len(plan.fallback_targets):
        raise ConfigError("execution plan has no such fallback")
    target = plan.fallback_targets[index]
    remaining = plan.fallback_targets[index + 1 :]
    return ExecutionPlan(
        plan_id=f"{plan.plan_id}.fallback-{index + 1}",
        task_category=plan.task_category,
        task_complexity=plan.task_complexity,
        target=target,
        reasoning_effort=plan.reasoning_effort,
        context=plan.context,
        required_tools=plan.required_tools,
        fallback_allowed=bool(remaining),
        fallback_targets=remaining,
        routing_locked=True,
    )


def default_policy_path() -> Path:
    override = os.environ.get("QUATTRO_MODEL_POLICY")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve(strict=False)
    return Path(__file__).with_name("data") / "model-policy.json"


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if path.is_symlink():
        raise ConfigError(f"{label} must not be a symlink")
    try:
        if path.stat().st_size > MAX_POLICY_BYTES:
            raise ConfigError(f"{label} exceeds the safe size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{label} is invalid") from error
    if not isinstance(value, Mapping):
        raise ConfigError(f"{label} must be an object")
    return value


def load_model_registry(policy_path: Path, catalog_path: Path) -> tuple[ModelTarget, ...]:
    """Load policy and reject any target not present in the approved catalog."""
    policy = _load_json(policy_path, "model policy")
    catalog = _load_json(catalog_path, "model catalog")
    if policy.get("schemaVersion") != 1 or not isinstance(policy.get("targets"), list):
        raise ConfigError("model policy schema is unsupported")
    catalog_rows = {
        row.get("slug"): row for row in catalog.get("models", [])
        if isinstance(row, Mapping) and isinstance(row.get("slug"), str)
    }
    result: list[ModelTarget] = []
    seen: set[str] = set()
    for index, raw in enumerate(policy["targets"]):
        where = f"model policy target {index}"
        if not isinstance(raw, Mapping):
            raise ConfigError(f"{where} must be an object")
        allowed = {
            "route", "provider", "account", "model", "capabilities", "tiers",
            "costRank", "priority", "reliability",
        }
        if set(raw) - allowed:
            raise ConfigError(f"{where} contains unknown fields")
        route = raw.get("route")
        provider = raw.get("provider")
        account = raw.get("account")
        model = raw.get("model")
        if not all(isinstance(v, str) for v in (route, provider, account, model)):
            raise ConfigError(f"{where} identity is invalid")
        if not _ROUTE.fullmatch(route) or not all(_ID.fullmatch(v) for v in (provider, account, model)):
            raise ConfigError(f"{where} identity is invalid")
        if route in seen or route not in catalog_rows:
            raise ConfigError(f"{where} route is duplicate or absent from the approved catalog")
        if not route.startswith(account + "/"):
            raise ConfigError(f"{where} route is not pinned to its account alias")
        expected_model = route.split("/", 1)[1]
        if provider != "codex" or model != expected_model:
            raise ConfigError(f"{where} provider/model identity does not match its catalog route")
        seen.add(route)
        capabilities = raw.get("capabilities")
        tiers = raw.get("tiers")
        if not isinstance(capabilities, list) or not capabilities or not all(isinstance(v, str) for v in capabilities):
            raise ConfigError(f"{where} capabilities are invalid")
        if not isinstance(tiers, list) or not tiers or not set(tiers) <= {"FAST", "STANDARD", "REASONING"}:
            raise ConfigError(f"{where} tiers are invalid")
        row = catalog_rows[route]
        limits = [row.get("context_window"), row.get("max_context_window")]
        limits = [v for v in limits if isinstance(v, int) and not isinstance(v, bool) and v > 0]
        if not limits:
            raise ConfigError(f"{where} has no verified context limit")
        verified_capabilities = {"conversation"}
        if row.get("shell_type") == "shell_command" and row.get("tool_mode") == "code_mode_only":
            verified_capabilities.update({
                "coding", "repository_read", "repository_write", "shell", "git",
                "tool_calling",
            })
        reasoning_levels = row.get("supported_reasoning_levels")
        if isinstance(reasoning_levels, list) and reasoning_levels:
            verified_capabilities.add("reasoning")
        if min(limits) >= 32_000:
            verified_capabilities.add("long_context")
        modalities = row.get("input_modalities")
        if isinstance(modalities, list) and "image" in modalities:
            verified_capabilities.add("vision")
        unsupported = sorted(set(capabilities) - verified_capabilities)
        if unsupported:
            raise ConfigError(
                f"{where} claims capabilities absent from trusted catalog metadata: "
                + ", ".join(unsupported)
            )
        cost_rank = raw.get("costRank")
        priority = raw.get("priority")
        reliability = raw.get("reliability")
        if type(cost_rank) is not int or cost_rank < 0 or type(priority) is not int or priority < 0:
            raise ConfigError(f"{where} ordering metadata is invalid")
        if reliability is not None and (not isinstance(reliability, (int, float)) or isinstance(reliability, bool) or not 0 <= float(reliability) <= 1):
            raise ConfigError(f"{where} reliability is invalid")
        result.append(ModelTarget(
            route=route, provider=provider, account=account, model=model,
            capabilities=frozenset(capabilities), tiers=frozenset(tiers),
            context_limit=min(limits), cost_rank=cost_rank, priority=priority,
            reliability=None if reliability is None else float(reliability),
        ))
    if not result:
        raise ConfigError("model policy contains no targets")
    return tuple(result)


def select_execution_target(
    profile: TaskProfile,
    targets: Sequence[ModelTarget],
    *,
    preferred_account: str | None,
    available_accounts: frozenset[str] | None = None,
    unavailable_routes: frozenset[str] = frozenset(),
) -> ExecutionTarget:
    """Choose the cheapest verified capable target and bounded fallbacks."""
    required = set(profile.required_capabilities)
    eligible = [
        target for target in targets
        if profile.tier.value in target.tiers
        and (available_accounts is None or target.account in available_accounts)
        and target.route not in unavailable_routes
        and required <= set(target.capabilities)
        and profile.final_request_tokens <= target.context_limit
    ]
    if not eligible:
        raise ConfigError("no configured execution target satisfies the request")
    eligible.sort(key=lambda target: (
        target.cost_rank,
        0 if target.account == preferred_account else 1,
        -(target.reliability if target.reliability is not None else 0.0),
        target.priority,
        target.route,
    ))
    selected = eligible[0]
    fallbacks = tuple(target.route for target in eligible[1:8])
    return ExecutionTarget(
        mode="EXPLICIT", provider=selected.provider, account=selected.account,
        model=selected.model, route=selected.route, tier=profile.tier.value,
        reason=(
            "lowest configured cost rank among verified capable, context-compatible, "
            "tier-eligible targets"
        ),
        fallbacks=fallbacks,
    )


def target_matches_actual(
    target: ExecutionTarget, *, actual_provider: str | None, actual_model: str | None,
    actual_account: str | None = None,
) -> bool:
    """Compare exact normalized provider/model identity without fuzzy matching."""
    provider_aliases = {"codex": "codex", "cx": "codex"}
    expected_provider = provider_aliases.get(target.provider.lower(), target.provider.lower())
    observed_provider = provider_aliases.get(
        (actual_provider or "").lower(), (actual_provider or "").lower()
    )
    account_matches = actual_account is None or target.account == actual_account
    return (
        expected_provider == observed_provider
        and target.model == (actual_model or "")
        and account_matches
    )


def execution_target_for_route(
    profile: TaskProfile,
    targets: Sequence[ModelTarget],
    route: str,
    *,
    available_accounts: frozenset[str] | None = None,
) -> ExecutionTarget | None:
    """Return a no-fallback exact contract for a user-selected registry route."""
    target = next((item for item in targets if item.route == route), None)
    if target is None:
        return None
    if available_accounts is not None and target.account not in available_accounts:
        raise ConfigError(f"manual execution target account is disabled: {target.account}")
    # A manual route is explicit user intent. Capability validation remains at
    # the existing catalog/provider preflight boundary so Quattro does not
    # silently replace it with a different model.
    if profile.final_request_tokens > target.context_limit:
        raise ConfigError(f"manual execution target context is insufficient: {route}")
    return ExecutionTarget(
        mode="MANUAL", provider=target.provider, account=target.account,
        model=target.model, route=target.route, tier=profile.tier.value,
        reason="explicit user-selected account-qualified route", fallbacks=(),
    )
