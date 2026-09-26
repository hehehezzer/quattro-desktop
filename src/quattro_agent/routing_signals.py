"""Conservative Quattro-owned fusion at the existing request boundary.

Signals can raise a capability floor by one tier, never remove a deterministic
requirement, change execution/worker, select a target, or bypass availability.
Existing registry cost/capability filters and fallback plans remain downstream.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Any

from .intelligence.store import IntelligenceStore
from .intelligence.telemetry import shadow_predict, sanitize_request
from .jev import serialize_state
from .jev_shadow import annotate, start_shadow
from .routing import RoutingDecision, RoutingTier, classify_pre_routing

POLICY_VERSION = "quattro-signal-fusion-v1"
MIN_CONFIDENCE = 0.90
LEARNED_VETO_CONFIDENCE = 0.80


def learned_signal(database: Path, request: str) -> dict[str, Any]:
    """Use the existing safe-feature artifact, not a new learned classifier."""
    if not database.is_file():
        return {"error": "model_unavailable"}
    try:
        safe, _ = sanitize_request(request)
        result = shadow_predict(IntelligenceStore(database, busy_timeout_ms=20),
                                request=safe, profile=None, repository_present=False)
        # Native error categories and bounded model IDs only, never paths/text.
        return {name: result[name] for name in
                ("prediction", "confidence", "model_version", "latency_ms", "error") if name in result}
    except Exception:
        return {"error": "inference_failed"}


def fuse(baseline: RoutingDecision, *, execution: str, manual: bool,
         features: dict[str, Any], jev: dict[str, Any] | None,
         learned: dict[str, Any], config) -> tuple[RoutingDecision, str]:
    """Explicit eligibility/veto policy, never an average or router contest."""
    if manual:
        return baseline, "explicit_target_preserved"
    if execution != "DELEGATE" or features["complexity"] == "low":
        return baseline, "deterministic_execution_preserved"
    if baseline.tier is RoutingTier.REASONING:
        return baseline, "deterministic_maximum_preserved"
    if not jev:
        return baseline, "jev_unavailable"
    if learned.get("prediction") == "DIRECT" and learned.get("confidence", 0) >= LEARNED_VETO_CONFIDENCE:
        return baseline, "learned_direct_veto"
    answers = jev["answers"]
    if any(answers[name]["confidence"] < MIN_CONFIDENCE for name in ("execution", "complexity", "capability")):
        return baseline, "uncertain_signal"
    if answers["execution"]["choice"] != "DELEGATE" or answers["complexity"]["choice"] != "HIGH":
        return baseline, "deterministic_floor_preserved"
    requested = {"CHEAP": 0, "STANDARD": 1, "STRONG": 2, "FRONTIER": 2}[answers["capability"]["choice"]]
    tiers = (RoutingTier.FAST, RoutingTier.STANDARD, RoutingTier.REASONING)
    current = tiers.index(baseline.tier)
    if requested <= current:
        return baseline, "deterministic_floor_preserved"
    target = tiers[min(current + 1, requested)]
    profile = dict(baseline.task_profile)
    thresholds = config.get("routing", {}).get("qualityThresholds", {})
    floor = thresholds.get(target.value, {"STANDARD": 0.65, "REASONING": 0.80}[target.value])
    profile.update(tier=target.value, minimum_quality=max(profile["minimum_quality"], floor))
    profile["signals"] = [*profile["signals"], "quattro_fused_capability_floor"]
    return replace(baseline, tier=target, reasoning_effort={
        RoutingTier.STANDARD: "medium", RoutingTier.REASONING: "high",
    }[target], task_profile=profile, reason="Quattro policy raised capability floor from corroborated task signals"), "capability_floor_raised"


def _classify_with_signals(*, pre_routing_input, config, database: Path, execution: str,
                           can_select=None) -> RoutingDecision:
    """Jev runs concurrently with deterministic and learned analysis.

    SHADOW never waits at the fusion boundary. COOPERATIVE waits only for the
    remainder of the strict routing budget; the lifecycle owns cancellation.
    """
    mode = config.get("routing", {}).get("jev", {}).get("mode", "OFF")
    if mode == "OFF":
        return classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
    started = time.perf_counter()
    state = serialize_state(pre_routing_input.request)
    features = json.loads(state)
    feature_ms = (time.perf_counter() - started) * 1000
    run = start_shadow(
        config=config, database=database.with_name("jev-shadow.sqlite3"),
        request="", state_json=state, decision=execution,
    )
    local_started = time.perf_counter()
    baseline = classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
    deterministic_ms = (time.perf_counter() - local_started) * 1000
    local_started = time.perf_counter()
    learned = learned_signal(database, pre_routing_input.request)
    learned_ms = (time.perf_counter() - local_started) * 1000
    jev = None
    wait_started = time.perf_counter()
    eligible = (
        execution == "DELEGATE" and features["complexity"] != "low"
        and pre_routing_input.explicit_model == "auto"
        and baseline.tier is not RoutingTier.REASONING
    )
    if mode == "COOPERATIVE" and run is not None and eligible:
        remaining = max(0, run.timeout_ms / 1000 - (time.perf_counter() - started))
        if not run.done.wait(remaining):
            run.close(reason="timeout")
        if run.record["status"] == "success":
            jev = {"answers": run.record["answers"]}
    added_wait_ms = (time.perf_counter() - wait_started) * 1000
    fusion_started = time.perf_counter()
    final, reason = baseline, "shadow_no_effect"
    if mode == "COOPERATIVE":
        final, reason = fuse(
            baseline, execution=execution, manual=pre_routing_input.explicit_model != "auto",
            features=features, jev=jev, learned=learned, config=config,
        )
    if final != baseline and (can_select is None or not can_select(final)):
        final, reason = baseline, "runtime_capability_veto"
    fusion_ms = (time.perf_counter() - fusion_started) * 1000
    annotate(
        mode=mode, policy_version=POLICY_VERSION, learned_signal=learned,
        policy_constraints=["execution_and_worker_preserved", "no_capability_downgrade",
                            "explicit_target_preserved", "registry_availability_and_cost_filters"],
        fusion_reason=reason, authoritative_tier=final.tier.value,
        deterministic_tier=baseline.tier.value,
        feature_extraction_ms=feature_ms, quattro_learned_ms=learned_ms,
        deterministic_ms=deterministic_ms, fusion_ms=fusion_ms,
        routing_total_ms=(time.perf_counter() - started) * 1000,
        critical_path_wait_ms=added_wait_ms,
    )
    return final


def classify_with_signals(*, pre_routing_input, config, database: Path, execution: str,
                          can_select=None) -> RoutingDecision:
    try:
        return _classify_with_signals(
            pre_routing_input=pre_routing_input, config=config, database=database,
            execution=execution, can_select=can_select,
        )
    except Exception:
        # Optional intelligence must never replace the authoritative exception
        # or make a previously routable request fail. Baseline errors still surface.
        annotate(fusion_reason="signal_failure_fallback")
        return classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
