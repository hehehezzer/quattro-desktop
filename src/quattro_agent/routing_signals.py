"""Local bootstrap routing with observational learned evidence.

Bootstrap has no model-authored decision yet. It therefore never submits the
historical fixed Jev questionnaire. Native execution authors contextual decisions
at the operational tool boundary, after the host locks its initial model plan.
Provider decisions are authored only by the native execution model.
"""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from .intelligence.store import IntelligenceStore
from .intelligence.telemetry import shadow_predict, sanitize_request
from .jev_shadow import annotate
from .routing import RoutingDecision, classify_pre_routing

POLICY_VERSION = "quattro-local-bootstrap-v2"


def learned_signal(database: Path, request: str, model_input=None) -> dict[str, Any]:
    """Use the existing safe-feature artifact, not a new learned classifier."""
    if not database.is_file():
        return {"error": "model_unavailable"}
    try:
        safe, _ = sanitize_request(request)
        result = shadow_predict(IntelligenceStore(database, busy_timeout_ms=20),
                                request=safe, profile=None, repository_present=False,
                                model_input=model_input)
        # Native error categories and bounded model IDs only, never paths/text.
        return {name: result[name] for name in
                ("prediction", "confidence", "model_version", "latency_ms", "error") if name in result}
    except Exception:
        return {"error": "inference_failed"}


def _classify_with_signals(*, pre_routing_input, config, database: Path, execution: str,
                           can_select=None, baseline_override=None, canonical_features=None,
                           eligible=True) -> RoutingDecision:
    """Preserve host routing authority without a fixed remote questionnaire.

    Learned evidence remains observational. Legacy mode settings are accepted
    for configuration compatibility, but neither enabled mode calls Jev here.
    """
    mode = config.get("routing", {}).get("jev", {}).get("mode", "OFF")
    annotate(policy_version=POLICY_VERSION, static_questionnaire_retired=True,
             decision_boundary="native_model_authored_operational")
    if not eligible:
        annotate(mode=mode, jev_eligible=False, jev_requested=False,
                 learned_signal={"error": "fast_guard"},
                 quattro_learned_ms=0.0, fusion_ms=0.0, critical_path_wait_ms=0.0, jev_wait_ms=0.0,
                 fusion_reason="fast_guard")
        return baseline_override or classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
    if mode == "OFF":
        annotate(mode=mode, jev_eligible=False, jev_requested=False, learned_signal={"error": "off"},
                 quattro_learned_ms=0.0, fusion_ms=0.0, critical_path_wait_ms=0.0, jev_wait_ms=0.0, fusion_reason="off")
        return baseline_override or classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
    started = time.perf_counter()
    local_started = time.perf_counter()
    baseline = baseline_override or classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
    deterministic_ms = (time.perf_counter() - local_started) * 1000
    local_started = time.perf_counter()
    learned = (learned_signal(database, pre_routing_input.request, canonical_features.local_projection())
               if canonical_features else learned_signal(database, pre_routing_input.request))
    learned_ms = (time.perf_counter() - local_started) * 1000
    annotate(local_preparation_finished=time.perf_counter())
    annotate(
        mode=mode, policy_version=POLICY_VERSION, learned_signal=learned,
        jev_eligible=False, jev_requested=False,
        policy_constraints=["execution_and_worker_preserved", "no_capability_downgrade",
                            "explicit_target_preserved", "registry_availability_and_cost_filters"],
        fusion_reason="model_authored_decision_deferred", authoritative_tier=baseline.tier.value,
        deterministic_tier=baseline.tier.value,
        quattro_learned_ms=learned_ms,
        deterministic_ms=deterministic_ms, fusion_ms=0.0,
        routing_total_ms=(time.perf_counter() - started) * 1000,
        critical_path_wait_ms=0.0, jev_wait_ms=0.0,
    )
    return baseline


def classify_with_signals(*, pre_routing_input, config, database: Path, execution: str,
                          can_select=None, baseline_override=None, canonical_features=None,
                          eligible=True) -> RoutingDecision:
    try:
        return _classify_with_signals(
            pre_routing_input=pre_routing_input, config=config, database=database,
            execution=execution, can_select=can_select, baseline_override=baseline_override,
            canonical_features=canonical_features, eligible=eligible,
        )
    except Exception:
        # Optional intelligence must never replace the authoritative exception
        # or make a previously routable request fail. Baseline errors still surface.
        annotate(fusion_reason="signal_failure_fallback")
        return baseline_override or classify_pre_routing(pre_routing_input=pre_routing_input, config=config)
