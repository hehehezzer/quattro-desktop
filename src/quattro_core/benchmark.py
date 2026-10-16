"""Reproducible real-world retrieval benchmark for Quattro.

The benchmark file contains human-audited expectations.  Unknown or partial
ground truth remains visible in per-case output but is excluded from strict
recall/MRR denominators rather than being guessed into a pass.
"""

from __future__ import annotations

import json
import hashlib
import pathlib
import statistics
import time
from collections import Counter
from typing import Any, Mapping, Sequence

from .retrieval import (
    ContextAssembler, QueryRouter, RetrievalStore, allowed_origins_for_route,
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


def _router_correct(case: Mapping[str, Any], route: Any) -> bool:
    required = bool(case["retrieval_required"])
    query_type = str(case["query_type"])
    if not required:
        return route.intent == "no_retrieval"
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
        return route.intent in {"continue_session", "episodic", "multi_source", "graph"}
    return True


def run_benchmark(
    store: RetrievalStore,
    cases: Sequence[Mapping[str, Any]],
    *,
    default_repository: pathlib.Path,
    cold_cache: bool = True,
    limit: int = 5,
    context_budget: int = 4_000,
    index_maintenance_ms: float | None = None,
) -> dict[str, Any]:
    router = QueryRouter()
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
        branch = str(case.get("branch") or "") or None
        route = router.route(query)
        route_ok = _router_correct(case, route)
        router_correct += int(route_ok)
        if route.use_semantic and not bool(case["semantic_required"]):
            unnecessary_semantic += 1
        started = time.monotonic()
        trace: dict[str, Any] = {"cacheHit": False, "embeddingCalls": 0}
        results: list[Any] = []
        if bool(case["retrieval_required"]) and route.intent != "no_retrieval":
            results, trace = store.search(
                query,
                repository=str(repository),
                branch=branch,
                source_types=route.sources,
                use_lexical=route.use_lexical,
                use_semantic=route.use_semantic,
                use_graph=route.use_graph,
                historical=route.historical,
                allowed_origins=allowed_origins_for_route(route, memory_allowed=True),
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
            structured_state={},
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
        matching_rank = (
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
            if item_repository != expected_repository:
                cross_project_leaks += 1
                case_project_leaks += 1
            if branch is not None and item.branch != branch:
                branch_leaks += 1
                case_branch_leaks += 1
            if item.metadata.get("stale") or item.metadata.get("superseded"):
                stale_results += 1

        if (bool(case["retrieval_required"]) and not negative_expected
                and route.intent != "no_retrieval" and not results):
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
    p95_index = max(0, (len(ordered) * 95 + 99) // 100 - 1)
    mrr = (sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / len(ranks)) if ranks else 0.0
    return {
        "schemaVersion": 1,
        "caseCount": len(cases),
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


def evaluate_core(service, cases, *, limit=5, budget=6000):
    """Evaluate the public scoped service, with identical filters and byte budgets."""
    import math
    reports = {}
    scopes = {(case["project"], source_id) for case in cases for source_id in case["source_ids"]}
    corpus = []
    for project, source_id in sorted(scopes):
        service._sources(project, [source_id])
        corpus.extend(tuple(row) for row in service.connection.execute(
            "SELECT project,source_id,path,content_hash FROM knowledge_files WHERE project=? AND source_id=? ORDER BY path", (project,source_id)))
    memory_corpus = []
    for project in sorted({case["project"] for case in cases}):
        memory_corpus.extend(tuple(row) for row in service.memory.connection.execute(
            "SELECT project,id,content_hash,state,verification,revision,superseded_by,visibility,author FROM memories "
            "WHERE project=? AND (visibility='project' OR author=?) ORDER BY id", (project,service.config.principal)))
    for strategy in ("keyword", "semantic", "hybrid"):
        rows = []
        for case in cases:
            started = time.monotonic()
            phase = "retrieval"
            retrieval_ms = None
            context_started = None
            try:
                arguments = dict(project=case["project"], query=case["query"],
                                 source_ids=case["source_ids"], limit=limit, strategy=strategy)
                found = service.search_knowledge(**arguments)
                retrieval_ms = (time.monotonic() - started) * 1000
                context_started = time.monotonic()
                phase = "context"
                context = service.get_project_context(**arguments, budget=budget)
                context_ms = (time.monotonic() - context_started) * 1000
                results = found["results"]
                expected = set(case["expected_files"])
                hits = [r["citation"]["path"] in expected and
                        (not case.get("expected_symbol") or r.get("symbol") == case["expected_symbol"])
                        for r in results]
                ranks = [i + 1 for i, hit in enumerate(hits) if hit]
                covered = {r["citation"]["path"] for r, hit in zip(results, hits) if hit}
                credited = set()
                dcg = 0.0
                for index, (result, hit) in enumerate(zip(results, hits)):
                    path = result["citation"]["path"]
                    if hit and path not in credited:
                        dcg += 1 / math.log2(index + 2)
                        credited.add(path)
                ideal = sum(1 / math.log2(i + 2) for i in range(min(len(expected), limit)))
                rows.append({
                    "id": case["id"], "split": case["split"], "answerable": case["answerable"],
                    "available": strategy != "semantic" or found["semantic"]["available"],
                    "recall_at_5": len(covered) / len(expected) if expected else None,
                    "precision_at_5": sum(hits) / limit,
                    "mrr": 1 / ranks[0] if ranks else 0.0,
                    "ndcg": dcg / ideal if ideal else None,
                    "irrelevant_context_ratio": sum(k["citation"]["path"] not in expected or
                        bool(case.get("expected_symbol") and k.get("symbol") != case["expected_symbol"])
                        for k in context["knowledge"]) / max(1, len(context["knowledge"])),
                    "stale_results": sum(r["citation"]["provenance"] != "current" for r in results),
                    "stale_context":sum(k["citation"]["provenance"] != "current" for k in context["knowledge"]),
                    "boundary_violations": sum(r["citation"]["project"] != case["project"] or
                                               r["citation"]["source_id"] not in case["source_ids"] for r in results),
                    "no_evidence_correct": not results and not context["knowledge"] and not context["memories"] if not case["answerable"] else None,
                    "context_memory_units":len(context["memories"]),
                    "ineligible_memory_units":sum(m["id"] in case.get("ineligible_memory_ids",[]) for m in context["memories"]),
                    "context_bytes": len(json.dumps(context, ensure_ascii=False, sort_keys=True).encode()),
                    "context_tokens": None, "failure": False,
                    "context_request_latency_ms":context_ms,
                    "results": [{"id": r["id"], "path": r["citation"]["path"],
                                 "source_id": r["citation"]["source_id"],
                                 "file_hash": r["citation"]["file_hash"]} for r in results],
                })
            except Exception as error:
                rows.append({"id": case["id"], "split": case["split"], "failure": True,
                             "error_type": type(error).__name__, "failure_stage":phase, "available": False})
            rows[-1]["total_latency_ms"] = (time.monotonic() - started) * 1000
            rows[-1]["latency_ms"] = retrieval_ms if retrieval_ms is not None else rows[-1]["total_latency_ms"]
        valid = [r for r in rows if not r["failure"]]
        positives = [r for r in valid if r["answerable"]]
        negatives = [r for r in valid if not r["answerable"]]
        def mean(field, subset=valid):
            values = [r[field] for r in subset if r.get(field) is not None]
            return statistics.fmean(values) if values else None
        latencies = sorted(r["latency_ms"] for r in rows)
        reports[strategy] = {"metrics": {
            "recall_at_5": mean("recall_at_5", positives), "precision_at_5": mean("precision_at_5", positives),
            "mrr": mean("mrr", positives), "ndcg": mean("ndcg", positives),
            "relevant_evidence_coverage": mean("recall_at_5", positives),
            "irrelevant_context_ratio": mean("irrelevant_context_ratio"),
            "stale_results": sum(r["stale_results"] for r in valid),
            "boundary_violations": sum(r["boundary_violations"] for r in valid),
            "stale_context":sum(r["stale_context"] for r in valid),
            "ineligible_memory_units":sum(r["ineligible_memory_units"] for r in valid),
            "context_memory_units":sum(r["context_memory_units"] for r in valid),
            "no_evidence_accuracy": mean("no_evidence_correct", negatives),
            "p50_latency_ms": statistics.median(latencies),
            "p95_latency_ms": latencies[max(0, math.ceil(len(latencies) * .95) - 1)],
            "mean_context_request_latency_ms":mean("context_request_latency_ms"),
            "mean_total_case_latency_ms":mean("total_latency_ms", rows),
            "mean_context_bytes": mean("context_bytes"), "context_tokens": None,
            "failure_rate": sum(r["failure"] for r in rows) / len(rows),
            "retrieval_failure_rate":sum(r["failure"] and r["failure_stage"] == "retrieval" for r in rows) / len(rows),
            "context_failure_rate":sum(r["failure"] and r["failure_stage"] == "context" for r in rows) / len(rows),
            "unavailable_cases": sum(not r["available"] for r in rows),
        }, "cases": rows}
    return {"schema_version": 1, "case_count": len(cases), "limit": limit, "budget_bytes": budget,
            "dataset_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
            "corpus_sha256":hashlib.sha256(json.dumps(corpus,sort_keys=True).encode()).hexdigest(),
            "memory_corpus_sha256":hashlib.sha256(json.dumps(memory_corpus,sort_keys=True).encode()).hexdigest(),
            "embedding_model": service.store.embedding_backend.model_id,
            "gates": {"boundary_violations": 0, "stale_context": 0, "failure_rate": 0,
                      "heldout_recall_regression_tolerance": 0,
                      "no_evidence_accuracy_required": 1.0},
            "notes": "File/symbol labels; binary source relevance. Irrelevant context ratio grades knowledge units only; memory counts and eligibility are separate. No-evidence checks both knowledge and memories. p50/p95 measure search_knowledge alone; context latency includes its own retrieval. Tokens unavailable without client tokenizer.",
            "strategies": reports}


def compare_core(baseline, final):
    for key in ("dataset_sha256","corpus_sha256","memory_corpus_sha256","limit","budget_bytes","embedding_model"):
        if baseline.get(key) != final.get(key):
            raise ValueError("benchmark provenance/budgets differ: " + key)
    checks = {}
    for strategy, report in final["strategies"].items():
        before = baseline["strategies"][strategy]
        metrics = report["metrics"]
        def heldout_recall(value):
            rows = [r["recall_at_5"] for r in value["cases"] if not r["failure"] and r["split"] == "heldout" and r["answerable"]]
            return statistics.fmean(rows) if rows else 0
        checks[strategy] = {
            "isolation":metrics["boundary_violations"] == 0,
            "freshness":metrics["stale_context"] == 0,
            "memory_eligibility":metrics["ineligible_memory_units"] == 0,
            "availability":metrics["failure_rate"] == 0 and metrics["unavailable_cases"] == 0,
            "heldout_recall":heldout_recall(report) >= heldout_recall(before),
            "no_evidence":metrics["no_evidence_accuracy"] == 1,
            "heldout_recall_baseline":heldout_recall(before),"heldout_recall_final":heldout_recall(report),
        }
    passed = all(all(row[k] for k in ("isolation","freshness","memory_eligibility","availability","heldout_recall","no_evidence")) for row in checks.values())
    return {"passed":passed,"checks":checks,"scope":"frozen authorized evaluation corpus only; not semantic answer certification"}


def main(argv=None):
    import argparse
    from contextlib import closing
    from .config import Config
    from .knowledge import KnowledgeService
    parser = argparse.ArgumentParser(description="Compare scoped core retrieval on a labeled, authorized corpus")
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--dataset", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--baseline", type=pathlib.Path, help="Enforce fixed safety/no-regression gates against a comparable baseline")
    args = parser.parse_args(argv)
    cases = json.loads(args.dataset.read_text())["cases"]
    if len(cases) < 1:
        raise ValueError("empty evaluation")
    with closing(KnowledgeService(Config.load(args.config.absolute()), read_only=True)) as service:
        report = evaluate_core(service, cases)
    if args.baseline:
        report["comparison"] = compare_core(json.loads(args.baseline.read_text()), report)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v["metrics"] for k, v in report["strategies"].items()}, indent=2))
    return 0 if not args.baseline or report["comparison"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
