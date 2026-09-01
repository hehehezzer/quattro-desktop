"""Deterministic, low-overhead request-tier classification for Quattro.

Quattro selects only a reasoning tier.  OmniRoute remains the authority for
provider, account, quota, and cost routing behind the selected request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Mapping


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

# High-risk or genuinely ambiguous work is intentionally recognized before the
# inexpensive/mechanical vocabulary below.
_REASONING = re.compile(
    r"\b(?:architecture|security(?:[- ]critical)?|"
    r"incident|production|concurren(?:cy|t)|race condition|deadlock|data loss|"
    r"migration|root cause|ambiguous|distributed|cross[- ]cutting|large refactor)\b",
    re.IGNORECASE,
)
_FAST = re.compile(
    r"\b(?:find|search|locate|list|read|inspect|summari[sz]e|explain|"
    r"format|lint|rename|typo|documentation|docs?|configuration|config|"
    r"symbol|grep|deterministic|mechanical)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    tier: RoutingTier
    reason: str
    reasoning_effort: str
    automatic_escalations: int = 0
    exceptional_escalations: int = 0

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
    """Classify locally from stable metadata and bounded lexical heuristics."""
    compact = " ".join(request.split())[:4_096]
    if policy_name in {"audit-read-only", "review-untrusted"} and "security" in workflow:
        tier = RoutingTier.REASONING
        reason = "security review workflow"
    elif _REASONING.search(compact):
        tier = RoutingTier.REASONING
        reason = "high-risk or ambiguous task signal"
    elif agent == "pi" and workflow == "codex-pi-delegation":
        tier = RoutingTier.FAST
        reason = "bounded read-only delegation"
    elif _FAST.search(compact) and not re.search(
        r"\b(?:implement|feature|debug|refactor|integration|test suite)\b", compact, re.IGNORECASE
    ):
        tier = RoutingTier.FAST
        reason = "mechanical discovery or documentation task"
    else:
        tier = RoutingTier.STANDARD
        reason = "normal engineering task or uncertain request"
    return RoutingDecision(tier=tier, reason=reason, reasoning_effort=_effort(config, tier))


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
    )
