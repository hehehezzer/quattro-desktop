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
from typing import Any

from .config import load_ai_config
from .errors import ConfigError
from .retrieval import (
    ContextAssembler, QueryRouter, RepositoryIndexer, RetrievalStore,
    allowed_origins_for_route, repository_state,
)
from quattro_memory import MemoryError as VaultConfigError, memory_settings, project_memory_path

MAX_QUERY = 2_000
MAX_BUDGET = 4_000
MAX_RESULTS = 8
RTK_COMMANDS = frozenset({"git", "rg", "ls", "cat", "pytest", "cargo", "npm", "pnpm", "yarn", "bun", "go", "python"})


def _state_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state")) / "quattro/agents"


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


def refresh_history(*, directory: str | None = None) -> dict[str, Any]:
    root = _directory(directory)
    state = repository_state(root)
    with RetrievalStore(_state_root() / "private/retrieval.sqlite3") as store:
        status = _index_episodes(store, state["repository"], full=True)
    return {"repository": state["repository"], "episodic": status}


def search_knowledge(query: str, *, directory: str | None = None,
                     budget: int = 2_000, limit: int = 5) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
        raise ValueError("query must contain 1 to 2000 characters")
    if type(budget) is not int or not 2_000 <= budget <= MAX_BUDGET:
        raise ValueError("budget must be between 2000 and 4000 tokens")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be between 1 and 8")
    route = QueryRouter().route(query)
    if route.intent == "no_retrieval":
        return {"route": route.intent, "context": None, "retrievedTokens": 0}
    root = _directory(directory)
    state = repository_state(root)
    if route.intent == "live_state":
        return {"route": route.intent, "context": {"structuredState": state}, "retrievedTokens": 0}
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
        context = ContextAssembler().assemble(
            request=query, structured_state=state, results=results,
            budget_tokens=budget, include_request=False,
        )
    return {"route": route.intent, "context": context,
            "retrievedTokens": context["budget"]["retrievedUsed"],
            "indexPartial": indexed.budget_exhausted, "memory": memory,
            "episodic": episodic}


def rtk_status() -> dict[str, Any]:
    binary = shutil.which("rtk")
    if binary is None:
        return {"available": False, "reason": "rtk is not installed or is absent from PATH"}
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "reason": type(error).__name__}
    return {"available": result.returncode == 0, "version": result.stdout.strip()[:100]}


def rtk_run(command: list[str], *, directory: str | None = None) -> dict[str, Any]:
    binary = shutil.which("rtk")
    if binary is None:
        raise RuntimeError("rtk is unavailable; use the native shell tool")
    if (not isinstance(command, list) or not command or len(command) > 32
            or not all(isinstance(part, str) and part and len(part) <= 1_000 for part in command)
            or command[0] not in RTK_COMMANDS):
        raise ValueError("command must be an argument array beginning with an allowed RTK command")
    try:
        result = subprocess.run([binary, *command], cwd=_directory(directory),
                                capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("rtk command exceeded 30 seconds") from error
    return {"exitCode": result.returncode, "stdout": result.stdout[:16_000],
            "stderr": result.stderr[:4_000],
            "truncated": len(result.stdout) > 16_000 or len(result.stderr) > 4_000}


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


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    if name == "search_knowledge":
        return search_knowledge(arguments.get("query"), directory=arguments.get("directory"),
                                budget=arguments.get("budget", 2_000), limit=arguments.get("limit", 5))
    if name == "rtk_status":
        return rtk_status()
    if name == "rtk_run":
        return rtk_run(arguments.get("command"), directory=arguments.get("directory"))
    if name == "image_generate":
        return image_generate(arguments.get("prompt"), size=arguments.get("size"),
                              directory=arguments.get("directory"))
    if name == "refresh_history":
        return refresh_history(directory=arguments.get("directory"))
    raise ValueError(f"unknown shared intelligence tool: {name}")


def cli_main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Client-neutral Quattro intelligence tools")
    parser.add_argument("name", choices=("search_knowledge", "rtk_status", "rtk_run", "image_generate", "refresh_history"))
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
