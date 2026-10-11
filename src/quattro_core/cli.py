"""Operator CLI for configured, independent Quattro intelligence storage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .config import Config, Source, default_config_path, register_source
from .knowledge import migrate_legacy_database
from .mcp import McpRuntime, PATCH_FIELDS, TOOL_MAP, obj, serve, strict_json, validate

MAX_OPERATOR_CONTENT = 1048576


class OperatorParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command arguments; use --help for accepted options\n")


def _project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="Configured project identifier")


def _page(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=10, help="Result count (1–50)")
    parser.add_argument("--offset", type=int, default=0, help="Pagination offset (0–100000)")


def _content(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--content", help="Short memory content (up to 16384 characters)")
    group.add_argument("--file", type=Path, help="Read larger content from this local operator file (store limit: 24000 UTF-8 bytes)")
    group.add_argument("--stdin", action="store_true", help="Read larger content from stdin (store limit: 24000 UTF-8 bytes)")


def parser() -> argparse.ArgumentParser:
    root = OperatorParser(description="Quattro independent intelligence: retrieval and durable project memory, without an agent runtime")
    root.add_argument("--config", type=Path, default=None, help="Operator-owned JSON config (default ~/.config/quattro/intelligence.json)")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("config-init", help="Create a new explicit, read-only-by-default configuration")
    init.add_argument("--database-dir", type=Path, required=True)
    init.add_argument("--project", action="append", required=True, help="Allowed project; repeat for multiple projects")
    init.add_argument("--principal", default="local", help="Trusted local identity, never supplied by MCP callers")
    init.add_argument("--writable", action="store_true", help="Explicitly permit memory mutations and indexing")
    init.add_argument("--can-verify", action="store_true", help="Explicitly permit verified memory writes (requires --writable)")
    init.add_argument("--embedding", choices=("lexical", "local-neural"), default="lexical")
    commands.add_parser("serve", help="Serve bounded JSON-lines MCP on stdin/stdout")
    commands.add_parser("health", help="Report core storage and semantic availability")
    commands.add_parser("diagnostics", help="Report safe runtime diagnostics, without credentials or content")
    register = commands.add_parser("register-source", help="Register an operator-controlled source; never accepted over MCP")
    _project(register)
    register.add_argument("--id", required=True)
    register.add_argument("--root", type=Path, required=True)
    register.add_argument("--kind", choices=("repository", "documentation", "obsidian"), default="repository")
    register.add_argument("--exclude", action="append", default=[])
    index = commands.add_parser("index", help="Index or reindex one registered source")
    index.add_argument("source")
    index.add_argument("--reindex", action="store_true", help="Force rebuilding the registered source index")
    reindex = commands.add_parser("reindex", help="Force rebuilding one registered source index")
    reindex.add_argument("source")
    for name in ("query", "context"):
        command = commands.add_parser(name, help="Search project evidence" if name == "query" else "Build cited evidence and prior-memory context within a byte budget")
        _project(command)
        command.add_argument("query")
        command.add_argument("--limit", type=int, default=10)
        command.add_argument("--source-id", action="append", help="Restrict evidence to registered sources; repeat as needed")
        if name == "query":
            command.add_argument("--offset", type=int, default=0)
        else:
            command.add_argument("--budget", type=int, default=2000, help="Conservative UTF-8 byte budget (512–32768)")
    status = commands.add_parser("index-status", help="Index status for allowed projects only")
    status.add_argument("--project")
    backup = commands.add_parser("backup", help="Create consistent local SQLite backups of both databases; original databases remain unchanged")
    backup.add_argument("destination", type=Path, help="New directory for operator-owned backup files")
    migrate = commands.add_parser("migrate", help="Copy compatible legacy retrieval database; unassigned rows are quarantined, originals untouched")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("--project", help="Explicitly map legacy rows to this allowed project")
    migrate.add_argument("--source-id", help="Explicit registered source mapping; requires --project")
    memory = commands.add_parser("memory", help="Persistent project memory operations")
    memories = memory.add_subparsers(dest="memory_command", required=True)
    stats = memories.add_parser("stats", help="Memory counts restricted to configured projects and principal")
    stats.add_argument("--project")
    save = memories.add_parser("save", help="Save memory attributed to configured principal; secrets are rejected")
    _project(save)
    _content(save)
    save.add_argument("--category", default="semantic")
    save.add_argument("--confidence", type=float, default=0.5)
    save.add_argument("--verification", choices=("unverified", "verified", "disputed"), default="unverified")
    save.add_argument("--visibility", choices=("project", "private"), default="project")
    save.add_argument("--tag", action="append", default=[])
    save.add_argument("--reference", action="append", default=[])
    save.add_argument("--fact-key")
    save.add_argument("--supersedes")
    recall = memories.add_parser("recall", help="Recall active memories, with explicit historical access and pagination")
    _project(recall)
    _page(recall)
    recall.add_argument("query", nargs="?", default="")
    recall.add_argument("--historical", action="store_true")
    recall.add_argument("--category")
    recall.add_argument("--tag", action="append")
    recall.add_argument("--verification", choices=("unverified", "verified", "disputed"))
    update = memories.add_parser("update", help="Update a memory with optional optimistic expected revision")
    _project(update)
    update.add_argument("id")
    _content(update, required=False)
    update.add_argument("--patch", type=Path, help="Local JSON object containing allowed update fields")
    update.add_argument("--expected-revision", type=int)
    update.add_argument("--verification", choices=("unverified", "verified", "disputed"))
    invalidate = memories.add_parser("invalidate", help="Invalidate an accessible memory and record a reason")
    _project(invalidate)
    invalidate.add_argument("id")
    invalidate.add_argument("--reason", required=True)
    delete = memories.add_parser("delete", help="Delete an accessible memory")
    _project(delete)
    delete.add_argument("id")
    return root


def _local_path(path: Path, *, exists: bool = False) -> Path:
    if ".." in path.parts:
        raise ValueError("traversal path")
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink path")
    if exists and not path.is_file():
        raise ValueError("input file unavailable")
    return path


def _read_file(path: Path) -> bytes:
    with _local_path(path, exists=True).open("rb") as stream:
        data = stream.read(MAX_OPERATOR_CONTENT + 1)
    if len(data) > MAX_OPERATOR_CONTENT:
        raise ValueError("operator content limit")
    return data


def _read_content(args: argparse.Namespace) -> str | None:
    if args.file is not None:
        data = _read_file(args.file)
    elif args.stdin:
        data = sys.stdin.buffer.read(MAX_OPERATOR_CONTENT + 1)
        if len(data) > MAX_OPERATOR_CONTENT:
            raise ValueError("operator content limit")
    else:
        if args.content is not None and len(args.content) > 16384:
            raise ValueError("use stdin/file for large content")
        return args.content
    return data.decode("utf-8")


def _backup(config: Config, destination: Path) -> dict:
    destination = _local_path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    copied = []
    for name in ("memory.sqlite3", "retrieval.sqlite3"):
        source = _local_path(config.database_dir / name, exists=True)
        target = destination / name
        # Mode=ro avoids creating a missing source; SQLite backup includes WAL.
        original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            target.touch(mode=0o600, exist_ok=False)
            replica = sqlite3.connect(target)
            try:
                original.backup(replica)
            finally:
                replica.close()
        finally:
            original.close()
        copied.append(name)
    return {"backed_up": copied}


def execute(args: argparse.Namespace) -> Any:
    path = _local_path(args.config or default_config_path())
    if args.command == "config-init":
        if path.exists():
            raise ValueError("configuration already exists")
        if args.can_verify and not args.writable:
            raise ValueError("verification requires write permission")
        config = Config.from_dict({"version": 1, "database_dir": str(args.database_dir.absolute()),
                                  "projects": args.project, "sources": [], "principal": args.principal,
                                  "writable": args.writable, "can_verify": args.can_verify, "embedding": args.embedding})
        config.save(path)
        return {"configured": True, "projects": list(config.projects), "writable": config.writable, "can_verify": config.can_verify}
    config = Config.load(path)
    if args.command == "serve":
        return serve(config)
    if args.command == "register-source":
        config.authorize(args.project)
        register_source(path, Source(args.id, args.project, args.root.absolute(), args.kind, tuple(args.exclude)))
        return {"registered": args.id, "project": args.project}
    if args.command == "backup":
        return _backup(config, args.destination)
    if args.command == "migrate":
        if not config.writable:
            raise PermissionError("migration requires write permission")
        if bool(args.project) != bool(args.source_id):
            raise ValueError("mapping requires project and source")
        if args.project:
            config.authorize(args.project, write=True)
            if config.source(args.source_id).project != args.project:
                raise PermissionError("source project mismatch")
        return migrate_legacy_database(_local_path(args.source, exists=True), config.database_dir / "retrieval.sqlite3",
                                       project=args.project, source_id=args.source_id,
                                       source_root=config.source(args.source_id).root if args.source_id else None)
    runtime = McpRuntime(config)
    try:
        if args.command in ("health", "diagnostics"):
            health = runtime.service.health()
            if args.command == "diagnostics":
                return {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                        "projects": list(config.projects), "source_count": len(config.sources),
                        "writable": config.writable, "can_verify": config.can_verify, "health": health}
            return health
        if args.command in ("index", "reindex"):
            return runtime.call("index_source", {"source_id": args.source, "reindex": args.command == "reindex" or args.reindex})
        if args.command in ("query", "context"):
            values = {"project": args.project, "query": args.query, "limit": args.limit}
            if args.source_id is not None:
                values["source_ids"] = args.source_id
            values["offset" if args.command == "query" else "budget"] = args.offset if args.command == "query" else args.budget
            return runtime.call("search_knowledge" if args.command == "query" else "get_project_context", values)
        if args.command == "index-status":
            if args.project:
                return runtime.call("get_index_status", {"project": args.project})
            return {"projects": {project: runtime.call("get_index_status", {"project": project}) for project in config.projects}}
        command = args.memory_command
        if command == "stats":
            projects = [args.project] if args.project else config.projects
            for project in projects:
                config.authorize(project)
            return {"projects": {project: runtime.service.memory.stats(project, principal=config.principal) for project in projects}}
        if command == "save":
            values = {"project": args.project, "category": args.category, "confidence": args.confidence,
                      "verification": args.verification, "visibility": args.visibility,
                      "tags": args.tag, "references": args.reference}
            for field in ("fact_key", "supersedes"):
                if getattr(args, field) is not None:
                    values[field] = getattr(args, field)
            content = _read_content(args)
            # Operator file/stdin is the only large-content path; MCP remains bounded.
            config.authorize(args.project, write=True)
            if args.verification == "verified" and not config.can_verify:
                raise PermissionError("verification unavailable")
            validate(dict(values, content="validation"), TOOL_MAP["save_memory"]["inputSchema"])
            return runtime.service.memory.save(**values, content=content, author=config.principal)
        if command == "recall":
            values = {"project": args.project, "query": args.query, "limit": args.limit,
                      "offset": args.offset, "historical": args.historical}
            for field, value in (("category", args.category), ("tags", args.tag), ("verification", args.verification)):
                if value is not None:
                    values[field] = value
        elif command == "update":
            patch = strict_json(_read_file(args.patch)) if args.patch else {}
            if not isinstance(patch, dict):
                raise ValueError("patch must be object")
            content = _read_content(args)
            if content is not None:
                if "content" in patch:
                    raise ValueError("duplicate content")
                patch["content"] = content
            for field in ("expected_revision", "verification"):
                if getattr(args, field) is not None:
                    if field in patch:
                        raise ValueError("duplicate patch field")
                    patch[field] = getattr(args, field)
            if not patch:
                raise ValueError("empty patch")
            config.authorize(args.project, write=True)
            if patch.get("verification") == "verified" and not config.can_verify:
                raise PermissionError("verification unavailable")
            small_patch = dict(patch)
            if "content" in small_patch and isinstance(small_patch["content"], str):
                small_patch["content"] = "validation"
            validate(small_patch, obj(PATCH_FIELDS))
            return runtime.service.memory.update(args.project, args.id, patch, principal=config.principal, can_verify=config.can_verify)
        elif command == "invalidate":
            values = {"project": args.project, "id": args.id, "reason": args.reason}
        else:
            values = {"project": args.project, "id": args.id}
        return runtime.call(command + "_memory", values)
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        if args.command == "serve":
            return result
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True))
        return 0
    except PermissionError:
        print("Operation not permitted by intelligence configuration", file=sys.stderr)
    except (ValueError, TypeError, KeyError, UnicodeError):
        print("Invalid configuration, arguments, or memory data", file=sys.stderr)
    except Exception:
        print("Intelligence storage or operation unavailable", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
