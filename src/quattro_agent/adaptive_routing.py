"""Public OmniRoute capability negotiation and adaptive candidate selection.

Only sanitized metadata crosses this boundary.  Quattro never reads provider
configuration or credentials and OmniRoute remains authoritative at dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from .routing_intelligence import (
    Availability,
    ModelCandidate,
    ModelSelection,
    PreferenceMode,
    ROUTING_POLICY_VERSION,
    TaskProfile,
    evaluate_candidates,
    load_benchmark_cache,
    load_local_outcomes,
    save_benchmark_cache,
)


CAPABILITY_CACHE_TTL_SECONDS = 300.0
CANDIDATE_CACHE_TTL_SECONDS = 5.0
MAX_METADATA_BYTES = 2_000_000
REQUIRED_ENHANCED_CAPABILITIES = frozenset({
    "candidate_snapshot",
    "routing_requirements",
    "preferred_candidates",
    "capability_routing",
    "practical_context",
    "cost_metadata",
    "quota_state",
    "routing_diagnostics",
})
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

_CAPABILITY_MAP: Mapping[str, tuple[str, ...]] = {
    "coding": ("code_analysis",),
    "repository_read": ("repository_access",),
    "repository_write": ("repository_access", "code_editing", "sandbox_write"),
    "shell": ("shell",),
    "git": ("git",),
    "reasoning": ("reasoning",),
    "long_context": ("long_context",),
}


@dataclass(frozen=True, slots=True)
class CapabilityNegotiation:
    connected: bool
    compatibility: str
    capabilities: frozenset[str]
    header_transport: bool
    error: str | None = None

    @property
    def adaptive(self) -> bool:
        return self.compatibility == "enhanced"


@dataclass(frozen=True, slots=True)
class AdaptiveRoutingDecision:
    negotiation: CapabilityNegotiation
    selection: ModelSelection | None
    envelope: Mapping[str, Any] | None
    metadata_version: str
    candidate_count: int
    overhead_ms: float
    cache_hit: bool

    @property
    def preferred_candidates(self) -> tuple[str, ...]:
        if not self.envelope:
            return ()
        return tuple(str(value) for value in self.envelope.get("preferred_candidates", ()))


class OmniRouteAdaptiveClient:
    """Bounded, thread-safe client for the two public enhanced endpoints."""

    _lock = threading.Lock()
    _capability_cache: dict[str, tuple[float, CapabilityNegotiation]] = {}
    _candidate_cache: dict[tuple[str, str], tuple[float, Mapping[str, Any]]] = {}

    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def clear_caches(cls) -> None:
        with cls._lock:
            cls._capability_cache.clear()
            cls._candidate_cache.clear()

    def _get_json(self, path: str) -> Mapping[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "application/json", "User-Agent": "Quattro-Routing/2"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read(MAX_METADATA_BYTES + 1)
        if len(payload) > MAX_METADATA_BYTES:
            raise ValueError("OmniRoute metadata exceeds the size limit")
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, Mapping):
            raise ValueError("OmniRoute metadata must be an object")
        return parsed

    def negotiate(self) -> tuple[CapabilityNegotiation, bool]:
        now = time.monotonic()
        with self._lock:
            cached = self._capability_cache.get(self.base_url)
            if cached and now - cached[0] < CAPABILITY_CACHE_TTL_SECONDS:
                return cached[1], True
        try:
            payload = self._get_json("/capabilities")
            flags = payload.get("capabilities")
            if payload.get("schema_version") != 1 or not isinstance(flags, Mapping):
                raise ValueError("unsupported capability schema")
            supported = frozenset(
                str(name) for name, value in flags.items() if value is True
            )
            negotiation = CapabilityNegotiation(
                connected=True,
                compatibility=(
                    "enhanced" if REQUIRED_ENHANCED_CAPABILITIES <= supported else "standard"
                ),
                capabilities=supported,
                header_transport="routing_header_transport" in supported,
            )
        except urllib.error.HTTPError as error:
            error.close()
            negotiation = CapabilityNegotiation(
                connected=error.code not in {502, 503, 504}, compatibility="standard",
                capabilities=frozenset(), header_transport=False,
                error=f"capability endpoint HTTP {error.code}",
            )
        except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
            negotiation = CapabilityNegotiation(
                connected=False, compatibility="standard", capabilities=frozenset(),
                header_transport=False, error=f"capability negotiation unavailable: {type(error).__name__}",
            )
        with self._lock:
            self._capability_cache[self.base_url] = (now, negotiation)
        return negotiation, False

    def candidates(self, channel: str) -> tuple[Mapping[str, Any], bool]:
        key = (self.base_url, channel)
        now = time.monotonic()
        with self._lock:
            cached = self._candidate_cache.get(key)
            if cached and now - cached[0] < CANDIDATE_CACHE_TTL_SECONDS:
                return cached[1], True
        query = urllib.parse.urlencode({"channel": channel})
        payload = self._get_json(f"/routing/candidates?{query}")
        if (
            payload.get("schema_version") != 1
            or not isinstance(payload.get("metadata_version"), str)
            or not isinstance(payload.get("candidates"), list)
            or len(payload["candidates"]) > 512
        ):
            raise ValueError("unsupported candidate snapshot schema")
        with self._lock:
            self._candidate_cache[key] = (now, payload)
        return payload, False


def _channel_for_route(route: str) -> str:
    # Enhanced ordering needs the complete public auto inventory. The request
    # still carries Quattro's tier route for standard compatibility; the fork
    # expands automatic tier aliases to this base pool only when it receives a
    # validated routing envelope.
    del route
    return "auto"


def _requirements(profile: TaskProfile) -> tuple[str, ...]:
    values: list[str] = []
    for capability in profile.required_capabilities:
        values.extend(_CAPABILITY_MAP.get(capability, ()))
    return tuple(dict.fromkeys(values))


def _candidate_capabilities(row: Mapping[str, Any]) -> frozenset[str]:
    result = {"conversation"}
    capabilities = row.get("capabilities")
    execution = capabilities.get("execution") if isinstance(capabilities, Mapping) else None
    if isinstance(capabilities, Mapping):
        if capabilities.get("reasoning") is True:
            result.add("reasoning")
        if capabilities.get("vision") is True:
            result.add("vision")
        if capabilities.get("tools") is True:
            result.add("tool_calling")
    if isinstance(execution, Mapping):
        mapping = {
            "repositoryAccess": "repository_read",
            "codeAnalysis": "coding",
            "shell": "shell",
            "git": "git",
        }
        for source, target in mapping.items():
            if execution.get(source) is True:
                result.add(target)
        if execution.get("codeEditing") is True and execution.get("sandbox") in {
            "workspace_write", "full_access",
        }:
            result.add("repository_write")
        if execution.get("longContext") is True:
            result.add("long_context")
    modalities = row.get("modalities")
    if isinstance(modalities, Mapping) and "image" in (modalities.get("input") or []):
        result.add("vision")
    return frozenset(result)


def _availability(row: Mapping[str, Any]) -> Availability:
    health = row.get("health_state")
    quota = row.get("quota_state")
    if row.get("cooldown_state") is True or health == "cooldown":
        return Availability.COOLDOWN
    if quota == "unavailable":
        return Availability.QUOTA_EXHAUSTED
    if health == "unhealthy":
        return Availability.UNHEALTHY
    return Availability.AVAILABLE if health == "available" else Availability.UNAVAILABLE


def model_candidates_from_snapshot(
    snapshot: Mapping[str, Any], profile: TaskProfile,
) -> tuple[ModelCandidate, ...]:
    result: list[ModelCandidate] = []
    seen: set[str] = set()
    for raw in snapshot.get("candidates", []):
        if not isinstance(raw, Mapping):
            raise ValueError("candidate entry must be an object")
        provider = raw.get("provider_id")
        model = raw.get("model_id")
        route = raw.get("route")
        if (
            not isinstance(provider, str) or not provider
            or not isinstance(model, str) or not model
            or route != f"{provider}/{model}"
            or not _PROVIDER_ID.fullmatch(provider)
            or not _MODEL_ID.fullmatch(model)
            or route in seen
        ):
            raise ValueError("candidate identity is invalid")
        seen.add(route)
        pricing = raw.get("pricing")
        if not isinstance(pricing, Mapping):
            raise ValueError("candidate pricing is invalid")
        pricing_state = pricing.get("state")
        input_price = pricing.get("input_cost") if pricing_state in {"known", "free"} else None
        output_price = pricing.get("output_cost") if pricing_state in {"known", "free"} else None
        if input_price is not None and (
            not isinstance(input_price, (int, float)) or isinstance(input_price, bool)
        ):
            raise ValueError("candidate input pricing is invalid")
        if output_price is not None and (
            not isinstance(output_price, (int, float)) or isinstance(output_price, bool)
        ):
            raise ValueError("candidate output pricing is invalid")
        capabilities = _candidate_capabilities(raw)
        # Static metadata is deliberately conservative. Verified execution and
        # reasoning flags establish capability, not benchmark-level strength.
        metadata_quality = 0.50
        if "coding" in capabilities and "repository_read" in capabilities:
            metadata_quality += 0.10
        if "reasoning" in capabilities:
            metadata_quality += 0.05
        practical = raw.get("practical_context_limit")
        if practical is not None and (
            not isinstance(practical, int) or isinstance(practical, bool) or practical <= 0
        ):
            raise ValueError("candidate context limit is invalid")
        result.append(ModelCandidate(
            provider=provider,
            model=model,
            capabilities=capabilities,
            practical_input_limit=practical,
            availability=_availability(raw),
            retry_eligible=False,
            metadata_quality=min(metadata_quality, 0.65),
            input_cost_per_million=float(input_price) if input_price is not None else None,
            output_cost_per_million=float(output_price) if output_price is not None else None,
            expected_input_tokens=profile.estimated_tokens,
            expected_output_tokens=max(512, min(8_000, profile.estimated_tokens // 4)),
            latency_ms=math.inf,
            stable_key=route,
        ))
    return tuple(result)


def build_adaptive_decision(
    *,
    client: OmniRouteAdaptiveClient,
    profile: TaskProfile,
    route: str,
    benchmark_path: Any,
    outcomes_path: Any,
    preference: PreferenceMode = PreferenceMode.BALANCED,
    quality_weights: Mapping[str, float] | None = None,
    local_outcome_min_samples: int = 5,
    task_profile_id: str | None = None,
) -> AdaptiveRoutingDecision:
    started = time.perf_counter()
    negotiation, capability_cache_hit = client.negotiate()
    if not negotiation.adaptive:
        return AdaptiveRoutingDecision(
            negotiation, None, None, "standard-tier-routing", 0,
            (time.perf_counter() - started) * 1000, capability_cache_hit,
        )
    try:
        snapshot, candidate_cache_hit = client.candidates(_channel_for_route(route))
        candidates = model_candidates_from_snapshot(snapshot, profile)
        benchmark_records = load_benchmark_cache(benchmark_path)
        if not benchmark_records:
            seed_path = Path(__file__).with_name("data") / "initial-routing-evidence.json"
            benchmark_records = load_benchmark_cache(seed_path)
            if benchmark_records:
                save_benchmark_cache(Path(benchmark_path), benchmark_records)
        selection = evaluate_candidates(
            profile,
            candidates,
            benchmark_records,
            load_local_outcomes(outcomes_path),
            preference=preference,
            quality_weights=quality_weights,
            local_outcome_min_samples=local_outcome_min_samples,
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        fallback = CapabilityNegotiation(
            connected=True, compatibility="standard", capabilities=negotiation.capabilities,
            header_transport=negotiation.header_transport,
            error="adaptive_routing_unavailable",
        )
        return AdaptiveRoutingDecision(
            fallback, None, None, "adaptive_routing_unavailable", 0,
            (time.perf_counter() - started) * 1000, capability_cache_hit,
        )
    ordered = sorted(
        (item for item in selection.candidates if item.eligible),
        key=lambda item: item.rank or math.inf,
    )
    profile_id = task_profile_id or (
        "profile-" + hashlib.sha256(
            json.dumps(profile.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
    )
    envelope = {
        "schema_version": 1,
        "requirements": {
            "capabilities": list(_requirements(profile)),
            "minimum_context": profile.estimated_tokens,
        },
        "preferred_candidates": [f"{item.provider}/{item.model}" for item in ordered[:32]],
        # Schema v1 implements only balanced advisory ordering. Quattro may use
        # economy/quality internally, but the emitted order is the sole signal.
        "preference_mode": "balanced",
        "task_profile_id": profile_id,
        "routing_policy_version": ROUTING_POLICY_VERSION,
    }
    return AdaptiveRoutingDecision(
        negotiation=negotiation,
        selection=selection,
        envelope=envelope,
        metadata_version=str(snapshot["metadata_version"]),
        candidate_count=len(candidates),
        overhead_ms=(time.perf_counter() - started) * 1000,
        cache_hit=capability_cache_hit and candidate_cache_hit,
    )


def encode_routing_header(envelope: Mapping[str, Any]) -> str:
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 8_192 or any(ord(char) < 0x20 for char in encoded):
        raise ValueError("routing envelope exceeds the safe header contract")
    return encoded
