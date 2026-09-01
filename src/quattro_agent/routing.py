"""Deterministic, evidence-ready request routing for Quattro.

Quattro selects only a reasoning tier.  OmniRoute remains the authority for
provider, account, quota, and cost routing behind the selected request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Mapping

from .routing_intelligence import profile_task


class RoutingTier(StrEnum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    REASONING = "REASONING"


_TIER_ORDER = (RoutingTier.FAST, RoutingTier.STANDARD, RoutingTier.REASONING)
_NORMAL_EFFORT = {
    RoutingTier.FAST: "low",
    RoutingTier.STANDARD: "medium",
    RoutingTier.REASONING: "high",
}
_DEFAULT_CONTEXT_BUDGETS = {
    RoutingTier.FAST: 1_200,
    RoutingTier.STANDARD: 2_500,
    RoutingTier.REASONING: 4_000,
}

@dataclass(frozen=True, slots=True)
class RoutingDecision:
    tier: RoutingTier
    reason: str
    reasoning_effort: str
    automatic_escalations: int = 0
    exceptional_escalations: int = 0
    task_profile: Mapping[str, object] = field(default_factory=dict)

    def display(self) -> dict[str, object]:
        return asdict(self) | {"tier": self.tier.value}


def _effort(config: Mapping[str, object], tier: RoutingTier) -> str:
    """Return Quattro's fixed normal effort for a tier."""
    del config
    return _NORMAL_EFFORT[tier]


def effective_reasoning_effort(
    config: Mapping[str, object], routing: Mapping[str, object],
) -> str:
    """Resolve Quattro's authoritative effort immediately before dispatch.

    Native Codex configuration is deliberately not an input. Normal work uses
    the fixed tier mapping; only one already-recorded, evidence-gated
    REASONING escalation may select Quattro's exceptional configured effort.
    """
    try:
        tier = RoutingTier(str(routing.get("tier", RoutingTier.STANDARD.value)))
    except ValueError:
        tier = RoutingTier.STANDARD
    try:
        exceptional = int(routing.get("exceptional_escalations", 0))
    except (TypeError, ValueError):
        exceptional = 0
    configured = config.get("routing")
    if tier is RoutingTier.REASONING and exceptional == 1 and isinstance(configured, Mapping):
        value = configured.get("exceptionalReasoningEffort")
        if value in {"xhigh", "max", "ultra"}:
            return str(value)
    return _NORMAL_EFFORT[tier]


def context_budget_tokens(config: Mapping[str, object], tier: RoutingTier) -> int:
    """Return a validated supplemental-context budget for the request tier."""
    routing = config.get("routing")
    key = {
        RoutingTier.FAST: "fastContextBudgetTokens",
        RoutingTier.STANDARD: "standardContextBudgetTokens",
        RoutingTier.REASONING: "reasoningContextBudgetTokens",
    }[tier]
    value = routing.get(key) if isinstance(routing, Mapping) else None
    if isinstance(value, int) and not isinstance(value, bool) and 512 <= value <= 16_000:
        return value
    return _DEFAULT_CONTEXT_BUDGETS[tier]


def classify_request(
    *,
    request: str,
    config: Mapping[str, object],
    agent: str,
    workflow: str,
    policy_name: str,
) -> RoutingDecision:
    """Classify from a transparent multi-signal :class:`TaskProfile`.

    Regexes remain bounded signal detectors inside ``profile_task``; no single
    keyword is tier authority.  This wrapper preserves the mature public
    ``RoutingDecision`` contract used by the harness and existing sessions.
    """
    routing_config = config.get("routing")
    thresholds = (
        routing_config.get("qualityThresholds")
        if isinstance(routing_config, Mapping) else None
    )
    profile = profile_task(
        request,
        agent=agent,
        workflow=workflow,
        policy_name=policy_name,
        quality_thresholds=thresholds if isinstance(thresholds, Mapping) else None,
    )
    tier = RoutingTier(profile.tier.value)
    reason = {
        RoutingTier.FAST: "low-risk localized task with strong verification",
        RoutingTier.STANDARD: "bounded engineering task requiring normal capability",
        RoutingTier.REASONING: "high reasoning, risk, scope, ambiguity, or weak-verification requirement",
    }[tier]
    return RoutingDecision(
        tier=tier,
        reason=reason,
        reasoning_effort=_effort(config, tier),
        task_profile=profile.to_dict(),
    )


def next_tier(decision: RoutingDecision, *, evidence: str, max_automatic_escalations: int) -> RoutingDecision | None:
    """Return one bounded escalation only when supplied evidence warrants it."""
    if decision.automatic_escalations >= max_automatic_escalations:
        return None
    try:
        index = _TIER_ORDER.index(decision.tier)
    except ValueError:
        return None
    if index >= len(_TIER_ORDER) - 1:
        return None
    indicators = re.compile(
        r"\b(?:ambiguous|cannot determine|unable to determine|architecture|"
        r"security|race condition|deadlock|interacting failures|root cause)\b",
        re.IGNORECASE,
    )
    if not indicators.search(evidence[:12_000]):
        return None
    tier = _TIER_ORDER[index + 1]
    return RoutingDecision(
        tier=tier,
        reason="repeated attempt produced reasoning-gap evidence",
        reasoning_effort={RoutingTier.STANDARD: "medium", RoutingTier.REASONING: "high"}[tier],
        automatic_escalations=decision.automatic_escalations + 1,
        exceptional_escalations=decision.exceptional_escalations,
        task_profile=decision.task_profile,
    )


def automatic_model_override(config: Mapping[str, object], tier: RoutingTier, configured_model: str | None) -> str | None:
    """Select an existing OmniRoute auto-combo only when `/model` is auto.

    A specific `/model` route is user intent and is never silently replaced.
    The returned IDs are gateway routes; OmniRoute still scores providers,
    accounts, quotas, resets, and fallback candidates inside that route.
    """
    if configured_model != "auto":
        return None
    routing = config.get("routing")
    if not isinstance(routing, Mapping):
        return None
    key = {
        RoutingTier.FAST: "fastAutoRoute",
        RoutingTier.STANDARD: "standardAutoRoute",
        RoutingTier.REASONING: "reasoningAutoRoute",
    }[tier]
    value = routing.get(key)
    return value if isinstance(value, str) and value.startswith("auto/") else None


def next_exceptional_effort(
    decision: RoutingDecision, *, evidence: str, exceptional_effort: str,
    max_exceptional_escalations: int,
) -> RoutingDecision | None:
    """Allow one evidence-gated exceptional effort inside REASONING only."""
    if (decision.tier is not RoutingTier.REASONING
            or decision.reasoning_effort != "high"
            or decision.exceptional_escalations >= max_exceptional_escalations
            or exceptional_effort not in {"xhigh", "max", "ultra"}):
        return None
    indicators = re.compile(
        r"\b(?:still unresolved|cannot determine|root cause|architecture|security|"
        r"race condition|deadlock|interacting failures|production incident)\b", re.IGNORECASE,
    )
    if not indicators.search(evidence[:12_000]):
        return None
    return RoutingDecision(
        tier=RoutingTier.REASONING,
        reason="exceptional unresolved reasoning evidence",
        reasoning_effort=exceptional_effort,
        automatic_escalations=decision.automatic_escalations,
        exceptional_escalations=decision.exceptional_escalations + 1,
        task_profile=decision.task_profile,
    )


def deescalate_for_follow_up(
    previous: RoutingDecision,
    *,
    request: str,
    config: Mapping[str, object],
    agent: str,
    workflow: str,
    policy_name: str,
) -> RoutingDecision:
    """Re-profile a follow-up instead of inheriting an expensive parent tier.

    Hard risk signals in the follow-up still route to REASONING.  The previous
    decision is accepted only to make the policy explicit and auditable; it is
    never used as a minimum tier.
    """
    del previous
    return classify_request(
        request=request,
        config=config,
        agent=agent,
        workflow=workflow,
        policy_name=policy_name,
    )
