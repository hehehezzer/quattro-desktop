"""Reproducible real-world retrieval benchmark for Quattro.

The benchmark file contains human-audited expectations.  Unknown or partial
ground truth remains visible in per-case output but is excluded from strict
recall/MRR denominators rather than being guessed into a pass.
"""

from __future__ import annotations

import json
import hashlib
import pathlib
import re
import statistics
import time
from collections import Counter
from typing import Any, Mapping, Sequence

from .retrieval import (
    ContextAssembler, QueryRoute, QueryRouter, RetrievalStore,
    allowed_origins_for_route, repository_state,
)


def load_cases(path: pathlib.Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark must contain a non-empty cases list")
    required = {
        "id", "query", "query_type", "repository", "expected_source_type",
        "retrieval_required", "semantic_required", "graph_required",
        "expected_authority", "notes",
    }
    identifiers: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"benchmark case {index} is not an object")
        missing = required - set(case)
        if missing:
            raise ValueError(f"benchmark case {index} is missing {sorted(missing)}")
        identifier = str(case["id"])
        if identifier in identifiers:
            raise ValueError(f"duplicate benchmark id: {identifier}")
        identifiers.add(identifier)
    return cases


def _expected_values(case: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = case.get(key, ())
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item is not None)
    raise ValueError(f"{case.get('id')}: {key} must be a string, list, or null")


def _matches(case: Mapping[str, Any], result: Any) -> bool:
    files = _expected_values(case, "expected_files")
    symbols = _expected_values(case, "expected_symbols")
    memories = _expected_values(case, "expected_memories")
    source_types = _expected_values(case, "expected_source_type")
    path = result.path or ""
    symbol = result.symbol or ""
    metadata = result.metadata
    authoritative = str(metadata.get("authoritativePath", ""))
    target_checks: list[bool] = []
    if files:
        target_checks.append(any(path == value or path.endswith("/" + value) or authoritative.endswith(value) for value in files))
    if symbols:
        target_checks.append(any(symbol == value or value.endswith("." + symbol) for value in symbols))
    if memories:
        target_checks.append(any(
        value == result.id or value == path or authoritative.endswith(value)
        for value in memories
        ))
    return (not source_types or result.source_type in source_types) and (
        not target_checks or any(target_checks)
    )


class LegacyQueryRouter:
    """Frozen pre-optimization router for reproducible before/after evidence."""

    STATE = re.compile(r"(?i)\b(current|what|which)\b.*\b(branch|commit|sha|directory|repository|provider|model|account|task id|session id)\b|\bwhat branch am i on\b")
    CONTINUE = re.compile(r"(?i)\b(continue|resume|pick up|where we left|checkpoint)\b")
    HISTORY = re.compile(r"(?i)\b(yesterday|previous|last time|why did|failed|failure|decide|decision|history)\b")
    SYMBOL = re.compile(r"(?i:\b(find|locate|where is|definition|class|function|method|interface|symbol)\b)|\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+\b")
    ARCH = re.compile(r"(?i)\b(architecture|how does|design|flow|relationship|depends|calls|middleware)\b")

    def route(self, query: str) -> QueryRoute:
        if self.STATE.search(query):
            return QueryRoute("live_state", ("live_state",), True, False)
        if self.CONTINUE.search(query):
            return QueryRoute("multi_source", ("live_state", "checkpoint", "session"), True, False)
        if self.SYMBOL.search(query):
            return QueryRoute("symbol", ("code",), True, False, use_graph=True)
        if self.HISTORY.search(query):
            return QueryRoute("episodic", ("decision", "error", "fix", "session", "checkpoint"), True, True, historical=True)
        if self.ARCH.search(query):
            return QueryRoute("hybrid", ("architecture", "documentation", "code", "decision"), True, True, use_graph=True)
        return QueryRoute("hybrid", ("documentation", "decision", "code", "configuration"), True, True)


def _router_correct(case: Mapping[str, Any], route: Any) -> bool:
    required = bool(case["retrieval_required"])
    query_type = str(case["query_type"])
    if not required:
        return route.intent in {"no_retrieval", "live_state"}
    if query_type in {"live_state", "git_live_state"}:
        return route.intent == "live_state"
    if bool(case["semantic_required"]) and not route.use_semantic:
        return False
    if not bool(case["semantic_required"]) and route.use_semantic:
        return False
    if bool(case["graph_required"]) and not route.use_graph:
        return False
    if bool(case["graph_required"]) and route.intent == "graph":
        return True
    if query_type in {"exact_symbol", "symbol", "exact_file", "lexical_identifier", "exact_symbol_lookup", "exact_file_lookup", "lexical_heavy_identifier"}:
        return route.intent in {"symbol", "lexical", "graph"}
    if query_type in {"history", "historical_decision", "previous_bug", "previous_fix", "deployment_failure"}:
        return route.intent in {"historical", "episodic", "memory", "multi_source"}
    if query_type in {"continue_session", "checkpoint_recovery", "task_session_history"}:
        return route.intent in {"live_state", "continue_session", "episodic", "multi_source", "graph"}
    return True


def run_benchmark(
    store: RetrievalStore,
    cases: Sequence[Mapping[str, Any]],
    *,
    default_repository: pathlib.Path,
    cold_cache: bool = True,
    limit: int = 5,
    context_budget: int = 4_000,
    router_profile: str = "current",
    live_state_snapshot: Mapping[str, Any] | None = None,
    index_maintenance_ms: float | None = None,
) -> dict[str, Any]:
    router = LegacyQueryRouter() if router_profile == "legacy" else QueryRouter()
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []
    ranks: list[int | None] = []
    strict_ground_truth = 0
    router_correct = 0
    unnecessary_semantic = 0
    failed_retrievals = 0
    stale_results = 0
    cross_project_leaks = 0
    branch_leaks = 0
    context_tokens = 0
    duplicate_results = 0
    total_results = 0
    cache_hits = 0
    embedding_calls = 0
    graph_uses = 0
    graph_found = 0
    graph_injected = 0
    failure_categories: Counter[str] = Counter()

    if cold_cache:
        store.connection.execute("DELETE FROM query_cache")
        store.connection.commit()

    for case in cases:
        query = str(case["query"])
        repository = pathlib.Path(str(case.get("repository") or default_repository)).expanduser().resolve()
        state = {**repository_state(repository), **dict(live_state_snapshot or {})}
        branch = str(case.get("branch") or state.get("branch") or "") or None
        route = router.route(query)
        route_ok = _router_correct(case, route)
        router_correct += int(route_ok)
        if route.use_semantic and not bool(case["semantic_required"]):
            unnecessary_semantic += 1
        started = time.monotonic()
        trace: dict[str, Any] = {"cacheHit": False, "embeddingCalls": 0}
        results: list[Any] = []
        if bool(case["retrieval_required"]) and route.intent not in {"live_state", "no_retrieval"}:
            results, trace = store.search(
                query,
                repository=str(repository),
                branch=branch,
                source_types=route.sources,
                use_lexical=route.use_lexical,
                use_semantic=route.use_semantic,
                use_graph=route.use_graph,
                historical=route.historical,
                allowed_origins=(
                    None if router_profile == "legacy"
                    else allowed_origins_for_route(route, memory_allowed=True)
                ),
                limit=max(5, limit),
            )
        latency = (time.monotonic() - started) * 1_000
        latencies.append(latency)
        cache_hits += int(bool(trace.get("cacheHit")))
        embedding_calls += int(trace.get("embeddingCalls", 0))
        graph_uses += int(route.use_graph and bool(case["retrieval_required"]))
        found_graph_ids = {
            item.id for item in results if item.metadata.get("graphExpanded")
        }
        graph_found += len(found_graph_ids)
        assembled = ContextAssembler().assemble(
            request=query,
            structured_state=state,
            results=results,
            budget_tokens=context_budget,
        )
        context_tokens += int(assembled["budget"]["retrievedUsed"])
        graph_injected += sum(
            item.get("id") in found_graph_ids for item in assembled["retrievedKnowledge"]
        )
        digests = [item.content_hash if hasattr(item, "content_hash") else item.content.strip() for item in results]
        duplicate_results += len(digests) - len(set(digests))
        total_results += len(results)

        negative_expected = "none" in _expected_values(case, "expected_source_type")
        structured_expected = "live_state" in _expected_values(case, "expected_source_type")
        authority = str(case.get("expected_authority", ""))
        structured_supported = (
            bool(state.get("branch") and state.get("commitSha"))
            if authority in {"git_live_state", "git_history"}
            else bool(state.get("recentTasks"))
            if authority == "task_store_display_projection"
            else bool(state.get("logicalSessions"))
            if authority == "logical_session_and_checkpoint_store"
            else True
        )
        matching_rank = (
            1 if structured_expected and route.intent == "live_state" and structured_supported else
            1 if negative_expected and not results else
            next((index for index, item in enumerate(results, 1) if _matches(case, item)), None)
        )
        truth = str(case.get("ground_truth_status", "established"))
        if truth == "established" and bool(case["retrieval_required"]):
            strict_ground_truth += 1
            ranks.append(matching_rank)
        expected_repository = str(repository)
        case_project_leaks = 0
        case_branch_leaks = 0
        for item in results:
            item_repository = str(item.repository or "")
            authoritative = str(item.metadata.get("authoritativePath", ""))
            if item_repository and item_repository != expected_repository:
                cross_project_leaks += 1
                case_project_leaks += 1
            if authoritative and not (
                authoritative.startswith(expected_repository + "/")
                or "/Shared/" in authoritative
                or "/Projects/" in authoritative
            ):
                cross_project_leaks += 1
                case_project_leaks += 1
            item_branch = item.branch
            if item_branch and branch and item_branch != branch:
                branch_leaks += 1
                case_branch_leaks += 1
            if item.metadata.get("stale") or item.metadata.get("superseded"):
                stale_results += 1

        if (bool(case["retrieval_required"]) and not negative_expected
                and route.intent not in {"live_state", "no_retrieval"} and not results):
            failed_retrievals += 1
            failure_categories["failed_retrieval"] += 1
        if not route_ok:
            failure_categories["router_error"] += 1
        if truth == "established" and bool(case["retrieval_required"]) and matching_rank is None:
            if route.use_semantic and not route.use_lexical:
                failure_categories["semantic_miss"] += 1
            elif route.use_lexical and not route.use_semantic:
                failure_categories["lexical_miss"] += 1
            else:
                failure_categories["ranking_or_hybrid_miss"] += 1
        if case_project_leaks:
            failure_categories["project_isolation_problem"] += 1
        if case_branch_leaks:
            failure_categories["branch_isolation_problem"] += 1
        per_case.append({
            "id": case["id"],
            "query": query,
            "queryType": case["query_type"],
            "groundTruthStatus": truth,
            "route": route.intent,
            "routerCorrect": route_ok,
            "semanticUsed": route.use_semantic,
            "graphUsed": route.use_graph,
            "graphResultsFound": len(found_graph_ids),
            "graphResultsInjected": sum(
                item.get("id") in found_graph_ids for item in assembled["retrievedKnowledge"]
            ),
            "matchingRank": matching_rank,
            "negativeExpected": negative_expected,
            "structuredExpected": structured_expected,
            "resultCount": len(results),
            "latencyMs": round(latency, 3),
            "contextTokens": assembled["budget"]["retrievedUsed"],
            "cacheHit": bool(trace.get("cacheHit")),
            "embeddingCalls": int(trace.get("embeddingCalls", 0)),
            "resultIds": [item.id for item in results[:limit]],
            "resultPaths": [item.path for item in results[:limit]],
            "resultSymbols": [item.symbol for item in results[:limit]],
        })

    def recall(k: int) -> float:
        return (sum(rank is not None and rank <= k for rank in ranks) / len(ranks)) if ranks else 0.0

    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    mrr = (sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / len(ranks)) if ranks else 0.0
    return {
        "schemaVersion": 1,
        "caseCount": len(cases),
        "routerProfile": router_profile,
        "provenance": {
            "datasetSha256": hashlib.sha256(
                json.dumps(list(cases), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "indexGeneration": store.generation,
            "embeddingModel": store.embedding_backend.model_id,
            "coldCache": cold_cache,
            "indexMaintenanceMsSample": (
                round(index_maintenance_ms, 3) if index_maintenance_ms is not None else None
            ),
        },
        "strictGroundTruthCases": strict_ground_truth,
        "metrics": {
            "recallAt1": round(recall(1), 6),
            "recallAt3": round(recall(3), 6),
            "recallAt5": round(recall(5), 6),
            "mrr": round(mrr, 6),
            "routerDecisionRate": round(router_correct / len(cases), 6),
            "unnecessarySemanticRate": round(unnecessary_semantic / len(cases), 6),
            "failedRetrievalRate": round(failed_retrievals / len(cases), 6),
            "staleResultRate": round(stale_results / max(1, total_results), 6),
            "crossProjectLeakageRate": round(cross_project_leaks / max(1, total_results), 6),
            "branchLeakageRate": round(branch_leaks / max(1, total_results), 6),
            "averageLatencyMs": round(statistics.fmean(latencies), 3),
            "p50LatencyMs": round(statistics.median(latencies), 3),
            "p95LatencyMs": round(ordered[p95_index], 3),
            "contextTokensAssembled": context_tokens,
            "duplicateContextRate": round(duplicate_results / max(1, total_results), 6),
            "cacheHitRate": round(cache_hits / len(cases), 6),
            "semanticVectorComputations": embedding_calls,
            "graphExpansionUsage": graph_uses,
            "graphResultsFound": graph_found,
            "graphResultsInjected": graph_injected,
        },
        "failureCategories": dict(sorted(failure_categories.items())),
        "cases": per_case,
    }
