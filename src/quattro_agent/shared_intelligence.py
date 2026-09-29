"""Client-neutral, lazy access to Quattro's local knowledge and RTK tools.

This module has no routing, model, provider, task, or supervisor dependency.
"""

from __future__ import annotations

import json
import hashlib
import os
import pathlib
import shutil
import sqlite3
import subprocess
import time
import uuid
from typing import Any

from .config import load_ai_config
from .errors import ConfigError
from .retrieval import (
    ContextAssembler, QueryRouter, RepositoryIndexer, RetrievalStore,
    allowed_origins_for_route, repository_state,
)
from .native_intelligence import (
    NativeContext, NativeTelemetry, load_native_settings, native_event,
    native_jev_advice, split_native_context,
)
from .decision_service import DecisionSession
from quattro_memory import MemoryError as VaultConfigError, memory_settings, project_memory_path

MAX_QUERY = 2_000
MAX_BUDGET = 4_000
MAX_RESULTS = 8
RTK_COMMANDS = frozenset({"git", "rg", "ls", "cat", "pytest", "cargo", "npm", "pnpm", "yarn", "bun", "go", "python"})


def _state_root() -> pathlib.Path:
    from .paths import state_root
    return state_root()


def _directory(value: str | None) -> pathlib.Path:
    path = pathlib.Path(value or os.getcwd()).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("directory must exist")
    return path


def _index_memory(store: RetrievalStore, root: pathlib.Path) -> str:
    config_path = pathlib.Path.home() / ".config/quattro/ai.json"
    if not config_path.is_file():
        return "disabled"
    try:
        config = load_ai_config(config_path)
        enabled, vault, _enforced = memory_settings(config)
        project_vault = project_memory_path(config)
    except (ConfigError, ValueError, VaultConfigError) as error:
        raise ValueError(f"shared intelligence configuration is malformed: {error}") from error
    if not enabled:
        return "disabled"
    shared = vault / "Shared"
    project_notes = project_vault / root.name
    if not shared.is_dir() or shared.is_symlink():
        return "unavailable"
    indexer = RepositoryIndexer(store)
    shared_result = indexer.index(shared, global_scope=True,
                                  origin="institutional_memory", trusted_non_git=True)
    project_result = None
    if project_vault.is_dir() and not project_vault.is_symlink() and project_notes.is_dir() and not project_notes.is_symlink():
        project_result = indexer.index(project_notes, scope_repository=str(root),
                                       origin="institutional_memory", trusted_non_git=True)
    return "partial" if (shared_result.budget_exhausted or
                         (project_result and project_result.budget_exhausted)) else "available"


def _index_episodes(store: RetrievalStore, repository: str, *, full: bool = False) -> str:
    """Refresh project episodes directly, with a cheap recent-search default."""
    database = _state_root() / "private/harness.sqlite3"
    if not database.is_file() or database.is_symlink():
        return "unavailable"
    connection = None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        task_query = ("SELECT task_id,project_path,display_title,state,terminal_code,terminal_summary,created_at "
                      "FROM tasks WHERE project_path=? ORDER BY created_at DESC")
        tasks = list(connection.execute(task_query + ("" if full else " LIMIT 100"), (repository,)))
        if not tasks:
            return "complete" if full else "recent_only"
        if full:
            task_filter = "task_id IN (SELECT task_id FROM tasks WHERE project_path=?)"
            parameters = [repository]
        else:
            task_filter = "task_id IN (" + ",".join("?" for _ in tasks) + ")"
            parameters = [row["task_id"] for row in tasks]
        events = list(connection.execute(
            f"SELECT event_id,task_id,event_type,display_payload_json,created_at "
            f"FROM events WHERE {task_filter} ORDER BY sequence DESC" +
            ("" if full else " LIMIT 200"), parameters))
        checkpoints = list(connection.execute(
            f"SELECT checkpoint_id,task_id,quattro_session_id,kind,content_json,created_at "
            f"FROM session_checkpoints WHERE {task_filter} ORDER BY created_at DESC" +
            ("" if full else " LIMIT 100"), parameters))
    except sqlite3.Error:
        return "unavailable"
    finally:
        if connection is not None:
            connection.close()

    def add(identifier: str, source_type: str, content: str, **kwargs: Any) -> None:
        content = content[:4_000]
        digest = hashlib.sha256(content.encode()).hexdigest()
        old = store.connection.execute(
            "SELECT content_hash FROM documents WHERE id=?", (identifier,)).fetchone()
        if old and old[0] == digest:
            return
        try:
            store.upsert_document(identifier=identifier, source_type=source_type,
                                  content=content, repository=repository,
                                  origin="episodic", **kwargs)
        except ValueError:  # Exclude credential-shaped historical material.
            pass

    for row in tasks:
        content = json.dumps({"title": row["display_title"], "state": row["state"],
                              "terminalCode": row["terminal_code"],
                              "terminalSummary": row["terminal_summary"]}, sort_keys=True)
        add(f"task_{row['task_id']}", "task", content,
            task_id=row["task_id"], valid_from=row["created_at"],
            importance=.6, metadata={"displaySafe": True})
    for row in events:
        kind = "error" if any(word in row["event_type"] for word in
                              ("fail", "error", "interrupt", "timeout")) else "session"
        add(f"event_{row['event_id']}", kind,
            f"{row['event_type']}: {row['display_payload_json']}",
            task_id=row["task_id"], valid_from=row["created_at"],
            importance=.58, metadata={"displaySafe": True, "eventType": row["event_type"]})
    for row in checkpoints:
        add(f"episode_{row['checkpoint_id']}", "checkpoint", row["content_json"],
            task_id=row["task_id"], session_id=row["quattro_session_id"],
            valid_from=row["created_at"], importance=.78,
            metadata={"kind": row["kind"], "provenance": "harness.sqlite3"})
    return "complete" if full else "recent_only"


def refresh_history(*, directory: str | None = None,
                    telemetry_context: NativeContext | None = None) -> dict[str, Any]:
    root = _directory(directory)
    state = repository_state(root)
    settings = load_native_settings()
    telemetry = NativeTelemetry(enabled=settings.telemetry_enabled)
    native_context = telemetry_context or NativeContext(host="cli", project=str(root))
    trace_id = "history-" + uuid.uuid4().hex[:20]
    telemetry.record(kind="retrieval", stage="index_refresh", status="REQUESTED", context=native_context,
                     trace_id=trace_id, metadata={"answer": False})
    with RetrievalStore(_state_root() / "private/retrieval.sqlite3") as store:
        status = _index_episodes(store, state["repository"], full=True)
    telemetry.record(kind="retrieval", stage="index_refresh", status="COMPLETED", context=native_context,
                     trace_id=trace_id, metadata={"answer": False, "episodic": status})
    return {"repository": state["repository"], "episodic": status,
            "usageEvidence": {"traceId": trace_id, "answer": False}}


def search_knowledge(query: str, *, directory: str | None = None,
                     budget: int = 2_000, limit: int = 5,
                     telemetry_context: NativeContext | None = None) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
        raise ValueError("query must contain 1 to 2000 characters")
    if type(budget) is not int or not 2_000 <= budget <= MAX_BUDGET:
        raise ValueError("budget must be between 2000 and 4000 tokens")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be between 1 and 8")
    settings = load_native_settings()
    telemetry = NativeTelemetry(enabled=settings.telemetry_enabled)
    root = _directory(directory)
    native_context = telemetry_context or NativeContext(host="cli", project=str(root))
    trace_id = "retrieval-" + uuid.uuid4().hex[:20]
    requested_at = time.perf_counter()
    telemetry.record(kind="retrieval", stage="retrieval_requested", status="REQUESTED", context=native_context,
                     trace_id=trace_id, metadata={"budget": budget, "limit": limit})
    if not settings.retrieval_enabled:
        telemetry.record(kind="retrieval", stage="skipped", status="SKIPPED", context=native_context,
                         trace_id=trace_id, metadata={"reason": "disabled"})
        return {"route": "disabled", "context": None, "retrievedTokens": 0,
                "usageEvidence": {"traceId": trace_id, "requested": True,
                                   "completed": False, "sourcesSelected": 0,
                                   "resultReturned": True, "contextDelivery": "UNVERIFIED",
                                   "skipReason": "disabled"}}
    route = QueryRouter().route(query)
    if route.intent == "no_retrieval":
        telemetry.record(kind="retrieval", stage="skipped", status="SKIPPED", context=native_context,
                         trace_id=trace_id, metadata={"reason": "no_retrieval", "latencyMs": (time.perf_counter() - requested_at) * 1000})
        return {"route": route.intent, "context": None, "retrievedTokens": 0,
                "usageEvidence": {"traceId": trace_id, "requested": True,
                                   "completed": False, "sourcesSelected": 0,
                                   "resultReturned": True, "contextDelivery": "UNVERIFIED",
                                   "skipReason": "no_retrieval"}}
    state = repository_state(root)
    if route.intent == "live_state":
        telemetry.record(kind="retrieval", stage="retrieval_completed", status="COMPLETED", context=native_context,
                         trace_id=trace_id, metadata={"route": route.intent, "resultCount": 0,
                                                       "latencyMs": (time.perf_counter() - requested_at) * 1000})
        telemetry.record(kind="retrieval", stage="result_returned", status="RETURNED", context=native_context,
                         trace_id=trace_id, metadata={"route": route.intent, "contextTokensEstimated": 0})
        return {"route": route.intent, "context": {"structuredState": state}, "retrievedTokens": 0,
                "usageEvidence": {"traceId": trace_id, "requested": True,
                                   "completed": True, "sourcesSelected": 0,
                                   "resultReturned": True, "contextDelivery": "UNVERIFIED"}}
    with RetrievalStore(_state_root() / "private/retrieval.sqlite3") as store:
        # Only tool invocation pays indexing cost. The indexer has its own file,
        # byte, unit, and five-second limits and skips unchanged Git files.
        indexed = RepositoryIndexer(store).index(root)
        origins = allowed_origins_for_route(route, memory_allowed=True)
        memory = _index_memory(store, pathlib.Path(state["repository"])) if "institutional_memory" in origins else "not_requested"
        episodic = _index_episodes(store, state["repository"]) if "episodic" in origins else "not_requested"
        results, _trace = store.search(
            query, repository=state["repository"], branch=state["branch"],
            source_types=route.sources, use_lexical=route.use_lexical,
            use_semantic=route.use_semantic, use_graph=route.use_graph,
            historical=route.historical, limit=limit,
            allowed_origins=origins,
        )
        assembled = ContextAssembler().assemble(
            request=query, structured_state=state, results=results,
            budget_tokens=budget, include_request=False,
        )
    selected = _trace.get("selected", []) if isinstance(_trace, dict) else []
    source_categories = sorted({str(item.get("source")) for item in selected
                                if isinstance(item, dict) and item.get("source")})
    source_ids = [
        "sha256:" + hashlib.sha256(str(item.get("id")).encode("utf-8", "replace")).hexdigest()[:20]
        for item in selected if isinstance(item, dict) and item.get("id") is not None
    ][:8]
    retrieved_tokens = assembled["budget"]["retrievedUsed"]
    evidence = {
        "traceId": trace_id, "requested": True, "completed": True,
        "sourcesSelected": len(selected), "resultReturned": True,
        "contextDelivery": "UNVERIFIED", "sourceCategories": source_categories,
        "sourceIdsHashed": source_ids, "indexPartial": indexed.budget_exhausted,
        "indexCoverage": "partial" if indexed.budget_exhausted else "bounded_current_scope",
        "contextTokensEstimated": retrieved_tokens, "contextTokensExact": None,
        "latencyMs": (time.perf_counter() - requested_at) * 1000,
        "cacheHit": bool(_trace.get("cacheHit")) if isinstance(_trace, dict) else None,
        "candidateCount": _trace.get("candidateCount") if isinstance(_trace, dict) else None,
    }
    telemetry.record(kind="retrieval", stage="retrieval_completed", status="COMPLETED", context=native_context,
                     trace_id=trace_id, metadata={key: value for key, value in evidence.items()
                                                   if key not in {"traceId", "contextDelivery"}})
    telemetry.record(kind="retrieval", stage="sources_selected", status="SELECTED", context=native_context,
                     trace_id=trace_id, metadata={"count": len(selected),
                                                   "sourceCategories": source_categories,
                                                   "sourceIdsHashed": source_ids})
    telemetry.record(kind="retrieval", stage="result_returned", status="RETURNED", context=native_context,
                     trace_id=trace_id, metadata={"contextTokensEstimated": retrieved_tokens,
                                                   "resultCount": len(results)})
    return {"route": route.intent, "context": assembled,
            "retrievedTokens": retrieved_tokens,
            "indexPartial": indexed.budget_exhausted, "memory": memory,
            "episodic": episodic, "usageEvidence": evidence}


def rtk_status(*, telemetry_context: NativeContext | None = None) -> dict[str, Any]:
    settings = load_native_settings()
    telemetry = NativeTelemetry(enabled=settings.telemetry_enabled)
    context = telemetry_context or NativeContext(host="cli")
    trace_id = "rtk-status-" + uuid.uuid4().hex[:16]
    binary = shutil.which("rtk")
    if binary is None:
        telemetry.record(kind="rtk", stage="status_checked", status="UNAVAILABLE", context=context,
                         trace_id=trace_id, metadata={"actualCommand": False})
        return {"available": False, "reason": "rtk is not installed or is absent from PATH",
                "usageEvidence": {"traceId": trace_id, "statusChecked": True,
                                   "actualCommand": False}}
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        telemetry.record(kind="rtk", stage="status_checked", status="ERROR", context=context,
                         trace_id=trace_id, metadata={"reason": type(error).__name__, "actualCommand": False})
        return {"available": False, "reason": type(error).__name__,
                "usageEvidence": {"traceId": trace_id, "statusChecked": True,
                                   "actualCommand": False}}
    telemetry.record(kind="rtk", stage="status_checked", status="AVAILABLE" if result.returncode == 0 else "FAILED",
                     context=context, trace_id=trace_id,
                     metadata={"version": result.stdout.strip()[:100], "actualCommand": False})
    return {"available": result.returncode == 0, "version": result.stdout.strip()[:100],
            "usageEvidence": {"traceId": trace_id, "statusChecked": True,
                               "actualCommand": False}}


def rtk_run(command: list[str], *, directory: str | None = None,
            telemetry_context: NativeContext | None = None) -> dict[str, Any]:
    binary = shutil.which("rtk")
    if binary is None:
        raise RuntimeError("rtk is unavailable; use the native shell tool")
    if (not isinstance(command, list) or not command or len(command) > 32
            or not all(isinstance(part, str) and part and len(part) <= 1_000 for part in command)
            or command[0] not in RTK_COMMANDS):
        raise ValueError("command must be an argument array beginning with an allowed RTK command")
    settings = load_native_settings()
    telemetry = NativeTelemetry(enabled=settings.telemetry_enabled)
    context = telemetry_context or NativeContext(host="cli", project=directory)
    trace_id = "rtk-" + uuid.uuid4().hex[:20]
    started = time.perf_counter()
    telemetry.record(kind="rtk", stage="requested", status="REQUESTED", context=context,
                     trace_id=trace_id, metadata={"command": command[0], "argumentCount": len(command)})
    try:
        result = subprocess.run([binary, *command], cwd=_directory(directory),
                                capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("rtk command exceeded 30 seconds") from error
    telemetry.record(kind="rtk", stage="executed", status="COMPLETED", context=context,
                     trace_id=trace_id, metadata={"command": command[0], "exitCode": result.returncode,
                                                   "latencyMs": (time.perf_counter() - started) * 1000})
    telemetry.record(kind="rtk", stage="command_result", status="RETURNED", context=context,
                     trace_id=trace_id, metadata={"stdoutBytes": len(result.stdout.encode("utf-8", "replace")),
                                                   "stderrBytes": len(result.stderr.encode("utf-8", "replace"))})
    return {"exitCode": result.returncode, "stdout": result.stdout[:16_000],
            "stderr": result.stderr[:4_000],
            "truncated": len(result.stdout) > 16_000 or len(result.stderr) > 4_000,
            "usageEvidence": {"traceId": trace_id, "statusChecked": False,
                               "actualCommand": True, "resultReturned": True}}


def image_generate(prompt: str, *, size: str | None = None,
                   directory: str | None = None) -> dict[str, Any]:
    # Reuse the existing credential-free image bridge. Its output remains a
    # private project file; Pi receives only the path, not a large base64 blob.
    from quattro_image_mcp import ImageBridgeError, generate_image

    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8_000:
        raise ValueError("image prompt must contain 1 to 8000 characters")
    root = _directory(directory)
    try:
        arguments = {"prompt": prompt}
        if size is not None:
            arguments["size"] = size
        result = generate_image(arguments, project_root=root)
    except ImageBridgeError as error:
        raise RuntimeError(str(error)) from error
    return result["structuredContent"]


def call(name: str, arguments: dict[str, Any], *, telemetry_context: NativeContext | None = None,
         decision_session: DecisionSession | None = None) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    clean, embedded_context = split_native_context(arguments)
    context = telemetry_context or embedded_context
    if name == "search_knowledge":
        return search_knowledge(clean.get("query"), directory=clean.get("directory"),
                                budget=clean.get("budget", 2_000), limit=clean.get("limit", 5),
                                telemetry_context=context)
    if name == "rtk_status":
        return rtk_status(telemetry_context=context)
    if name == "rtk_run":
        return rtk_run(clean.get("command"), directory=clean.get("directory"),
                       telemetry_context=context)
    if name == "image_generate":
        return image_generate(clean.get("prompt"), size=clean.get("size"),
                              directory=clean.get("directory"))
    if name == "refresh_history":
        return refresh_history(directory=clean.get("directory"), telemetry_context=context)
    if name == "operational_decision":
        return native_jev_advice(clean, context=context, decision_session=decision_session)
    if name == "jev_advice":
        return native_jev_advice(clean, context=context, decision_session=decision_session)
    if name == "native_event":
        return native_event(arguments)
    raise ValueError(f"unknown shared intelligence tool: {name}")


def cli_main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Client-neutral Quattro intelligence tools")
    parser.add_argument("name", choices=("search_knowledge", "rtk_status", "rtk_run", "image_generate",
                                         "refresh_history", "jev_advice", "native_event", "operational_decision"))
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    try:
        print(json.dumps(call(args.name, json.loads(args.arguments)), ensure_ascii=False))
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
