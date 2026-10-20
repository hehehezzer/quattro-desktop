#!/usr/bin/python3
"""Read-only desktop projection of the standalone Intelligence operator CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

HOME = Path.home()
MODES = ("knowledge", "context", "memory")


def runtime():
    search_path = str(HOME / ".local/bin") + os.pathsep + os.environ.get("PATH", os.defpath)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
    config = config_home / "quattro/intelligence.json"
    executable = shutil.which("quattro-intelligence", path=search_path)
    if not executable or not config.is_file():
        raise FileNotFoundError("Intelligence runtime unavailable")
    return [executable, "--config", str(config)], search_path


def call(command, args, search_path):
    result = subprocess.run(command + args, cwd=HOME,
                            env={"HOME": str(HOME), "PATH": search_path, "LANG": "C.UTF-8"},
                            capture_output=True, timeout=15, check=True)
    if len(result.stdout) > 1048576:
        raise ValueError("oversized Intelligence response")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("invalid Intelligence response")
    return value


def text(value, limit=24000):
    return value[:limit] if isinstance(value, str) else ""


def semantic(value):
    info = value.get("semantic") or {}
    available = info.get("available") is True
    return {"semanticAvailable": available, "retrievalMode": "Hybrid" if available else "Lexical",
            "embeddingBackend": text(info.get("backend"), 128)}


def status(command, search_path):
    diagnostics = call(command, ["diagnostics"], search_path)
    indexes = call(command, ["index-status"], search_path).get("projects", {})
    memories = call(command, ["memory", "stats"], search_path).get("projects", {})
    health = diagnostics.get("health") or {}
    projects = []
    for project in diagnostics.get("projects", []):
        index = indexes.get(project) or {}
        memory = memories.get(project) or {}
        projects.append({"id": project, "documents": index.get("documents"), "files": index.get("files"),
                         "memories": memory.get("total"),
                         "sources": [{"id": text(source.get("source_id"), 128),
                                      "indexedAt": text(source.get("indexed_at"), 64),
                                      "documents": source.get("documents"), "files": source.get("files")}
                                     for source in index.get("sources", [])]})
    return {"schemaVersion": 1, "status": "ready" if health.get("ok") else "unavailable",
            "message": "" if health.get("ok") else "Intelligence storage needs attention.",
            "projects": projects, "database": text(health.get("database"), 64),
            "memoryDatabase": text(health.get("memory_database"), 64), **semantic(health)}


def evidence(record, memory=False):
    citation = record.get("citation") or {}
    return {"title": text(record.get("symbol") or record.get("title") or
                          (record.get("fact_key") if memory else citation.get("path")) or
                          ("Project memory" if memory else "Evidence"), 256),
            "path": text(citation.get("path"), 1024), "line": citation.get("start_line"),
            "endLine": citation.get("end_line"), "content": text(record.get("content")),
            "source": text(citation.get("source_id"), 128),
            "provenance": text(citation.get("provenance"), 64),
            "commit": text(citation.get("commit_sha"), 64),
            "verification": text(record.get("verification"), 64) if memory else "",
            "references": [text(item, 1024) for item in record.get("references", [])[:12]] if memory else []}


def search(command, search_path, project, mode, query):
    diagnostics = call(command, ["diagnostics"], search_path)
    if project not in diagnostics.get("projects", []):
        raise ValueError("project unavailable")
    query = query.strip()
    if not query or len(query) > 4096 or mode not in MODES:
        raise ValueError("invalid search")
    args = ["memory", "recall"] if mode == "memory" else ["query" if mode == "knowledge" else "context"]
    args += ["--project", project, "--limit", "12"]
    if mode == "context":
        args += ["--budget", "3000"]
    args += ["--", query]
    result = call(command, args, search_path)
    rows = ([evidence(row) for row in result.get("knowledge", [])] +
            [evidence(row, True) for row in result.get("memories", [])]) if mode == "context" else [
                evidence(row, mode == "memory") for row in result.get("results", [])]
    return {"schemaVersion": 1, "status": "ready", "mode": mode, "project": project,
            "results": rows, "total": result.get("total", len(rows)), "budget": result.get("budget", {}),
            "conflicts": len(result.get("conflicts", [])), "outdated": len(result.get("outdated", [])),
            **semantic(result if "semantic" in result else diagnostics.get("health") or {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    query = commands.add_parser("search")
    query.add_argument("--project", required=True)
    query.add_argument("--mode", choices=MODES, required=True)
    query.add_argument("--query", required=True)
    args = parser.parse_args()
    try:
        command, search_path = runtime()
        value = status(command, search_path) if args.command == "status" else search(
            command, search_path, args.project, args.mode, args.query)
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        value = {"schemaVersion": 1, "status": "unavailable", "results": [], "projects": [],
                 "message": "Intelligence unavailable. Check the core runtime and configured project."}
    print(json.dumps(value, allow_nan=False))


if __name__ == "__main__":
    main()
