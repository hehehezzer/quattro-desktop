#!/usr/bin/env python3
"""Command-line control plane for the Quattro orchestration engine.

Only display-safe normalized state is written below ~/.local/state/quattro/agents.
Authentication material is never read directly; Codex account information and
rate limits come from the structured Codex app-server protocol.
"""

from __future__ import annotations

from quattro.platform.filesystem import fsync_directory

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import pathlib
import re
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from quattro_memory import (
    MemoryError,
    initialize_project_vault,
    initialize_vault,
    link_project_vault,
    memory_policy,
    memory_settings,
    obsidian_uri,
    project_memory_path,
    project_vault_status,
    register_obsidian_vault,
    require_project_vault,
    require_vault,
    vault_status,
)
from quattro_pr_review import (
    GitHubClient,
    ReviewError,
    ReviewOptions,
    execute_review,
    parse_target,
)
from quattro_agent.errors import ConfigError, LeaseConflict, StateTransitionError
from quattro.platform.executables import find_executable
from quattro_agent.paths import (
    codex_data_root,
    config_path as configured_path,
    data_root,
    default_workspace,
    model_catalog_path,
    omniroute_dashboard_url,
    state_root as configured_state_root,
    xdg_data_home,
)
from quattro_agent.config import migrate_ai_config, validate_ai_config
from quattro_agent.models import RunState, TaskState
from quattro_agent.omniroute import validate_omniroute_contract
from quattro_agent.sessions import load_session_registry, prepare_shared_session_namespace, update_session_registry
from quattro_agent.supervisor import ProcessIdentity, read_process_identity, verify_process_identity
from quattro_agent.privacy import redact_secret_text, summarize_display_title
from quattro_agent.retrieval import (
    ContextAssembler, QueryRouter, RepositoryIndexer, RetrievalStore,
    consolidate as consolidate_memory, consolidation_proposal,
    evaluate as evaluate_retrieval,
    FeatureHashEmbeddingBackend, LocalNeuralEmbeddingBackend,
    index_episodic_database, repository_state, utc_now,
    verified_release_source_paths, safe_to_index, allowed_origins_for_route,
    DENIED_NAMES, DENIED_PARTS, MAX_FILE_BYTES, SECRET_PATTERNS,
)
from quattro_agent.benchmark import load_cases as load_benchmark_cases, run_benchmark
from quattro_agent.mandatory_context import (
    build_mandatory_context,
    project_root_from_config,
    resolve_project_destination,
)
from quattro_harness import HarnessRuntime
from quattro_deployment import (
    build_manifest, load_manifest, resolve_git_revision,
    verify_manifest_files, write_manifest_atomic,
)
from quattro_release import create_release, create_source_release, load_release, restore_release


HOME = pathlib.Path.home()
CONFIG_PATH = configured_path()
STATE_ROOT = configured_state_root()
DEFAULT_WORKSPACE = default_workspace()
LEGACY_DEPLOYMENT_MANIFEST = STATE_ROOT / "deployment" / "manifest.json"
CORE_DEPLOYMENT_MANIFEST = STATE_ROOT / "deployment" / "core-manifest.json"
DESKTOP_DEPLOYMENT_MANIFEST = STATE_ROOT / "deployment" / "desktop-manifest.json"
# Backward-compatible name now points at the independently operable Core unit.
DEPLOYMENT_MANIFEST = CORE_DEPLOYMENT_MANIFEST
RELEASE_ROOT = codex_data_root() / "releases"
SHARED_CODEX_SESSIONS = STATE_ROOT / "private/codex-sessions"
CODEX_SESSION_REGISTRY = STATE_ROOT / "private/codex-session-registry.json"
BASELINE_REVISION = "ef72904701a2920c1dd103e2a9add7b7b12fb7cf"
BASELINE_RELEASE_ID = BASELINE_REVISION
VERSION = "0.1.0"

from quattro.deployment.migration import migrate_legacy_manifest
from quattro.deployment.profiles import (
    CORE_DEPLOYMENT_MAPPINGS, DESKTOP_DEPLOYMENT_MAPPINGS, DESKTOP_RETIRED_PATHS,
    DEPLOYMENT_MAPPINGS,
)

# Child workers must enter through the executable wrapper so Python resolves
# the package from its parent directory.  Executing cli.py directly leaves
# ``quattro_agent`` unavailable on sys.path in an installed deployment.
SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "quattro-agent"
SCHEMA_VERSION = 1
MAX_SESSION_META_BYTES = 1_048_576
HARNESS: HarnessRuntime | None = None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def deployment_profile(profile: str) -> tuple[Mapping[str, tuple[str, str]], pathlib.Path, pathlib.Path]:
    if profile == "core":
        return CORE_DEPLOYMENT_MAPPINGS, CORE_DEPLOYMENT_MANIFEST, RELEASE_ROOT / "core"
    if profile == "desktop":
        return DESKTOP_DEPLOYMENT_MAPPINGS, DESKTOP_DEPLOYMENT_MANIFEST, RELEASE_ROOT / "desktop"
    raise ValueError(f"unsupported deployment profile: {profile}")


def migrate_deployment_manifest() -> dict[str, Any]:
    return migrate_legacy_manifest(
        LEGACY_DEPLOYMENT_MANIFEST,
        CORE_DEPLOYMENT_MANIFEST,
        DESKTOP_DEPLOYMENT_MANIFEST,
        core_names=set(CORE_DEPLOYMENT_MAPPINGS),
        desktop_names=set(DESKTOP_DEPLOYMENT_MAPPINGS),
    )


def deployment_paths(
    active_manifest: Mapping[str, Any] | None = None,
    mappings: Mapping[str, tuple[str, str]] = CORE_DEPLOYMENT_MAPPINGS,
) -> set[str]:
    """Return the desired inventory plus paths known to the active release."""
    paths = {str(deployed) for _source, deployed in mappings.values()}
    if active_manifest is not None:
        paths.update(str(record["deployedPath"]) for record in active_manifest["files"])
    return paths


def source_tree_is_clean(root: pathlib.Path) -> None:
    """Require a committed source snapshot before it can reach the runtime."""
    git = shutil.which("git")
    if not git:
        die("Git is unavailable; refusing source deployment")
    try:
        result = subprocess.run(
            [git, "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5, env={"PATH": os.defpath, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        die(f"Unable to verify source cleanliness: {error}")
    if result.returncode != 0:
        die("Unable to verify source cleanliness")
    if result.stdout.strip():
        die("Refusing deployment from a dirty source tree")


def eprint(message: str) -> None:
    print(f"quattro-agent: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> "NoReturn":
    eprint(message)
    raise SystemExit(code)


def command_path(name: str) -> str | None:
    return find_executable(name)


def ensure_state_dirs() -> None:
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_ROOT, 0o700)
    for name in ("usage", "recent", "runtime", "snapshots", "crashes", "dictation"):
        path = STATE_ROOT / name
        path.mkdir(mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)


def atomic_json(path: pathlib.Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_json(path: pathlib.Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback


def expand_path(value: str) -> pathlib.Path:
    return pathlib.Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def load_config() -> dict[str, Any]:
    try:
        return harness().config()
    except (ConfigError, OSError, ValueError) as error:
        die(f"Invalid AI configuration: {error}")


def starter_config() -> dict[str, Any]:
    """Return a credential-free configuration suitable for a new checkout."""
    account_root = codex_data_root() / "accounts"
    def portable(path: pathlib.Path) -> str:
        try:
            return "~/" + str(path.relative_to(HOME))
        except ValueError:
            return str(path)

    return {
        "schemaVersion": 3,
        "defaultAgent": "codex",
        "defaultCodexAccount": "default",
        "defaultPolicyProfile": "workspace-write",
        "fullAccessRequiresConfirmation": True,
        "accounts": [{
            "id": "default",
            "alias": "Default Codex account",
            "codexHome": portable(account_root / "default"),
            "enabled": True,
        }],
        "usageRefresh": {"enabled": False, "intervalMinutes": 15},
        "crossDeviceSync": {"enabled": False, "directory": None},
        "crashCapture": {"enabled": True, "automaticDiagnosis": False},
        "dictation": {
            "engine": "whisper.cpp",
            "modelPath": portable(xdg_data_home() / "whisper/model.bin"),
            "maxRecordingSeconds": 60,
            "retainAudio": False,
        },
        "memory": {
            "enabled": False,
            "vaultPath": portable(data_root() / "memory/shared"),
            "projectVaultPath": portable(data_root() / "memory/projects"),
            "enforceOnLaunch": False,
        },
        "prReview": {
            "runtime": "codex", "codexAccount": "default", "githubAccount": None,
            "defaultRepository": None, "reviewMode": "comment",
            "automaticPublication": False, "maximumDepth": "full", "runTests": True,
            "securityScanning": True, "commentBehavior": "summary",
            "severityThreshold": "LOW", "model": None, "timeoutSeconds": 1800,
            "maxFiles": 500, "maxDiffBytes": 5_000_000,
        },
        "delegation": {"enabled": True, "maxWorkers": 3},
        "cooperation": {"globalLimit": 5, "perRepositoryLimit": 3},
        "routing": {
            "fastReasoningEffort": "low", "standardReasoningEffort": "medium",
            "reasoningReasoningEffort": "high", "exceptionalReasoningEffort": "ultra",
            "maxAutomaticEscalations": 2, "maxExceptionalEscalations": 1,
            "fastAutoRoute": "auto/coding:cheap", "standardAutoRoute": "auto/coding",
            "reasoningAutoRoute": "auto/reasoning", "fastContextBudgetTokens": 1200,
            "standardContextBudgetTokens": 2500, "reasoningContextBudgetTokens": 4000,
        },
    }


def initialize_config(force: bool = False) -> int:
    """Create a private local config without reading provider credentials."""
    if CONFIG_PATH.is_symlink():
        die(f"configuration must not be a symlink: {CONFIG_PATH}")
    if CONFIG_PATH.exists() and not force:
        die(f"configuration already exists: {CONFIG_PATH} (use --force to replace it)")
    normalized = validate_ai_config(starter_config())
    atomic_json(CONFIG_PATH, normalized, mode=0o600)
    print(json.dumps({
        "schemaVersion": normalized["schemaVersion"],
        "path": str(CONFIG_PATH),
        "memoryEnabled": normalized["memory"]["enabled"],
        "message": "Credential-free starter configuration created; configure Codex separately.",
    }, ensure_ascii=False))
    return 0


def harness() -> HarnessRuntime:
    global HARNESS
    if HARNESS is None:
        HARNESS = HarnessRuntime(
            config_path=CONFIG_PATH,
            state_root=STATE_ROOT,
            script_path=SCRIPT_PATH,
            default_workspace=DEFAULT_WORKSPACE,
            command_resolver=command_path,
        )
    return HARNESS


def account_record(config: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
    selected = account_id or str(config.get("defaultCodexAccount", "account-1"))
    for record in config["accounts"]:
        if isinstance(record, dict) and record.get("id") == selected:
            return record
    die(f"Unknown Codex account: {selected}")


def codex_home(config: dict[str, Any], account_id: str | None = None) -> pathlib.Path:
    record = account_record(config, account_id)
    value = record.get("codexHome")
    if not isinstance(value, str) or not value:
        die(f"Codex home is not configured for {record.get('id', 'account')}")
    return expand_path(value)


def prepare_codex_launch(config: dict[str, Any], account_id: str | None = None) -> pathlib.Path:
    """Validate routing and attach the account to Quattro's shared sessions."""
    home = codex_home(config, account_id)
    validate_omniroute_contract(home)
    prepare_shared_session_namespace(
        config["accounts"], SHARED_CODEX_SESSIONS, CODEX_SESSION_REGISTRY
    )
    return home


def codex_full_access(config: dict[str, Any]) -> bool:
    """Return whether this concrete task configuration selects explicit full access."""
    return config.get("defaultPolicyProfile") == "full-access-explicit"


def codex_permission_args(config: dict[str, Any]) -> list[str]:
    if codex_full_access(config):
        return ["--dangerously-bypass-approvals-and-sandbox"]
    return ["-a", "on-request"]


def safe_directory(value: str | None) -> pathlib.Path:
    if value:
        path = expand_path(value)
    else:
        path = pathlib.Path.cwd().resolve()
        if path in (HOME, pathlib.Path("/")):
            path = DEFAULT_WORKSPACE
    if not path.is_dir():
        die(f"Directory does not exist: {path}")
    return path


def require(name: str) -> str:
    path = command_path(name)
    if not path:
        die(f"{name} is not available in PATH")
    return path


_CHILD_ENVIRONMENT = (
    "HOME", "PATH", "LANG", "LC_ALL", "TERM", "COLORTERM", "TMPDIR",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
    "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
    "QUATTRO_CONFIG", "QUATTRO_STATE_DIR", "QUATTRO_DATA_DIR",
    "QUATTRO_CODEX_DATA_DIR", "QUATTRO_CODEX_HOME_ROOT", "QUATTRO_MODEL_CATALOG",
    "QUATTRO_OMNIROUTE_BASE_URL", "QUATTRO_WORKSPACE", "NO_COLOR",
)


def tool_environment(name: str) -> dict[str, str]:
    """Return a desktop-safe environment without inheriting arbitrary secrets."""
    env = {
        key: value for key in _CHILD_ENVIRONMENT
        if (value := os.environ.get(key)) is not None
    }
    env.setdefault("HOME", str(HOME))
    env.setdefault("PATH", os.defpath)
    binary = command_path(name)
    if binary:
        bin_directory = str(pathlib.Path(binary).parent)
        current = env.get("PATH", "")
        entries = current.split(os.pathsep) if current else []
        if bin_directory not in entries:
            env["PATH"] = bin_directory + (os.pathsep + current if current else "")
    return env


def notify(summary: str, body: str, urgency: str = "normal") -> None:
    binary = command_path("notify-send")
    if binary:
        subprocess.run(
            [binary, "--app-name=Quattro AI", f"--urgency={urgency}", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )


def detached(argv: list[str], cwd: pathlib.Path | None = None) -> None:
    subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def runtime_path(session_id: str) -> pathlib.Path:
    return STATE_ROOT / "runtime" / f"{session_id}.json"


def write_runtime(session_id: str, agent: str, directory: pathlib.Path,
                  account_id: str | None, mode: str) -> pathlib.Path:
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "pid": os.getpid(),
        "agent": agent,
        "projectPath": str(directory),
        "projectName": directory.name or str(directory),
        "accountId": account_id,
        "mode": mode,
        "startedAt": now_iso(),
        "state": "running",
    }
    path = runtime_path(session_id)
    atomic_json(path, record)
    return path


def update_recent(directory: pathlib.Path, agent: str, session_id: str | None = None,
                  resumable: bool = False, last_activity: str | None = None) -> None:
    ensure_state_dirs()
    target = STATE_ROOT / "recent" / "projects.json"
    current = read_json(target, {"schemaVersion": SCHEMA_VERSION, "projects": []})
    projects = current.get("projects", []) if isinstance(current, dict) else []
    projects = [p for p in projects if isinstance(p, dict) and p.get("path") != str(directory)]
    projects.insert(0, {
        "path": str(directory),
        "name": directory.name or str(directory),
        "agent": agent,
        "lastActivity": last_activity or now_iso(),
        "sessionId": session_id,
        "resumable": bool(resumable),
        "exists": directory.is_dir(),
    })
    atomic_json(target, {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now_iso(),
        "projects": projects[:20],
    })


def codex_thread_titles(
    config: dict[str, Any], account_id: str, timeout_seconds: float = 8.0
) -> dict[str, str]:
    """Read Codex's own user-facing thread names through structured app-server RPC."""
    binary = command_path("codex")
    if not binary:
        return {}
    try:
        env = tool_environment("codex")
        env["CODEX_HOME"] = str(codex_home(config, account_id))
        process = subprocess.Popen(
            [binary, "app-server", "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=env,
            start_new_session=True,
        )
    except OSError:
        return {}
    assert process.stdin is not None and process.stdout is not None
    requests = (
        {
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "quattro-session-titles", "version": "1"}},
        },
        {"method": "initialized", "params": {}},
        {
            "id": 2,
            "method": "thread/list",
            "params": {
                "limit": 50,
                "sortKey": "updated_at",
                "useStateDbOnly": True,
            },
        },
    )
    result: dict[str, str] = {}
    deadline = time.monotonic() + timeout_seconds
    try:
        for request in requests:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                [process.stdout], [], [], min(0.5, max(0.0, deadline - time.monotonic()))
            )
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline(4_000_001)
            if not line or len(line.encode("utf-8", errors="replace")) > 4_000_000:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != 2:
                continue
            payload = message.get("result")
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                thread_id = row.get("id")
                source_title = row.get("name") or row.get("preview")
                if not isinstance(thread_id, str) or not thread_id:
                    continue
                if not isinstance(source_title, str) or not source_title.strip():
                    continue
                result[thread_id] = summarize_display_title(
                    source_title, fallback="Codex session"
                )
            break
    except (BrokenPipeError, OSError, ValueError):
        result = {}
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        try:
            process.stdout.close()
        except OSError:
            pass
    return result


def scan_codex_sessions(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Read display-safe metadata for every configured native Codex session.

    The session identity/path comes only from the leading ``session_meta``
    record. Codex's own user-facing name is read through ``thread/list``;
    prompt and response records are never parsed or copied into Quattro state.
    """
    rows: dict[str, dict[str, Any]] = {}
    registry = load_session_registry(CODEX_SESSION_REGISTRY)
    aliases = {
        row.get("id"): row.get("alias", row.get("id"))
        for row in config["accounts"] if isinstance(row, dict)
    }
    for account in config["accounts"]:
        if not isinstance(account, dict) or not account.get("enabled", True):
            continue
        account_id = account.get("id")
        home_value = account.get("codexHome")
        if not isinstance(account_id, str) or not isinstance(home_value, str):
            continue
        titles = codex_thread_titles(config, account_id)
        session_root = expand_path(home_value) / "sessions"
        for filename in glob.iglob(str(session_root / "**" / "*.jsonl"), recursive=True):
            try:
                candidate = pathlib.Path(filename)
                if candidate.is_symlink():
                    continue
                candidate.resolve().relative_to(session_root.resolve())
                with open(filename, "r", encoding="utf-8") as stream:
                    leading_line = stream.readline(MAX_SESSION_META_BYTES + 1)
                if len(leading_line.encode("utf-8")) > MAX_SESSION_META_BYTES:
                    continue
                first = json.loads(leading_line)
                payload = first.get("payload", {})
                if first.get("type") != "session_meta" or not isinstance(payload, dict):
                    continue
                # ``id`` is the concrete rollout/thread UUID. Forked sessions
                # may retain their parent's ``session_id``, so preferring that
                # legacy field collapses distinct resumable conversations.
                session_id = payload.get("id") or payload.get("session_id")
                cwd = payload.get("cwd")
                created_at = payload.get("timestamp")
                if not isinstance(session_id, str) or not session_id:
                    continue
                if not isinstance(cwd, str) or not cwd.startswith("/"):
                    continue
                if not isinstance(created_at, str):
                    created_at = None
                path = pathlib.Path(cwd)
                exists = path.is_dir()
                ephemeral_review = cwd.startswith(
                    str(pathlib.Path(tempfile.gettempdir()) / "quattro-pr-review-")
                )
                modified = dt.datetime.fromtimestamp(
                    os.path.getmtime(filename), dt.timezone.utc
                ).isoformat(timespec="seconds")
                registered = registry.get(session_id, {})
                origin = registered.get("originatingAccount")
                if not isinstance(origin, str):
                    origin = account_id
                last_account = registered.get("mostRecentlyUsedAccount")
                if not isinstance(last_account, str):
                    last_account = origin
                row = {
                    "sessionId": session_id,
                    "accountId": origin,
                    "originatingAccount": origin,
                    "mostRecentlyUsedAccount": last_account,
                    "providerId": "omniroute",
                    "accountAlias": aliases.get(origin, origin),
                    "path": cwd,
                    "name": path.name or cwd,
                    "title": titles.get(session_id) or registered.get("displayTitle"),
                    "createdAt": created_at,
                    "lastActivity": modified,
                    "exists": exists,
                    "resumable": bool(exists and not ephemeral_review),
                }
                previous = rows.get(session_id)
                if (
                    previous is None
                    or row["lastActivity"] > previous["lastActivity"]
                    or (row.get("title") and not previous.get("title"))
                ):
                    rows[session_id] = row
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
    ordered = sorted(rows.values(), key=lambda row: str(row["lastActivity"]), reverse=True)
    for row in ordered:
        title = row.get("title")
        current = registry.get(row["sessionId"], {})
        if not isinstance(title, str) or not title:
            continue
        if (
            current.get("displayTitle") == title
            and current.get("projectPath") == row["path"]
            and current.get("createdAt") == row.get("createdAt")
        ):
            continue
        update_session_registry(CODEX_SESSION_REGISTRY, row["sessionId"], {
            "displayTitle": title,
            "projectPath": row["path"],
            "createdAt": row.get("createdAt"),
            "updatedAt": now_iso(),
        })
    return ordered


def resolve_codex_resume_target(
    config: dict[str, Any],
    directory: pathlib.Path,
    session_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any] | None:
    """Resolve one exact native session across every configured Codex home."""
    expected_path = str(directory.resolve())
    for row in scan_codex_sessions(config):
        if not row["resumable"]:
            continue
        if str(pathlib.Path(row["path"]).resolve()) != expected_path:
            continue
        if session_id is not None and row["sessionId"] != session_id:
            continue
        return row
    return None


def session_worker(args: argparse.Namespace) -> int:
    ensure_state_dirs()
    config = load_config()
    directory = safe_directory(args.directory)
    memory_enabled, memory_vault, memory_enforced = memory_settings(config)
    project_vault = project_memory_path(config)
    if memory_enabled and memory_enforced:
        try:
            require_vault(memory_vault)
            require_project_vault(project_vault)
        except MemoryError as error:
            die(str(error))
    policy = memory_policy(memory_vault, project_vault) if memory_enabled else ""
    mandatory = build_mandatory_context(
        config, request=args.prompt, cwd=directory,
    )
    policy = policy + "\n\n" + mandatory.text
    account_id = args.account if args.agent == "codex" else None
    path = write_runtime(args.session_id, args.agent, directory, account_id, args.mode)
    update_recent(directory, args.agent, args.session_id, args.agent == "codex")
    try:
        if args.agent == "codex":
            binary = require("codex")
            env = tool_environment("codex")
            env["CODEX_HOME"] = str(prepare_codex_launch(config, account_id))
            memory_args = [
                "-c", f"developer_instructions={json.dumps(policy)}",
                "--add-dir", str(memory_vault),
                "--add-dir", str(project_vault),
            ] if memory_enabled else []
            if args.mode == "resume":
                resume_target = [args.native_session_ref] if getattr(args, "native_session_ref", None) else ["--all"]
                command = [binary, *memory_args, *codex_permission_args(config), "resume", *resume_target, "-C", str(directory)]
            elif args.mode == "prompt":
                command = [binary, *memory_args, *codex_permission_args(config), "exec", "-C", str(directory), "--skip-git-repo-check", "-"]
            else:
                command = [binary, *memory_args, *codex_permission_args(config), "-C", str(directory)]
                if args.prompt:
                    command.append(args.prompt)
        else:
            binary = require("pi")
            memory_args = ["--append-system-prompt", policy] if memory_enabled else []
            if args.mode == "prompt":
                command = [binary, *memory_args, "-p", "--", args.prompt]
            elif args.mode == "resume":
                command = [binary, *memory_args, "-r"]
            else:
                command = [binary, *memory_args]
                if args.prompt:
                    command.extend(["--", args.prompt])
            env = tool_environment("pi")

        if args.mode == "prompt" and args.agent == "codex":
            completed = subprocess.run(
                command, cwd=directory, env=env, input=args.prompt + "\n", text=True,
                check=False,
            )
        else:
            completed = subprocess.run(command, cwd=directory, env=env, check=False)
        if args.mode == "prompt":
            notify(
                f"{args.agent.title()} task finished",
                f"{directory.name}: exit {completed.returncode}",
                "normal" if completed.returncode == 0 else "critical",
            )
        return completed.returncode
    finally:
        if args.agent == "codex":
            for row in scan_codex_sessions(config):
                if row["path"] == str(directory):
                    update_session_registry(CODEX_SESSION_REGISTRY, row["sessionId"], {
                        "originatingAccount": row.get("originatingAccount") or account_id,
                        "mostRecentlyUsedAccount": account_id,
                        "providerId": "omniroute",
                        "projectPath": str(directory),
                        "updatedAt": now_iso(),
                    })
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def launch_terminal(agent: str, directory_value: str | None, mode: str = "interactive",
                    prompt: str = "", account_id: str | None = None,
                    native_session_ref: str | None = None,
                    profile_name: str | None = None,
                    confirm_full_access: bool = False,
                    write_scopes: Sequence[str] = ()) -> str:
    """Create a durable interactive task and open its worker in Foot."""
    directory = safe_directory(directory_value)
    task_id, _ = harness().submit(
        agent=agent,
        project=directory,
        prompt=prompt,
        mode=mode,
        profile_name=profile_name,
        account_id=account_id,
        native_session_ref=native_session_ref,
        confirm_full_access=confirm_full_access,
        terminal=True,
        write_scopes=write_scopes,
    )
    return task_id


def run_prompt(agent: str, prompt: str, directory_value: str | None,
               profile_name: str | None = None,
               confirm_full_access: bool = False,
               write_scopes: Sequence[str] = ()) -> int:
    if not prompt:
        die("A prompt is required")
    directory = safe_directory(directory_value)
    from quattro_agent.delegation import classify_task_request
    decision = classify_task_request(prompt, preferred_agent=agent)
    if decision.decision == "DIRECT":
        try:
            result = harness().direct_response(
                project=directory, prompt=prompt, profile_name=profile_name,
            )
        except (RuntimeError, ValueError) as error:
            print(json.dumps({
                "schemaVersion": 1, "decision": "DIRECT", "status": "failed",
                "error": str(error), "retry": "not_attempted",
                "nextAction": "Check OmniRoute health, route availability, and retry the request.",
            }, ensure_ascii=False), file=sys.stderr)
            return 1
        print(result["response"])
        return 0
    _task_id, result = harness().submit(
        agent=agent,
        project=directory,
        prompt=prompt,
        mode="prompt",
        profile_name=profile_name,
        confirm_full_access=confirm_full_access,
        write_scopes=write_scopes,
    )
    return int(result or 0)


def jsonrpc_snapshot(account_id: str, timeout_seconds: int = 18) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_config()
    binary = require("codex")
    env = tool_environment("codex")
    env["CODEX_HOME"] = str(prepare_codex_launch(config, account_id))
    process = subprocess.Popen(
        [binary, "-a", "on-request", "app-server", "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, bufsize=1,
    )
    requests = [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {
            "name": "quattro-agent", "version": "1"
        }}},
        {"method": "initialized", "params": {}},
        {"id": 2, "method": "account/read", "params": {"refreshToken": False}},
        {"id": 3, "method": "account/rateLimits/read", "params": {}},
    ]
    assert process.stdin is not None and process.stdout is not None
    for request in requests:
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    process.stdin.flush()
    responses: dict[int, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline and (2 not in responses or 3 not in responses):
            ready, _, _ = select.select([process.stdout], [], [], min(1, deadline - time.monotonic()))
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            if isinstance(request_id, int):
                responses[request_id] = message
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    for request_id in (2, 3):
        response = responses.get(request_id)
        if not response:
            raise RuntimeError(f"Codex app-server timed out waiting for response {request_id}")
        if "error" in response:
            error = response["error"]
            raise RuntimeError(str(error.get("message", "Codex app-server error"))[:240])
    return responses[2]["result"], responses[3]["result"]


def normalize_window(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    used = value.get("usedPercent")
    if not isinstance(used, (int, float)):
        return None
    duration = value.get("windowDurationMins") if isinstance(value.get("windowDurationMins"), int) else None
    if duration == 300:
        label = "5h"
    elif duration == 10080:
        label = "W"
    elif duration and duration % 1440 == 0:
        label = f"{duration // 1440}d"
    elif duration and duration % 60 == 0:
        label = f"{duration // 60}h"
    else:
        label = "Usage"
    return {
        "usedPercent": max(0, min(100, round(float(used), 1))),
        "resetAt": value.get("resetsAt") if isinstance(value.get("resetsAt"), int) else None,
        "windowMinutes": duration,
        "label": label,
    }


def normalized_account_login(account: Any, native_authenticated: bool) -> tuple[bool, str | None]:
    """Keep native login state when a custom model provider hides account/read."""
    if isinstance(account, dict):
        login_type = account.get("type")
        return True, login_type if isinstance(login_type, str) else None
    return bool(native_authenticated), None


def refresh_usage(account_id: str | None = None, retries: int = 2) -> int:
    ensure_state_dirs()
    config = load_config()
    record = account_record(config, account_id)
    selected = str(record["id"])
    good_path = STATE_ROOT / "usage" / f"{selected}.json"
    refresh_path = STATE_ROOT / "usage" / f"{selected}.refresh.json"
    last_error = "Unknown refresh error"
    for attempt in range(retries):
        try:
            account_result, limits_result = jsonrpc_snapshot(selected)
            account = account_result.get("account")
            native_authenticated = False
            if not isinstance(account, dict):
                native_authenticated = bool(account_login_state(record).get("authenticated"))
            logged_in, login_type = normalized_account_login(account, native_authenticated)
            snapshot = limits_result.get("rateLimits")
            if not isinstance(snapshot, dict):
                snapshot = {}
            normalized = {
                "schemaVersion": SCHEMA_VERSION,
                "accountId": selected,
                "alias": record.get("alias", selected),
                "loggedIn": logged_in,
                "loginType": login_type,
                "plan": (account.get("planType") if isinstance(account, dict) else None) or snapshot.get("planType"),
                "primary": normalize_window(snapshot.get("primary")),
                "secondary": normalize_window(snapshot.get("secondary")),
                "lastSuccessfulRefresh": now_iso(),
                "stale": False,
                "error": None,
            }
            atomic_json(good_path, normalized)
            atomic_json(refresh_path, {
                "schemaVersion": SCHEMA_VERSION, "accountId": selected,
                "attemptedAt": now_iso(), "ok": True, "error": None,
            })
            return 0
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            last_error = str(error)[:240]
            if attempt + 1 < retries:
                time.sleep(1)
    atomic_json(refresh_path, {
        "schemaVersion": SCHEMA_VERSION, "accountId": selected,
        "attemptedAt": now_iso(), "ok": False, "error": last_error,
    })
    eprint(f"usage refresh failed for {selected}: {last_error}")
    return 1


def refresh_all_usage() -> int:
    config = load_config()
    account_ids = [
        str(record["id"])
        for record in config["accounts"]
        if isinstance(record, dict)
        and record.get("enabled", True)
        and isinstance(record.get("id"), str)
        and record["id"]
    ]
    if not account_ids:
        eprint("No enabled Codex accounts are configured")
        return 1
    result = 0
    for account_id in account_ids:
        if refresh_usage(account_id) != 0:
            result = 1
    return result


def usage_is_overdue(config: dict[str, Any], refreshed_at: Any,
                     current_time: dt.datetime | None = None) -> bool:
    settings = config.get("usageRefresh")
    if isinstance(settings, dict) and settings.get("enabled") is False:
        return False
    interval = settings.get("intervalMinutes", 15) if isinstance(settings, dict) else 15
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
        interval = 15
    if not isinstance(refreshed_at, str) or not refreshed_at:
        return True
    try:
        refreshed = dt.datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return True
    now = current_time or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    tolerance = dt.timedelta(minutes=float(interval) * 2 + 5)
    return now.astimezone(dt.timezone.utc) - refreshed.astimezone(dt.timezone.utc) > tolerance


def usage_status(account_id: str | None = None) -> dict[str, Any]:
    config = load_config()
    record = account_record(config, account_id)
    selected = str(record["id"])
    good = read_json(STATE_ROOT / "usage" / f"{selected}.json", {})
    refresh = read_json(STATE_ROOT / "usage" / f"{selected}.refresh.json", {})
    if not isinstance(good, dict) or not good:
        good = {
            "schemaVersion": SCHEMA_VERSION, "accountId": selected,
            "alias": record.get("alias", selected), "loggedIn": False,
            "loginType": None, "plan": None, "primary": None, "secondary": None,
            "lastSuccessfulRefresh": None,
        }
    refresh_failed = isinstance(refresh, dict) and refresh.get("ok") is False
    overdue = usage_is_overdue(config, good.get("lastSuccessfulRefresh"))
    if refresh_failed:
        good = {**good, "stale": True, "error": refresh.get("error"),
                "lastAttempt": refresh.get("attemptedAt")}
    else:
        good = {**good, "stale": overdue, "error": None,
                "lastAttempt": refresh.get("attemptedAt") if isinstance(refresh, dict) else None}
    return good


def refresh_recent() -> int:
    ensure_state_dirs()
    config = load_config()
    combined: dict[str, dict[str, Any]] = {}
    existing = read_json(STATE_ROOT / "recent" / "projects.json", {})
    if isinstance(existing, dict):
        for row in existing.get("projects", []):
            if (isinstance(row, dict) and isinstance(row.get("path"), str)
                    and row.get("agent") != "codex"):
                combined[row["path"]] = row
    sessions = scan_codex_sessions(config)
    atomic_json(STATE_ROOT / "recent" / "sessions.json", {
        "schemaVersion": SCHEMA_VERSION, "generatedAt": now_iso(), "sessions": sessions,
    })
    for row in sessions:
        cwd = row["path"]
        previous = combined.get(cwd)
        if previous and str(previous.get("lastActivity", "")) >= row["lastActivity"]:
            continue
        combined[cwd] = {
            "path": cwd, "name": row["name"], "agent": "codex",
            "accountId": row["accountId"], "accountAlias": row["accountAlias"],
            "lastActivity": row["lastActivity"], "sessionId": row["sessionId"],
            "resumable": row["resumable"], "exists": row["exists"],
        }
    rows = sorted(combined.values(), key=lambda row: str(row.get("lastActivity", "")), reverse=True)[:20]
    atomic_json(STATE_ROOT / "recent" / "projects.json", {
        "schemaVersion": SCHEMA_VERSION, "generatedAt": now_iso(), "projects": rows,
    })
    return 0


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def sessions_status(clean: bool = True) -> list[dict[str, Any]]:
    ensure_state_dirs()
    rows: list[dict[str, Any]] = []
    for path in (STATE_ROOT / "runtime").glob("*.json"):
        record = read_json(path, {})
        if not isinstance(record, dict):
            if clean:
                path.unlink(missing_ok=True)
            continue
        if pid_alive(record.get("pid")):
            record["state"] = "running"
            rows.append(record)
        elif clean:
            path.unlink(missing_ok=True)
        else:
            record["state"] = "stale"
            rows.append(record)

    # The durable harness superseded runtime/*.json for new tasks. Project its
    # verified live runs into the same display-safe session contract so CLI and
    # Quickshell never report an empty session list while Codex or Pi is active.
    for task_state in (TaskState.RUNNING, TaskState.CANCELLING):
        for task in harness().store.list_display_tasks(limit=1_000, state=task_state):
            task_id = str(task["taskId"])
            run = harness().store.latest_run(task_id)
            if not run or run.get("state") not in {
                RunState.RUNNING.value, RunState.CANCELLING.value,
            }:
                continue
            try:
                identity = ProcessIdentity(
                    pid=int(run["pid"]),
                    start_ticks=int(run["process_start_ticks"]),
                    process_group=int(run["process_group"]),
                    expected_executable=str(run["expected_executable"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if not verify_process_identity(identity):
                continue
            logical = harness().store.logical_session_for_task(task_id)
            logical_title = task["title"]
            coordination_id = None
            if logical:
                logical_title = harness().logical_session_projection(logical)["title"]
                coordination = harness().coordinator.find_by_logical_session(
                    str(logical["quattro_session_id"])
                )
                if coordination:
                    coordination_id = coordination.get("sessionId")
            rows.append({
                "schemaVersion": SCHEMA_VERSION,
                "sessionId": task_id,
                "taskId": task_id,
                "quattroSessionId": logical.get("quattro_session_id") if logical else None,
                "coordinationSessionId": coordination_id,
                "pid": identity.pid,
                "agent": task["agent"],
                "projectPath": task["projectPath"],
                "projectName": task["projectName"],
                "title": logical_title,
                "accountId": run.get("account_id"),
                "mode": task.get("workflow", "task"),
                "startedAt": run.get("started_at") or task.get("createdAt"),
                "heartbeatAt": run.get("heartbeat_at"),
                "state": task_state.value,
                "stoppable": True,
            })
    return sorted(rows, key=lambda row: str(row.get("startedAt", "")), reverse=True)


def stop_session(identifier: str) -> dict[str, Any]:
    """Stop one durable launcher-managed session through verified supervision."""
    target = identifier.strip()
    if not target:
        die("sessions stop requires a session or task id")
    task_id = target
    try:
        harness().store.get_task(task_id)
    except KeyError:
        try:
            task_id = str(harness().store.get_logical_session(target)["current_task_id"])
        except KeyError:
            try:
                task_id = str(harness().coordinator.get(target)["taskId"])
            except (KeyError, TypeError, ValueError):
                die(f"No launcher-managed session matched: {target}")
    running_ids = {
        str(row.get("taskId")) for row in sessions_status(clean=False)
        if row.get("taskId")
    }
    if task_id not in running_ids:
        die(f"Session is not currently running: {target}")
    harness().request_cancel(task_id)
    return {"schemaVersion": SCHEMA_VERSION, "sessionId": target, "taskId": task_id, "state": "cancelled"}


def session_terminal_pid(session: dict[str, Any], proc_root: pathlib.Path = pathlib.Path("/proc")) -> int | None:
    """Find the verified Foot process that owns one launcher-managed session."""
    task_id = str(session.get("taskId") or "")
    session_id = str(session.get("sessionId") or "")
    try:
        entries = tuple(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            executable = (entry / "exe").resolve(strict=True)
            if executable.name != "foot":
                continue
            raw = (entry / "cmdline").read_bytes()[:65_536]
        except OSError:
            continue
        argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        durable = bool(task_id and "_task-worker" in argv and task_id in argv)
        legacy = bool(
            session_id and "_session" in argv and "--session-id" in argv
            and any(
                argv[index] == "--session-id" and index + 1 < len(argv)
                and argv[index + 1] == session_id
                for index in range(len(argv))
            )
        )
        if durable or legacy:
            return int(entry.name)
    return None


def open_session(identifier: str) -> dict[str, Any]:
    """Focus the mapped Foot window for one verified live Quattro session."""
    target = identifier.strip()
    if not target:
        die("sessions open requires a session or task id")
    matches = [row for row in sessions_status(clean=False) if target in {
        str(row.get("sessionId") or ""),
        str(row.get("taskId") or ""),
        str(row.get("quattroSessionId") or ""),
        str(row.get("coordinationSessionId") or ""),
    }]
    if not matches:
        die(f"Session is not currently running: {target}")
    session = matches[0]
    terminal_pid = session_terminal_pid(session)
    if terminal_pid is None:
        die(f"No mapped terminal was found for session: {target}")
    hyprctl = require("hyprctl")
    try:
        clients_result = subprocess.run(
            [hyprctl, "clients", "-j"], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=3,
        )
        clients = json.loads(clients_result.stdout) if clients_result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        clients = []
    client = next((row for row in clients if (
        isinstance(row, dict)
        and row.get("class") == "quattro-ai"
        and row.get("mapped") is not False
        and int(row.get("pid") or 0) == terminal_pid
    )), None)
    address = str(client.get("address") or "") if client else ""
    if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
        die(f"No mapped terminal was found for session: {target}")
    focus_result = subprocess.run(
        [hyprctl, "dispatch", f'hl.dsp.focus({{ window = "address:{address}" }})'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=3,
    )
    if focus_result.returncode != 0 or focus_result.stdout.strip() != "ok":
        die("The session terminal could not be focused")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": str(session.get("sessionId") or target),
        "taskId": session.get("taskId"),
        "terminalPid": terminal_pid,
        "address": address,
        "state": "focused",
    }


def account_login_state(account: dict[str, Any]) -> dict[str, Any]:
    account_id = str(account.get("id", "unknown"))
    home_value = account.get("codexHome")
    home = expand_path(home_value) if isinstance(home_value, str) else pathlib.Path("/nonexistent")
    authenticated = False
    status = "Unavailable"
    enabled = bool(account.get("enabled", True))
    if enabled and home.is_dir() and command_path("codex"):
        env = tool_environment("codex")
        env["CODEX_HOME"] = str(home)
        try:
            result = subprocess.run(
                [require("codex"), "login", "status"], env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8, check=False,
            )
            authenticated = result.returncode == 0 and "logged in" in result.stdout.lower()
            status = "Authenticated" if authenticated else "Authentication required"
        except (OSError, subprocess.SubprocessError):
            status = "Unavailable"
    return {
        "id": account_id, "alias": account.get("alias", account_id),
        "enabled": enabled, "available": home.is_dir(),
        "authenticated": authenticated, "status": status,
    }


def dictation_status() -> dict[str, Any]:
    state = read_json(STATE_ROOT / "dictation" / "state.json", {})
    if not isinstance(state, dict) or not pid_alive(state.get("pid")):
        return {"state": "idle", "available": bool(command_path("pw-record")),
                "transcriberAvailable": find_transcriber() is not None}
    return {**state, "available": bool(command_path("pw-record")),
            "transcriberAvailable": find_transcriber() is not None}


def crash_rows(limit: int = 8) -> list[dict[str, Any]]:
    binary = command_path("coredumpctl")
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, "list", "--json=short", "--no-pager"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    decoded: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, list):
            decoded.extend(item for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            decoded.append(raw)
    for raw in decoded:
        pid = raw.get("COREDUMP_PID") or raw.get("_PID")
        if not str(pid).isdigit():
            continue
        executable = raw.get("COREDUMP_EXE") or raw.get("EXE") or raw.get("COREDUMP_COMM") or "unknown"
        rows.append({
            "pid": int(pid), "executable": pathlib.Path(str(executable)).name,
            "signal": raw.get("COREDUMP_SIGNAL_NAME") or raw.get("COREDUMP_SIGNAL") or "unknown",
            "timestamp": raw.get("__REALTIME_TIMESTAMP") or raw.get("COREDUMP_TIMESTAMP") or "",
        })
    return rows[-limit:][::-1]


def dashboard() -> dict[str, Any]:
    ensure_state_dirs()
    config = load_config()
    memory_enabled, memory_vault, _ = memory_settings(config)
    project_vault = project_memory_path(config)
    memory_state = vault_status(memory_vault) if memory_enabled else {"enabled": False, "status": "disabled"}
    if memory_enabled:
        memory_state["projectVault"] = project_vault_status(project_vault)
        if memory_state["projectVault"]["status"] != "ok":
            memory_state["status"] = "degraded"
    project_state = repository_state(DEFAULT_WORKSPACE)
    changed_files: list[str] = []
    if project_state.get("commitSha"):
        try:
            changed_files = subprocess.run(
                ["git", "-C", str(DEFAULT_WORKSPACE), "status", "--porcelain"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            changed_files = []
    project_state["changedFileCount"] = len(changed_files)
    project_state["name"] = pathlib.Path(str(project_state["repository"])).name
    project_state["zedAvailable"] = any(command_path(name) for name in ("zed", "zeditor", "zed-editor"))
    with retrieval_store() as knowledge_store:
        retrieval_state = knowledge_store.stats()
        retrieval_state["lastRetrieval"] = knowledge_store.last_trace()
    logical_sessions = harness().list_logical_sessions(recoverable_only=False)
    pending_approvals = harness().store.list_display_approvals(state="requested", limit=20)
    catalog = model_catalog_path()
    try:
        catalog_hash = hashlib.sha256(catalog.read_bytes()).hexdigest() if catalog.is_file() else None
    except OSError:
        catalog_hash = None
    manifest_revision = None
    manifest_parity = None
    if DEPLOYMENT_MANIFEST.is_file():
        try:
            manifest = load_manifest(DEPLOYMENT_MANIFEST)
            manifest_revision = manifest["gitRevision"]
            manifest_parity = verify_manifest_files(manifest, DEFAULT_WORKSPACE, HOME)["allMatch"]
        except (OSError, ValueError):
            manifest_parity = False
    return {
        "schemaVersion": SCHEMA_VERSION, "generatedAt": now_iso(),
        "defaultAgent": config["defaultAgent"],
        "activeAccount": config["defaultCodexAccount"],
        "defaultPolicyProfile": config["defaultPolicyProfile"],
        "runtime": {
            "sourceRevision": resolve_git_revision(DEFAULT_WORKSPACE),
            "manifestRevision": manifest_revision,
            "manifestParity": manifest_parity,
            "catalogSha256": catalog_hash,
            "activeAccount": config["defaultCodexAccount"],
        },
        "fullAccess": config["defaultPolicyProfile"] == "full-access-explicit",
        "accounts": [account_login_state(a) for a in config["accounts"] if isinstance(a, dict)],
        "agents": {
            "codex": {"available": bool(command_path("codex")), "version": tool_version("codex")},
            "pi": {"available": bool(command_path("pi")), "version": tool_version("pi")},
        },
        "usage": usage_status(),
        "recent": read_json(STATE_ROOT / "recent" / "projects.json", {}).get("projects", []),
        "sessions": sessions_status(clean=False),
        "cooperation": harness().coordinator.status(),
        "routing": harness().routing_summary(),
        "tasks": harness().list_tasks(50),
        "logicalSessions": logical_sessions,
        "approvals": pending_approvals,
        "project": project_state,
        "retrieval": retrieval_state,
        "dictation": dictation_status(),
        "crashes": crash_rows(),
        "memory": memory_state,
    }


def read_only_retrieval_stats() -> dict[str, Any]:
    path = STATE_ROOT / "private/retrieval.sqlite3"
    if not path.is_file() or path.is_symlink():
        return {"schemaVersion": 1, "status": "unavailable", "embeddingModel": "quattro-feature-hash-v1"}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        try:
            values = dict(connection.execute("SELECT key,value FROM retrieval_meta"))
            return {
                "schemaVersion": 1,
                "status": "ready",
                "embeddingModel": values.get("embedding_model", "quattro-feature-hash-v1"),
                "generation": int(values.get("generation", 0)),
                "documents": connection.execute("SELECT count(*) FROM documents").fetchone()[0],
                "files": connection.execute("SELECT count(*) FROM indexed_files").fetchone()[0],
                "edges": connection.execute("SELECT count(*) FROM graph_edges").fetchone()[0],
                "retrievals": connection.execute("SELECT count(*) FROM retrieval_runs").fetchone()[0],
                "databaseBytes": path.stat().st_size,
            }
        finally:
            connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {"schemaVersion": 1, "status": "unavailable", "embeddingModel": "quattro-feature-hash-v1"}


def ui_snapshot() -> dict[str, Any]:
    """Cheap display-safe snapshot; performs no schema migration or auth probe."""
    config = load_config()
    projection = read_json(STATE_ROOT / "tasks/tasks.json", {})
    if not isinstance(projection, dict):
        projection = {}
    project = repository_state(DEFAULT_WORKSPACE)
    changed = []
    if project.get("commitSha"):
        try:
            changed = subprocess.run(
                ["git", "-C", str(DEFAULT_WORKSPACE), "status", "--porcelain"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=3, check=False,
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            changed = []
    project.update({
        "name": pathlib.Path(str(project["repository"])).name,
        "changedFileCount": len(changed),
        "zedAvailable": any(command_path(name) for name in ("zed", "zeditor", "zed-editor")),
    })
    accounts = []
    for account in config["accounts"]:
        if not isinstance(account, dict):
            continue
        account_id = str(account.get("id", "unknown"))
        cached = usage_status(account_id)
        available = pathlib.Path(str(account.get("codexHome", ""))).expanduser().is_dir()
        authenticated = bool(cached.get("loggedIn"))
        accounts.append({
            "id": account_id,
            "alias": account.get("alias", account_id),
            "enabled": bool(account.get("enabled", True)),
            "available": available,
            "authenticated": authenticated,
            "status": "Authenticated" if authenticated else "Authentication required" if available else "Unavailable",
        })
    memory_enabled, memory_vault, _ = memory_settings(config)
    project_vault = project_memory_path(config)
    memory_state = {
        "enabled": memory_enabled,
        "status": "ok" if memory_enabled and (memory_vault / "INDEX.md").is_file()
                  and (project_vault / "INDEX.md").is_file() else "unavailable",
    }
    tasks = projection.get("tasks", []) if isinstance(projection.get("tasks"), list) else []
    # Only identity-verified processes belong in the Running section. The task
    # projection also contains queued/blocked lifecycle rows, which have no
    # terminal to focus and previously appeared with `PID —`.
    live_sessions = sessions_status(clean=False)
    try:
        cooperation_status = harness().coordinator.status()
    except Exception:
        # Account/usage state is independent from cooperative Git metadata.
        # A stale worktree record must not freeze the whole AI panel.
        cooperation_status = {
            "schemaVersion": 1,
            "sessions": {},
            "integrationLeases": {},
            "events": [],
            "status": "unavailable",
        }
    return {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "defaultAgent": config["defaultAgent"],
        "activeAccount": config["defaultCodexAccount"],
        "accounts": accounts,
        "agents": {
            "codex": {"available": bool(command_path("codex"))},
            "pi": {"available": bool(command_path("pi"))},
        },
        "usage": usage_status(),
        "recent": read_json(STATE_ROOT / "recent/projects.json", {}).get("projects", []),
        "sessions": live_sessions,
        "cooperation": cooperation_status,
        "tasks": tasks,
        "logicalSessions": projection.get("logicalSessions", []),
        "approvals": projection.get("approvals", []),
        "project": project,
        "retrieval": read_only_retrieval_stats(),
        "memory": memory_state,
    }


def tool_version(name: str) -> str | None:
    binary = command_path(name)
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "--version"], env=tool_environment(name), text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=5, check=False)
        return result.stdout.strip().splitlines()[-1][:120] if result.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def print_status(as_json: bool) -> None:
    data = dashboard()
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
        return
    print(f"Default agent: {data['defaultAgent']}")
    print(f"Codex account: {data['activeAccount']}")
    for agent, record in data["agents"].items():
        print(f"{agent.title()}: {record['version'] or 'NOT FOUND'}")
    active = next((a for a in data["accounts"] if a["id"] == data["activeAccount"]), None)
    print(f"Codex authentication: {active['status'] if active else 'Unavailable'}")
    print(f"Running sessions: {len(data['sessions'])}")
    print(f"Recent projects: {len(data['recent'])}")
    routing = data.get("routing", {})
    print("Routing tiers: " + ", ".join(f"{tier}={routing.get(tier, 0)}" for tier in ("FAST", "STANDARD", "REASONING")))
    cooperation = data["cooperation"]
    print(
        f"Global Quattro sessions: {cooperation['global']['active']}/"
        f"{cooperation['global']['limit']}"
    )
    for repository in cooperation["repositories"]:
        active_sessions = [
            row for row in repository["sessions"]
            if row.get("status") in {"starting", "active", "validating", "integrating"}
        ]
        recoverable = [
            row for row in repository["sessions"]
            if row.get("status") in {"stale_recoverable", "completed_recoverable"}
        ]
        if not active_sessions and not recoverable:
            continue
        print(f"\n{repository['name']}: {repository['active']}/{repository['limit']}")
        for row in active_sessions + recoverable:
            print(f"  {row['sessionId']} · {row.get('status')}")
            print(f"    task: {row.get('taskSummary') or 'not yet claimed'}")
            if row.get("branch"):
                print(f"    branch: {row['branch']}")
            print(f"    working directory: {row.get('workingDirectory') or row.get('worktreePath')}")
            print(f"    isolation: {row.get('isolationReason') or 'shared_working_tree'}")
            print(f"    write ownership: {', '.join(row.get('taskScope') or []) or 'scope not declared'}")


def doctor(as_json: bool) -> int:
    """Report Core health independently from optional integrations."""
    config = load_config()
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    check("core.python", sys.version_info >= (3, 11), sys.version.split()[0])
    codex = command_path("codex")
    pi = command_path("pi")
    check("adapter.codex", codex is not None, codex or "optional executable not found", required=False)
    check("adapter.pi", pi is not None, pi or "optional executable not found", required=False)

    memory_enabled, memory_vault, memory_enforced = memory_settings(config)
    project_vault = project_memory_path(config)
    memory_state = vault_status(memory_vault) if memory_enabled else {"status": "disabled"}
    project_memory_state = project_vault_status(project_vault) if memory_enabled else {"status": "disabled"}
    check("memory.vault", not memory_enforced or memory_state["status"] == "ok", json.dumps(memory_state, ensure_ascii=False), required=memory_enforced)
    check("memory.projects-vault", not memory_enforced or project_memory_state["status"] == "ok", json.dumps(project_memory_state, ensure_ascii=False), required=memory_enforced)

    try:
        harness().store.list_display_tasks(limit=1)
        check("core.session-store", True, str(harness().store.path))
    except Exception as error:
        check("core.session-store", False, str(error)[:240])
    try:
        validated_config = validate_ai_config(config)
        check("core.policy", validated_config.get("defaultPolicyProfile") != "full-access-explicit", str(validated_config.get("defaultPolicyProfile")))
    except (ConfigError, ValueError) as error:
        check("core.policy", False, str(error)[:240])

    migration: dict[str, Any]
    try:
        migration = migrate_deployment_manifest()
    except Exception as error:
        migration = {"status": "failed", "detail": str(error)[:240]}
        check("core.deployment-migration", False, migration["detail"])
    if CORE_DEPLOYMENT_MANIFEST.is_file():
        try:
            manifest = load_manifest(CORE_DEPLOYMENT_MANIFEST)
            parity = verify_manifest_files(manifest, DEFAULT_WORKSPACE, HOME)
            check("core.deployment", bool(parity["allMatch"]), json.dumps(parity))
        except Exception as error:
            check("core.deployment", False, str(error)[:240])
    else:
        check("core.deployment", True, "package install; source deployment manifest not required", required=False)

    desktop_installed = DESKTOP_DEPLOYMENT_MANIFEST.is_file()
    if not sys.platform.startswith("linux"):
        desktop = {"status": "UNSUPPORTED", "installed": False}
    elif not desktop_installed:
        desktop = {"status": "OPTIONAL_NOT_INSTALLED", "installed": False}
    else:
        desktop_checks = {"hyprland": command_path("hyprctl") is not None, "quickshell": command_path("qs") is not None}
        desktop = {"status": "HEALTHY" if all(desktop_checks.values()) else "INCOMPLETE", "installed": True, "checks": desktop_checks}
    check("desktop.integration", True, json.dumps(desktop, ensure_ascii=False), required=False)
    transcriber = find_transcriber()
    check("optional.dictation", transcriber is not None, "ready" if transcriber else "optional transcriber unavailable", required=False)

    required_ok = all(item["ok"] for item in checks if item["required"])
    result = {
        "schemaVersion": 2, "generatedAt": now_iso(),
        "overallStatus": "healthy" if required_ok else "degraded",
        "core": {"status": "HEALTHY" if required_ok else "DEGRADED"},
        "desktop": desktop,
        "migration": migration,
        "checks": checks,
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("===== QUATTRO DOCTOR =====")
        print(f"Quattro Core: {result['core']['status']}")
        for item in checks:
            label = "OK" if item["ok"] else ("WARN" if not item["required"] else "FAIL")
            print(f"{label:<5} {item['name']:<30} {item['detail']}")
        print(f"Desktop: {desktop['status']}")
        print(f"Overall: {result['overallStatus']}")
    return 0 if required_ok else 1


def find_transcriber() -> tuple[str, pathlib.Path] | None:
    config = load_config()
    dictation = config.get("dictation", {})
    if not isinstance(dictation, dict):
        dictation = {}
    binary = command_path("whisper-cli")
    candidates = []
    model_value = dictation.get("modelPath")
    if isinstance(model_value, str) and model_value:
        candidates.append(expand_path(model_value))
    candidates.extend([
        xdg_data_home() / "whisper/ggml-base.en.bin",
        pathlib.Path("/usr/share/whisper.cpp/models/ggml-base.en.bin"),
        pathlib.Path("/usr/share/whisper.cpp/ggml-base.en.bin"),
    ])
    if binary:
        for model in candidates:
            if model.is_file():
                return binary, model
    return None


def dictation_toggle() -> int:
    ensure_state_dirs()
    state_path = STATE_ROOT / "dictation" / "state.json"
    state = read_json(state_path, {})
    if isinstance(state, dict) and pid_alive(state.get("pid")):
        os.kill(int(state["pid"]), signal.SIGTERM)
        notify("Dictation", "Recording stopped; transcribing locally…")
        return 0
    if not command_path("pw-record"):
        notify("Dictation unavailable", "pw-record is not installed", "critical")
        return 1
    if find_transcriber() is None:
        notify("Dictation setup required", "Install whisper.cpp and configure a local ggml model", "critical")
        return 2
    session_id = uuid.uuid4().hex
    audio = pathlib.Path(tempfile.gettempdir()) / f"quattro-dictation-{os.getuid()}-{session_id}.wav"
    process = subprocess.Popen(
        [str(SCRIPT_PATH), "_dictation-record", session_id, str(audio)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    atomic_json(state_path, {
        "schemaVersion": SCHEMA_VERSION, "state": "recording", "pid": process.pid,
        "sessionId": session_id, "startedAt": now_iso(),
    })
    notify("Dictation", "Recording… press Super+Ctrl+X to stop")
    return 0


def dictation_worker(session_id: str, audio_value: str) -> int:
    ensure_state_dirs()
    audio = pathlib.Path(audio_value)
    state_path = STATE_ROOT / "dictation" / "state.json"
    stopping = False
    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop_handler)
    recorder = subprocess.Popen([require("pw-record"), "--rate", "16000", "--channels", "1", str(audio)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    started = time.monotonic()
    try:
        while not stopping and time.monotonic() - started < 60:
            if recorder.poll() is not None:
                break
            time.sleep(0.1)
        recorder.send_signal(signal.SIGINT)
        try:
            recorder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            recorder.kill()
        atomic_json(state_path, {
            "schemaVersion": SCHEMA_VERSION, "state": "transcribing", "pid": os.getpid(),
            "sessionId": session_id, "startedAt": now_iso(),
        })
        transcriber = find_transcriber()
        if transcriber is None:
            raise RuntimeError("local whisper.cpp model is unavailable")
        binary, model = transcriber
        output_base = audio.with_suffix("")
        result = subprocess.run(
            [binary, "-m", str(model), "-f", str(audio), "-otxt", "-of", str(output_base), "-nt", "-ng", "-np"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=90, check=False,
        )
        text_path = pathlib.Path(str(output_base) + ".txt")
        if result.returncode != 0 or not text_path.is_file():
            raise RuntimeError("local transcription failed")
        transcript = text_path.read_text(encoding="utf-8").strip()
        if not transcript:
            raise RuntimeError("no speech was detected")
        subprocess.run([require("wl-copy")], input=transcript, text=True, timeout=5, check=True)
        time.sleep(0.15)
        typed = subprocess.run([require("wtype"), transcript], timeout=15, check=False)
        if typed.returncode == 0:
            notify("Dictation complete", "Transcribed text was typed and copied to the clipboard")
        else:
            notify("Dictation complete", "Direct typing failed; the transcript is on the clipboard", "critical")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        notify("Dictation failed", str(error)[:200], "critical")
        return 1
    finally:
        for path in (audio, audio.with_suffix(".txt")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        current = read_json(state_path, {})
        if isinstance(current, dict) and current.get("sessionId") == session_id:
            state_path.unlink(missing_ok=True)


REDACTIONS = [
    (re.compile(r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|gh[opsu]_[A-Za-z0-9_]{12,})\b"), "[REDACTED_TOKEN]"),
]


def sanitize_text(value: str, limit: int = 16000) -> str:
    value = value[:limit]
    for pattern, replacement in REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def crash_context(pid: int) -> pathlib.Path:
    ensure_state_dirs()
    binary = require("coredumpctl")
    result = subprocess.run(
        [binary, "info", "--no-pager", str(pid)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, check=False,
    )
    if result.returncode != 0:
        die(f"No coredump found for PID {pid}")
    allowed_prefixes = (
        "PID:", "UID:", "GID:", "Signal:", "Timestamp:", "Command Line:",
        "Executable:", "Control Group:", "Unit:", "User Unit:", "Boot ID:",
        "Storage:", "Size on Disk:", "Message:", "Stack trace of thread",
    )
    lines = []
    in_stack = False
    for raw in result.stdout.splitlines():
        stripped = raw.strip()
        if any(stripped.startswith(prefix) for prefix in allowed_prefixes):
            in_stack = stripped.startswith("Stack trace")
            lines.append(stripped)
        elif in_stack and (raw.startswith(" ") or raw.startswith("\t")):
            lines.append(stripped)
        if len(lines) >= 140:
            break
    content = sanitize_text("\n".join(lines))
    path = STATE_ROOT / "crashes" / f"crash-{pid}-{int(time.time())}.txt"
    fd, temporary = tempfile.mkstemp(prefix=".crash.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("Sanitized systemd-coredump diagnostic context.\n")
            stream.write("No core bytes, environment variables, auth files, or home-directory files are included.\n\n")
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def diagnose_crash(pid: int) -> int:
    context = crash_context(pid)
    prompt = (
        "Diagnose this crash conservatively using only the sanitized context in "
        f"{context}. Do not read a core dump, process environment, credentials, auth files, "
        "or unrelated home-directory content. Explain likely cause and safe next checks."
    )
    launch_terminal("codex", str(DEFAULT_WORKSPACE), "interactive", prompt)
    notify("Crash diagnosis", f"Opened sanitized PID {pid} context in Codex")
    return 0


def launch_chatgpt() -> int:
    opener = require("xdg-open")
    detached([opener, "https://chatgpt.com/"])
    return 0


def launch_omniroute() -> int:
    opener = require("xdg-open")
    detached([opener, omniroute_dashboard_url()])
    return 0


def zed_binary() -> str:
    for name in ("zed", "zeditor", "zed-editor"):
        candidate = command_path(name)
        if candidate:
            return candidate
    die(
        "Zed is not installed. On Arch, install the verified AUR package or "
        "use Zed's official installer, then rerun this command."
    )


def open_in_zed(targets: list[str], directory: pathlib.Path) -> int:
    detached([zed_binary(), *targets], directory)
    return 0


def safe_zed_project(path: pathlib.Path) -> pathlib.Path:
    candidate = path.expanduser().resolve()
    if not candidate.is_dir() or candidate.is_symlink():
        die("Zed project target must be a real directory")
    lowered = {part.lower() for part in candidate.parts}
    private_roots: set[pathlib.Path] = set()
    try:
        configured = load_config()
        enabled, memory_vault, _ = memory_settings(configured)
        if enabled:
            private_roots.update({memory_vault, project_memory_path(configured)})
    except (ConfigError, MemoryError, OSError, ValueError, SystemExit):
        pass
    if lowered & DENIED_PARTS or candidate in private_roots:
        die("Zed project target is excluded by retrieval security policy")
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False, timeout=3,
    )
    if result.returncode != 0:
        die("Zed project target must be inside a Git repository")
    root = pathlib.Path(result.stdout.strip()).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        die("Zed project target escapes its Git repository")
    return root


def safe_zed_location(value: str, directory: pathlib.Path) -> str:
    match = re.fullmatch(r"(.+?)(?::([1-9][0-9]*))?(?::([1-9][0-9]*))?", value.strip())
    if not match:
        die("inspect requires PATH[:LINE[:COLUMN]]")
    raw_path, line, column = match.groups()
    candidate = pathlib.Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = directory / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        die("Zed inspection is restricted to the selected repository")
    safe_extensionless = False
    content = ""
    try:
        if candidate.is_file() and candidate.stat().st_size <= MAX_FILE_BYTES:
            content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        content = ""
    if candidate.suffix == "" and candidate.is_file() and not candidate.is_symlink():
        denied = candidate.name.lower() in DENIED_NAMES or bool(
            {part.lower() for part in candidate.parts} & DENIED_PARTS
        )
        tracked = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "--error-unmatch", str(candidate.relative_to(directory))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=3,
        ).returncode == 0
        safe_extensionless = bool(content and tracked and not denied and not any(
            pattern.search(content) for pattern in SECRET_PATTERNS
        ))
    if (not candidate.is_file() or candidate.is_symlink()
            or not (safe_to_index(candidate, content) or safe_extensionless)):
        die("Zed inspection target is unavailable or excluded by retrieval security policy")
    location = str(candidate)
    if line:
        location += f":{line}"
        if column:
            location += f":{column}"
    return location


def open_task_in_zed(task_id: str) -> int:
    task = harness().store.display_task(task_id)
    project = pathlib.Path(str(task["projectPath"])).resolve()
    return open_diff_in_zed(project)


def open_diff_in_zed(project: pathlib.Path) -> int:
    project = safe_zed_project(project)
    status_rows = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain=v1", "-z"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        timeout=5,
    ).stdout.split("\0")
    names: list[str] = []
    index = 0
    while index < len(status_rows):
        row = status_rows[index]
        if len(row) < 4:
            index += 1
            continue
        status = row[:2]
        name = row[3:]
        names.append(name)
        # In porcelain-v1 -z output a rename/copy record is followed by the
        # original pathname as a second NUL field without its own XY prefix.
        index += 2 if "R" in status or "C" in status else 1
    targets = [str(project)] + [
        str(project / name) for name in names[:32]
        if (project / name).is_file() and safe_to_index(project / name)
    ]
    return open_in_zed(targets, project)


def open_retrieval_result_in_zed(identifier: str, directory: pathlib.Path) -> int:
    with retrieval_store() as store:
        try:
            item = store.inspect(identifier)
        except KeyError:
            die(f"Unknown retrieval result: {identifier}")
    metadata = item.get("metadata", {})
    if metadata.get("origin") != "repository" or item.get("repository") != str(directory.resolve()):
        die("Only repository-scoped retrieval results may be opened in Zed")
    current = repository_state(directory)
    if item.get("branch") and item.get("branch") != current.get("branch"):
        die("Retrieval result belongs to a different Git branch")
    path = item.get("path")
    if not isinstance(path, str) or not path:
        die("Retrieval result has no repository file location")
    location = path
    if item.get("start_line"):
        location += f":{int(item['start_line'])}"
    return open_in_zed([safe_zed_location(location, directory)], directory)


def memory_command(action: str, as_json: bool) -> int:
    config = load_config()
    enabled, vault, _ = memory_settings(config)
    project_vault = project_memory_path(config)
    if not enabled:
        die("Institutional memory is disabled in ai.json")
    if action == "init":
        created = initialize_vault(vault)
        project_created = initialize_project_vault(project_vault, vault)
        moved = link_project_vault(vault, project_vault)
        vault_id = register_obsidian_vault(vault)
        project_vault_id = register_obsidian_vault(project_vault)
        result = {
            **vault_status(vault),
            "created": created,
            "obsidianVaultId": vault_id,
            "projectVault": {
                **project_vault_status(project_vault),
                "created": project_created,
                "moved": moved,
                "obsidianVaultId": project_vault_id,
            },
        }
    elif action in ("open", "open-projects"):
        try:
            require_vault(vault)
            require_project_vault(project_vault)
        except MemoryError as error:
            die(str(error))
        target = project_vault if action == "open-projects" else vault
        detached([require("xdg-open"), obsidian_uri(target)])
        result = {**vault_status(vault), "projectVault": project_vault_status(project_vault)}
    else:
        result = {**vault_status(vault), "projectVault": project_vault_status(project_vault)}
    combined_ok = result["status"] == "ok" and result["projectVault"]["status"] == "ok"
    if as_json or action not in ("open", "open-projects"):
        if as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            projects = result["projectVault"]
            print(f"Memory: {'ok' if combined_ok else 'degraded'}\nVault: {result['path']}\nProjects vault: {projects['path']}\nMissing: {len(result.get('missing', [])) + len(projects.get('missing', []))}\nSecret findings: {len(result.get('secretFindings', [])) + len(projects.get('secretFindings', []))}")
    return 0 if combined_ok else 1


def retrieval_store(backend_name: str = "feature-hash") -> RetrievalStore:
    if backend_name == "local-neural":
        return RetrievalStore(
            STATE_ROOT / "private/retrieval-neural.sqlite3",
            embedding_backend=LocalNeuralEmbeddingBackend(),
        )
    return RetrievalStore(
        STATE_ROOT / "private/retrieval.sqlite3",
        embedding_backend=FeatureHashEmbeddingBackend(),
    )


def ui_search_result(item: Any) -> dict[str, Any]:
    """Bound a retrieval result for the untrusted desktop presentation layer."""
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    origin = metadata.get("origin")
    return {
        "schemaVersion": 1,
        "id": item.id,
        "sourceType": item.source_type,
        "origin": origin,
        "repository": item.repository,
        "branch": item.branch,
        "path": item.path,
        "symbol": item.symbol,
        "startLine": metadata.get("startLine") or metadata.get("start_line"),
        "endLine": metadata.get("endLine") or metadata.get("end_line"),
        "snippet": str(item.content).replace("\n", " ")[:280],
        "score": round(float(item.score), 5),
        "capabilities": {
        "inspect": True,
        "open": origin == "repository" and bool(item.path),
        },
    }


def reindex_knowledge(directory: pathlib.Path, backend_name: str = "feature-hash") -> dict[str, Any]:
    config = load_config()
    enabled, vault, _ = memory_settings(config)
    project_vault = project_memory_path(config)
    if enabled:
        require_vault(vault)
        require_project_vault(project_vault)
    with retrieval_store(backend_name) as store:
        indexer = RepositoryIndexer(store)
        index_seconds = 300.0 if backend_name == "local-neural" else 5.0
        trusted_paths = verified_release_source_paths(directory)
        summaries = {"repository": asdict(indexer.index(
            directory, additional_trusted_paths=trusted_paths,
            max_seconds=index_seconds,
        ))}
        summaries["episodic"] = asdict(index_episodic_database(
            store, STATE_ROOT / "private/harness.sqlite3"
        ))
        if enabled:
            # Schema-v1 migration: early development builds indexed whole vaults
            # under their filesystem roots. Remove only those derived rows before
            # applying global-shared and project-associated scopes.
            summaries["legacyVaultRowsRemoved"] = store.purge_derived_scope(str(vault))
            summaries["legacyProjectVaultRowsRemoved"] = store.purge_derived_scope(str(project_vault))
            shared = vault / "Shared"
            summaries["longTermShared"] = asdict(indexer.index(
                shared, global_scope=True, origin="institutional_memory",
                trusted_non_git=True, max_seconds=index_seconds,
            ))
            project_notes = project_vault / directory.name
            if project_notes.is_dir():
                summaries["projectMemory"] = asdict(indexer.index(
                    project_notes, scope_repository=str(directory.resolve()),
                    origin="institutional_memory",
                    trusted_non_git=True, max_seconds=index_seconds,
                ))
        return {"schemaVersion": 1, "summaries": summaries, "stats": store.stats()}


def retrieval_command(args: argparse.Namespace) -> int:
    directory = safe_directory(args.directory)
    if args.action == "reindex":
        print(json.dumps(reindex_knowledge(directory, args.embedding_backend), ensure_ascii=False))
        return 0
    with retrieval_store(args.embedding_backend) as store:
        if args.action in ("status", "stats"):
            print(json.dumps({**store.stats(), "lastRetrieval": store.last_trace()}, ensure_ascii=False))
            return 0
        if args.action == "eval":
            print(json.dumps(evaluate_retrieval(store, directory), ensure_ascii=False))
            return 0
        if args.action == "benchmark":
            dataset = pathlib.Path(args.dataset).expanduser().resolve()
            index_started = time.monotonic()
            RepositoryIndexer(store).index(
                directory,
                additional_trusted_paths=verified_release_source_paths(directory),
            )
            index_maintenance_ms = (time.monotonic() - index_started) * 1_000
            project = str(directory.resolve())
            live_snapshot = {
                "recentTasks": [
                    row for row in harness().store.list_display_tasks(limit=20)
                    if row.get("projectPath") == project
                ][:10],
                "logicalSessions": [
                    row for row in harness().list_logical_sessions(recoverable_only=False)
                    if row.get("repository") == project
                ][:10],
            }
            result = run_benchmark(
                store,
                load_benchmark_cases(dataset),
                default_repository=directory,
                cold_cache=not args.warm_cache,
                limit=args.limit,
                context_budget=args.budget,
                router_profile=args.router_profile,
                live_state_snapshot=live_snapshot,
                index_maintenance_ms=index_maintenance_ms,
            )
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                output = pathlib.Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
                temporary.write_text(serialized + "\n", encoding="utf-8")
                os.chmod(temporary, 0o600)
                os.replace(temporary, output)
            print(serialized)
            return 0
        if args.action == "explain" and not args.query:
            print(json.dumps(store.last_trace(), ensure_ascii=False))
            return 0
        if args.action == "open":
            if not args.query:
                die("retrieval open requires a result id")
            return open_retrieval_result_in_zed(args.query, directory)
        query = args.query or ""
        if not query.strip():
            die(f"retrieval {args.action} requires a query")
        router = QueryRouter(); route = router.route(query); state = repository_state(directory)
        if route.intent in {"live_state", "no_retrieval"}:
            result = {"schemaVersion": 1, "route": asdict(route), "structuredState": state,
                      "results": [], "securityBoundary": "Retrieved content is untrusted evidence."}
        else:
            results, trace = store.search(query, repository=state["repository"], branch=state["branch"],
                source_types=route.sources, use_lexical=route.use_lexical,
                use_semantic=route.use_semantic, use_graph=route.use_graph,
                historical=route.historical, limit=args.limit,
                allowed_origins=allowed_origins_for_route(route, memory_allowed=True))
            context = ContextAssembler().assemble(request=query, structured_state=state,
                results=results, budget_tokens=args.budget)
            result = {"schemaVersion": 1, "route": asdict(route), "structuredState": state,
                      "results": [ui_search_result(item) for item in results] if args.action == "ui-search"
                      else [item.projection() for item in results],
                      "trace": trace}
            if args.action != "ui-search":
                result["context"] = context
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.action == "explain" else None))
        return 0


def advanced_memory_command(args: argparse.Namespace) -> int:
    directory = safe_directory(args.directory)
    if args.action == "reindex":
        print(json.dumps(reindex_knowledge(directory), ensure_ascii=False)); return 0
    with retrieval_store() as store:
        state = repository_state(directory)
        repository = state["repository"]
        if args.action == "stats":
            print(json.dumps(store.stats(), ensure_ascii=False)); return 0
        if args.action == "list":
            print(json.dumps({"schemaVersion":1,"memories":store.list_memories(repository=repository, limit=args.limit)}, ensure_ascii=False)); return 0
        if args.action == "inspect":
            if not args.value: die("memory inspect requires an id")
            try:
                inspected = store.inspect(args.value)
                require_memory_scope(inspected, repository)
                print(json.dumps(inspected, ensure_ascii=False, indent=2))
            except KeyError: die(f"Unknown memory: {args.value}")
            return 0
        if args.action == "forget":
            if not args.value: die("memory forget requires an id")
            try:
                forgotten = store.inspect(args.value)
                require_memory_scope(forgotten, repository)
                require_mutable_memory(forgotten)
            except KeyError: die(f"Unknown memory: {args.value}")
            append_memory_ledger(project_memory_path(load_config()), repository,
                args.value, "forgotten", f"Forgotten at {utc_now()}", metadata={"previousType":forgotten["source_type"]})
            if not store.forget(args.value): die(f"Unknown memory: {args.value}")
            print(args.value); return 0
        if args.action == "add":
            if not args.value: die("memory add requires content")
            if args.supersedes:
                try:
                    old_memory = store.inspect(args.supersedes)
                    require_memory_scope(old_memory, repository)
                    require_mutable_memory(old_memory)
                except KeyError: die(f"Unknown memory: {args.supersedes}")
            identifier = store.upsert_document(source_type=args.type, content=args.value,
                repository=repository, branch=state["branch"], importance=args.importance,
                confidence=args.confidence, valid_from=utc_now(),
                metadata={"explicit": True}, origin="explicit_memory")
            try:
                append_memory_ledger(project_memory_path(load_config()), repository,
                    identifier, args.type, args.value, metadata={"importance":args.importance,
                    "confidence":args.confidence,"supersedes":args.supersedes})
            except BaseException:
                store.forget(identifier)
                raise
            if args.supersedes: store.supersede(args.supersedes, identifier)
            print(identifier); return 0
        if args.action == "consolidate":
            proposal = consolidation_proposal(
                store, repository=repository, limit=args.limit
            )
            if proposal is None:
                print(json.dumps({"schemaVersion":1,"consolidated":False,"proposal":None}))
                return 0
            if not args.approve_sha256:
                print(json.dumps({
                    "schemaVersion":1, "consolidated":False,
                    "requiresApproval":True, "proposal":proposal,
                }, ensure_ascii=False, indent=2))
                return 0
            identifier = consolidate_memory(
                store, repository=repository, limit=args.limit,
                approved_sha256=args.approve_sha256,
            )
            if identifier:
                memory = store.inspect(identifier)
                try:
                    append_memory_ledger(project_memory_path(load_config()), repository,
                        identifier, "consolidated", memory["content"],
                        metadata=memory["metadata"])
                except BaseException:
                    store.forget(identifier)
                    raise
            print(json.dumps({"schemaVersion":1,"memoryId":identifier,"consolidated":identifier is not None})); return 0
        if args.action in ("search", "ui-search"):
            if not args.value: die("memory search requires a query")
            results, trace = store.search(args.value, repository=repository, branch=state["branch"],
                source_types=("decision","error","fix","session","checkpoint","memory"), limit=args.limit,
                historical=args.historical)
            projected = [ui_search_result(item) for item in results] if args.action == "ui-search" else [item.projection() for item in results]
            print(json.dumps({"schemaVersion":1,"results":projected,"trace":trace}, ensure_ascii=False)); return 0
    die(f"Unsupported memory action: {args.action}")


def require_memory_scope(memory: Mapping[str, Any], repository: str) -> None:
    if memory.get("repository") != repository:
        raise KeyError(str(memory.get("id", "memory")))


def require_mutable_memory(memory: Mapping[str, Any]) -> None:
    metadata = memory.get("metadata")
    if not isinstance(metadata, Mapping) or not (
        metadata.get("explicit") or metadata.get("consolidated")
    ):
        die("This is derived evidence; edit its authoritative source and reindex instead")


def append_memory_ledger(vault: pathlib.Path, repository: str, identifier: str,
                         kind: str, content: str, *, metadata: Mapping[str, Any]) -> None:
    """Keep explicit memory mutations human-readable in the project vault."""
    project = vault / pathlib.Path(repository).name
    if not project.is_dir() or project.is_symlink():
        die(f"Project memory directory is unavailable: {project}")
    target = project / "MEMORIES.md"
    if target.is_symlink():
        die("Project memory ledger must not be a symbolic link")
    clean, changed = redact_secret_text(content)
    if changed:
        die("Memory contains credential-shaped data and was not stored")
    block = (
        f"\n## {utc_now()} — {kind}\n\n"
        f"- ID: `{identifier}`\n"
        f"- Repository: `{repository}`\n"
        f"- Metadata: `{json.dumps(dict(metadata), sort_keys=True)}`\n\n"
        f"{clean.strip()}\n"
    )
    existed = target.exists()
    with target.open("a", encoding="utf-8") as stream:
        if not existed:
            stream.write("# Durable Memory Ledger\n")
        stream.write(block); stream.flush(); os.fsync(stream.fileno())
    os.chmod(target, 0o600)


def multi_launch(count: int, directory_value: str | None) -> int:
    if count < 2 or count > 4:
        die("Multi-agent count must be 2, 3, or 4")
    directory = safe_directory(directory_value)
    agents = ["codex", "pi"] + ["codex"] * (count - 2)
    tmux = command_path("tmux")
    if not tmux:
        for agent in agents:
            launch_terminal(agent, str(directory))
        notify("AI workspace", f"Opened {count} tiled agent windows (tmux unavailable)")
        return 0
    session = f"quattro-ai-{int(time.time())}"
    def worker_argv(agent: str) -> list[str]:
        account = str(load_config()["defaultCodexAccount"])
        session_id = uuid.uuid4().hex
        values = [str(SCRIPT_PATH), "_session", agent, str(directory), "--session-id", session_id]
        if agent == "codex":
            values.extend(["--account", account])
        return values
    subprocess.run([tmux, "new-session", "-d", "-s", session, "-c", str(directory), *worker_argv(agents[0])], check=True)
    if count >= 2:
        subprocess.run([tmux, "split-window", "-h", "-p", "50", "-t", f"{session}:0", "-c", str(directory), *worker_argv(agents[1])], check=True)
    if count == 3:
        subprocess.run([tmux, "split-window", "-v", "-p", "50", "-t", f"{session}:0.1", "-c", str(directory), *worker_argv(agents[2])], check=True)
    elif count == 4:
        subprocess.run([tmux, "split-window", "-v", "-p", "50", "-t", f"{session}:0.0", "-c", str(directory), *worker_argv(agents[2])], check=True)
        subprocess.run([tmux, "split-window", "-v", "-p", "50", "-t", f"{session}:0.1", "-c", str(directory), *worker_argv(agents[3])], check=True)
        subprocess.run([tmux, "select-layout", "-t", f"{session}:0", "tiled"], check=True)
    detached([require("foot"), "--app-id", "quattro-ai-multi", "--title", f"AI Workspace · {count}", tmux, "attach", "-t", session], directory)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quattro-agent", description="Quattro AI control plane")
    parser.add_argument("--version", action="version", version=f"quattro-agent {VERSION}")
    # Keep the implicit bare-command launch path equivalent to `launch`.
    # argparse only creates subparser-specific attributes after a subcommand is
    # selected, so provide the two launch defaults at the root parser as well.
    parser.set_defaults(agent=None, directory=None)
    sub = parser.add_subparsers(dest="command")
    launch = sub.add_parser("launch")
    launch.add_argument("agent", nargs="?", choices=("codex", "pi"))
    launch.add_argument("directory", nargs="?")
    launch.add_argument("--policy")
    launch.add_argument("--confirm-full-access", action="store_true")
    sub.add_parser("desktop")
    prompt = sub.add_parser("prompt")
    prompt.add_argument("values", nargs="+")
    prompt.add_argument("--policy")
    prompt.add_argument("--confirm-full-access", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("target", nargs="?", help="logical Quattro session id or legacy project path")
    resume.add_argument("--session")
    resume.add_argument("--account")
    resume.add_argument("--policy")
    resume.add_argument("--confirm-full-access", action="store_true")
    recover = sub.add_parser("recover", help="force checkpoint recovery for a logical session")
    recover.add_argument("quattro_session_id")
    recover.add_argument("--account")
    checkpoint = sub.add_parser("checkpoint", help="save the current logical Quattro session")
    checkpoint.add_argument("quattro_session_id", nargs="?")
    checkpoint.add_argument("--task")
    checkpoint.add_argument("--completed", action="append", default=[])
    checkpoint.add_argument("--decision", action="append", default=[])
    checkpoint.add_argument("--validation", action="append", default=[])
    checkpoint.add_argument("--unresolved", action="append", default=[])
    checkpoint.add_argument("--next-action")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--json", action="store_true")
    account = sub.add_parser("account")
    account.add_argument("action", nargs="?", choices=("list", "set"))
    account.add_argument("account_id", nargs="?")
    usage = sub.add_parser("usage")
    usage.add_argument("action", choices=("refresh", "status"))
    usage.add_argument("--account")
    usage.add_argument("--all", action="store_true", dest="all_accounts")
    recent = sub.add_parser("recent")
    recent.add_argument("action", choices=("refresh", "status"), nargs="?", default="status")
    sessions = sub.add_parser("sessions")
    sessions.add_argument("action", choices=("status", "clean", "native", "open", "stop"), nargs="?", default="status")
    sessions.add_argument("session_id", nargs="?")
    new_task = sub.add_parser("new-task")
    new_task.add_argument("--agent", choices=("codex", "pi"), default=None)
    new_task.add_argument("--directory")
    new_task.add_argument("--prompt", default="")
    new_task.add_argument("--mode", choices=("interactive", "prompt"), default="interactive")
    new_task.add_argument("--policy")
    new_task.add_argument("--confirm-full-access", action="store_true")
    new_task.add_argument("--scope", action="append", default=[], help="repository-relative writable scope; repeatable")
    submit = sub.add_parser("submit", help="queue a durable task and return immediately")
    submit.add_argument("--agent", choices=("auto", "codex", "pi"), default="auto")
    submit.add_argument("--directory")
    submit.add_argument("--prompt", required=True)
    submit.add_argument("--policy")
    submit.add_argument("--confirm-full-access", action="store_true")
    multi = sub.add_parser("multi")
    multi.add_argument("count", type=int)
    multi.add_argument("directory", nargs="?")
    multi.add_argument("--objective", default="")
    multi.add_argument("--policy")
    multi.add_argument("--confirm-full-access", action="store_true")
    multi.add_argument("--scope", action="append", default=[], help="repository-relative writable scope; repeatable")
    task = sub.add_parser("task", help="inspect and control durable tasks")
    task.add_argument("action", choices=("list", "show", "cancel", "retry", "events", "artifacts", "reconcile", "open"))
    task.add_argument("task_id", nargs="?")
    task.add_argument("--json", action="store_true")
    approval = sub.add_parser("approval", help="inspect and resolve durable approvals")
    approval.add_argument("action", choices=("list", "show", "approve", "reject"))
    approval.add_argument("approval_id", nargs="?")
    approval.add_argument("--json", action="store_true")
    workflow = sub.add_parser("workflow", help="run a coordinated multi-agent workflow")
    workflow.add_argument("action", choices=("run",))
    workflow.add_argument("name", choices=("implementation-review",))
    workflow.add_argument("--agents", type=int, choices=(2, 3, 4), default=2)
    workflow.add_argument("--directory")
    workflow.add_argument("--objective", required=True)
    workflow.add_argument("--policy")
    workflow.add_argument("--confirm-full-access", action="store_true")
    workflow.add_argument("--scope", action="append", default=[], help="repository-relative writable scope; repeatable")
    delegate = sub.add_parser("delegate", help="run one bounded Pi specialist for Codex")
    delegate.add_argument("action", choices=("decide", "run"))
    delegate.add_argument(
        "--kind", required=True,
        choices=("exploration", "implementation", "tests", "review", "security"),
    )
    delegate.add_argument("--directory")
    delegate.add_argument("--objective", required=True)
    delegate.add_argument("--parent-task")
    collaboration = sub.add_parser(
        "collab", help="inspect and coordinate same-repository Quattro sessions"
    )
    collaboration.add_argument(
        "action", choices=("status", "claim", "depend", "integrate", "cleanup", "recover")
    )
    collaboration.add_argument("target", nargs="?")
    collaboration.add_argument("--session")
    collaboration.add_argument("--summary")
    collaboration.add_argument("--scope", action="append", default=[])
    collaboration.add_argument("--strategy", choices=("merge", "cherry-pick"), default="merge")
    collaboration.add_argument("--json", action="store_true")
    config_parser = sub.add_parser("config", help="initialize, validate, or migrate ai.json")
    config_parser.add_argument("action", choices=("init", "validate", "migrate"))
    config_parser.add_argument("--dry-run", action="store_true")
    config_parser.add_argument("--force", action="store_true", help="replace an existing config during init")
    workspace = sub.add_parser("workspace", help="resolve project destinations from policy")
    workspace.add_argument("action", choices=("resolve",))
    workspace.add_argument("--operation", choices=("clone", "create"), default="clone")
    workspace.add_argument("--repository")
    workspace.add_argument("--destination")
    deployment = sub.add_parser("deployment", help="inspect and activate deployment provenance")
    deployment.add_argument("action", choices=("status", "save", "manifest", "deploy", "rollback"))
    deployment.add_argument("revision", nargs="?")
    deployment.add_argument("--profile", choices=("core", "desktop", "all"), default="all")
    deployment.add_argument("--confirm", action="store_true")
    sub.add_parser("chatgpt")
    sub.add_parser("omniroute")
    memory_parser = sub.add_parser("memory")
    memory_parser.add_argument("action", choices=("init", "status", "open", "open-projects", "search", "ui-search", "list", "inspect", "add", "forget", "consolidate", "reindex", "stats"), nargs="?", default="status")
    memory_parser.add_argument("value", nargs="?")
    memory_parser.add_argument("--directory")
    memory_parser.add_argument("--type", choices=("decision", "error", "fix", "session", "checkpoint", "memory"), default="memory")
    memory_parser.add_argument("--importance", type=float, default=0.7)
    memory_parser.add_argument("--confidence", type=float, default=0.8)
    memory_parser.add_argument("--supersedes")
    memory_parser.add_argument("--historical", action="store_true")
    memory_parser.add_argument("--approve-sha256")
    memory_parser.add_argument("--limit", type=int, default=20)
    memory_parser.add_argument("--json", action="store_true")
    retrieval = sub.add_parser("retrieval", help="search and inspect the local hybrid knowledge index")
    retrieval.add_argument("action", choices=("search", "ui-search", "explain", "status", "stats", "reindex", "eval", "benchmark", "open"), nargs="?", default="status")
    retrieval.add_argument("query", nargs="?")
    retrieval.add_argument("--directory")
    retrieval.add_argument("--limit", type=int, default=8)
    retrieval.add_argument("--budget", type=int, default=4000)
    retrieval.add_argument("--dataset", default=str(DEFAULT_WORKSPACE / "benchmarks/retrieval_real_world.json"))
    retrieval.add_argument("--output")
    retrieval.add_argument("--warm-cache", action="store_true")
    retrieval.add_argument("--embedding-backend", choices=("feature-hash", "local-neural"), default="feature-hash")
    retrieval.add_argument("--router-profile", choices=("current", "legacy"), default="current")
    open_parser = sub.add_parser("open", help="open a repository or project path in Zed")
    open_parser.add_argument("path", nargs="?")
    inspect_parser = sub.add_parser("inspect", help="open PATH[:LINE[:COLUMN]] in Zed")
    inspect_parser.add_argument("location")
    inspect_parser.add_argument("--directory")
    diff_parser = sub.add_parser("diff", help="open the repository and changed files in Zed")
    diff_parser.add_argument("--directory")
    dictation = sub.add_parser("dictation")
    dictation.add_argument("action", choices=("toggle", "status"), nargs="?", default="toggle")
    crash = sub.add_parser("crash")
    crash.add_argument("action", choices=("list", "diagnose"), nargs="?", default="list")
    crash.add_argument("pid", nargs="?", type=int)
    review = sub.add_parser("pr-review", help="autonomously review a GitHub pull request")
    review.add_argument("target", help="OWNER/REPO#PR, OWNER/REPO, or GitHub pull URL")
    review.add_argument("--pr", type=int)
    review.add_argument("--publish", action="store_true", help="post the review to GitHub")
    review.add_argument("--mode", choices=("comment", "request-changes", "approve"))
    review.add_argument("--account", help="Codex account id")
    review.add_argument("--model")
    review.add_argument("--depth", choices=("focused", "full", "exhaustive"))
    review.add_argument("--no-tests", action="store_true")
    review.add_argument("--no-security-scan", action="store_true")
    review.add_argument("--timeout", type=int)
    review.add_argument("--severity-threshold", choices=("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"))
    review.add_argument("--output", help="write the Markdown review to this path")
    review.add_argument("--json", action="store_true", help="print a compact execution report")
    sub.add_parser("state")
    sub.add_parser("ui-state", help="read the lightweight Control Center snapshot")
    worker = sub.add_parser("_session")
    worker.add_argument("agent", choices=("codex", "pi"))
    worker.add_argument("directory")
    worker.add_argument("--account")
    worker.add_argument("--session-id", required=True)
    worker.add_argument("--mode", choices=("interactive", "prompt", "resume"), default="interactive")
    worker.add_argument("--native-session-ref")
    worker.add_argument("--prompt", default="")
    recording = sub.add_parser("_dictation-record")
    recording.add_argument("session_id")
    recording.add_argument("audio")
    task_worker = sub.add_parser("_task-worker")
    task_worker.add_argument("task_id")
    workflow_worker = sub.add_parser("_workflow-worker")
    workflow_worker.add_argument("parent_task_id")
    return parser


def _deployment_profiles(requested: str) -> tuple[str, ...]:
    return ("core", "desktop") if requested == "all" else (requested,)


def _deployment_status(profile: str) -> dict[str, Any]:
    mappings, manifest_path, _release_root = deployment_profile(profile)
    if not manifest_path.is_file():
        return {
            "profile": profile,
            "installed": False,
            "status": "optional-not-installed" if profile == "desktop" else "not-deployed",
            "manifestPath": str(manifest_path),
        }
    manifest = load_manifest(manifest_path)
    live = verify_manifest_files(manifest, DEFAULT_WORKSPACE, HOME)
    return {
        "profile": profile,
        "installed": True,
        "status": "ok" if manifest["parity"]["allMatch"] and live["allMatch"] else "drift",
        "manifestPath": str(manifest_path),
        "manifest": manifest,
        "liveParity": live,
    }


def _find_previous_release(
    active: Mapping[str, Any], paths: set[str], profile: str,
) -> pathlib.Path | None:
    previous_revision = str(active["gitRevision"])
    candidates = [
        RELEASE_ROOT / previous_revision / "release.json",
        RELEASE_ROOT / f"{profile}-{previous_revision}" / "release.json",
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        release = load_release(candidate)
        covered = {str(row["path"]) for row in release["files"]}
        covered.update(str(path) for path in release["absentPaths"])
        if release["revision"] == previous_revision and paths <= covered:
            return candidate
    return None


def _deploy_profile(profile: str, revision: str) -> dict[str, Any]:
    mappings, manifest_path, _release_root = deployment_profile(profile)
    active = load_manifest(manifest_path) if manifest_path.is_file() else None
    current_paths = deployment_paths(mappings=mappings)
    previous_paths = deployment_paths(active, mappings) if active is not None else set()
    retired_paths = sorted(
        (previous_paths - current_paths)
        | (DESKTOP_RETIRED_PATHS if profile == "desktop" else set())
    )

    previous_release_manifest = None
    previous_revision = None
    if active is not None:
        previous_revision = str(active["gitRevision"])
        previous_release_manifest = _find_previous_release(active, previous_paths, profile)
        if previous_release_manifest is None:
            snapshot_id = f"{profile}-{previous_revision}-{uuid.uuid4().hex}"
            previous_release_manifest = create_release(
                RELEASE_ROOT, previous_revision, HOME, sorted(previous_paths), release_id=snapshot_id,
            )

    candidate_id = f"{profile}-{revision}"
    if (RELEASE_ROOT / candidate_id).exists():
        candidate_id = f"{candidate_id}-{uuid.uuid4().hex}"
    candidate = create_source_release(
        RELEASE_ROOT, revision, DEFAULT_WORKSPACE, mappings,
        release_id=candidate_id, absent_paths=retired_paths,
    )
    restored = restore_release(candidate, HOME, release_root=RELEASE_ROOT, expected_revision=revision)
    rollback_manifest = (
        previous_release_manifest.relative_to(RELEASE_ROOT.resolve(strict=False)).as_posix()
        if previous_release_manifest is not None else None
    )
    manifest = build_manifest(
        DEFAULT_WORKSPACE, HOME, mappings, revision=revision,
        rollback_manifest=rollback_manifest, rollback_revision=previous_revision,
    )
    if not manifest["parity"]["allMatch"]:
        die(f"Refusing to activate {profile} deployment with source/deployed mismatches")
    write_manifest_atomic(manifest_path, manifest)
    return {
        "profile": profile,
        "revision": revision,
        "releaseManifest": str(candidate),
        "restored": [str(path) for path in restored],
        "retiredPaths": retired_paths,
        "manifest": manifest,
    }


def _manifest_profile(profile: str, revision: str) -> dict[str, Any]:
    mappings, manifest_path, _release_root = deployment_profile(profile)
    active = load_manifest(manifest_path) if manifest_path.is_file() else None
    rollback_revision = None
    rollback_manifest = None
    if active is not None and active["gitRevision"] == revision:
        rollback_revision = active["rollback"]["previousGitRevision"]
        rollback_manifest = active["rollback"]["previousManifest"]
    manifest = build_manifest(
        DEFAULT_WORKSPACE, HOME, mappings, revision=revision,
        rollback_manifest=rollback_manifest, rollback_revision=rollback_revision,
    )
    if not manifest["parity"]["allMatch"]:
        die(f"Refusing to activate {profile} deployment with source/deployed mismatches")
    write_manifest_atomic(manifest_path, manifest)
    return {"profile": profile, "manifest": manifest}


def _rollback_profile(profile: str, requested_revision: str) -> dict[str, Any]:
    _mappings, manifest_path, _release_root = deployment_profile(profile)
    release_manifest: pathlib.Path | None = None
    if manifest_path.is_file():
        active = load_manifest(manifest_path)
        rollback = active["rollback"]
        previous_revision = str(rollback.get("previousGitRevision") or "").lower()
        previous_manifest = rollback.get("previousManifest")
        if previous_revision.startswith(requested_revision) and isinstance(previous_manifest, str):
            candidate = RELEASE_ROOT / pathlib.PurePosixPath(previous_manifest)
            if candidate.is_file():
                release_manifest = candidate
    if release_manifest is None:
        candidates = []
        if RELEASE_ROOT.is_dir():
            for candidate in RELEASE_ROOT.glob("*/release.json"):
                try:
                    release = load_release(candidate)
                except (OSError, ValueError):
                    continue
                if str(release["revision"]).startswith(requested_revision):
                    candidates.append(candidate)
        if len(candidates) != 1:
            die("deployment rollback revision is missing or ambiguous")
        release_manifest = candidates[0]
    release = load_release(release_manifest)
    restored = restore_release(
        release_manifest, HOME, release_root=RELEASE_ROOT, expected_revision=release["revision"],
    )
    return {"profile": profile, "revision": release["revision"], "restored": [str(path) for path in restored], "restartRequired": True}


def handle_deployment(args: argparse.Namespace) -> int:
    migration = migrate_deployment_manifest()
    profiles = _deployment_profiles(args.profile)
    if args.action == "status":
        results = [_deployment_status(profile) for profile in profiles]
        print(json.dumps({"schemaVersion": 2, "migration": migration, "profiles": results}, ensure_ascii=False))
        return 0 if all(row["status"] in {"ok", "optional-not-installed"} for row in results) else 1
    if args.action == "rollback":
        if args.profile == "all":
            die("deployment rollback requires --profile core or --profile desktop")
        if not args.revision or not args.confirm:
            die("deployment rollback requires REVISION and --confirm")
        if not re.fullmatch(r"[0-9a-f]{7,64}", args.revision.lower()):
            die("deployment rollback revision must be hexadecimal")
        print(json.dumps(_rollback_profile(args.profile, args.revision.lower()), ensure_ascii=False))
        return 0

    source_tree_is_clean(DEFAULT_WORKSPACE)
    revision = args.revision or resolve_git_revision(DEFAULT_WORKSPACE)
    if args.action == "deploy":
        results = [_deploy_profile(profile, revision) for profile in profiles]
    elif args.action == "manifest":
        results = [_manifest_profile(profile, revision) for profile in profiles]
    elif args.action == "save":
        results = []
        for profile in profiles:
            mappings, manifest_path, _release_root = deployment_profile(profile)
            active = load_manifest(manifest_path) if manifest_path.is_file() else None
            paths = sorted(deployment_paths(active, mappings))
            release_id = f"{profile}-{revision}-{uuid.uuid4().hex}"
            saved = create_release(RELEASE_ROOT, revision, HOME, paths, release_id=release_id)
            results.append({"profile": profile, "revision": revision, "releaseManifest": str(saved)})
    else:
        die(f"unsupported deployment action: {args.action}")
    print(json.dumps({"schemaVersion": 2, "migration": migration, "profiles": results}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "ui-state":
        print(json.dumps(ui_snapshot(), ensure_ascii=False))
        return 0
    if args.command == "config" and args.action == "init":
        return initialize_config(args.force)
    ensure_state_dirs()
    config = load_config()
    command = args.command or "launch"
    if command == "launch":
        agent = args.agent or str(config["defaultAgent"])
        print(launch_terminal(
            agent, args.directory,
            profile_name=getattr(args, "policy", None),
            confirm_full_access=getattr(args, "confirm_full_access", False),
        ))
        return 0
    if command == "desktop":
        print(launch_terminal("codex", str(DEFAULT_WORKSPACE)))
        return 0
    if command == "open":
        base = pathlib.Path.cwd().resolve()
        if not args.path:
            project = safe_zed_project(base)
            return open_in_zed([str(project)], project)
        candidate = pathlib.Path(args.path).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        candidate = candidate.resolve()
        if candidate.is_dir():
            project = safe_zed_project(candidate)
            return open_in_zed([str(project)], project)
        project = safe_zed_project(base)
        return open_in_zed([safe_zed_location(str(candidate), project)], project)
    if command == "inspect":
        directory = safe_zed_project(safe_directory(args.directory))
        return open_in_zed([safe_zed_location(args.location, directory)], directory)
    if command == "diff":
        return open_diff_in_zed(safe_directory(args.directory))
    if command == "prompt":
        values = list(args.values)
        agent = values.pop(0) if values and values[0] in ("codex", "pi") else str(config["defaultAgent"])
        prompt_value = values.pop(0) if values else ""
        directory_value = values.pop(0) if values else None
        if values:
            die("Too many prompt arguments")
        return run_prompt(
            agent, prompt_value, directory_value,
            profile_name=args.policy,
            confirm_full_access=args.confirm_full_access,
        )
    if command == "resume":
        if args.target is None and args.session is None:
            print(json.dumps({
                "schemaVersion": 1,
                "sessions": harness().list_logical_sessions(recoverable_only=True),
            }, ensure_ascii=False))
            return 0
        logical_id = None
        if args.target:
            try:
                logical_id = harness().store.get_logical_session(args.target)["quattro_session_id"]
            except KeyError:
                logical_id = None
        if logical_id is None and args.session:
            matches = [row for row in harness().store.list_logical_sessions() if (
                row.get("current_codex_session_id") == args.session
                or args.session in (row.get("previous_codex_session_ids") or [])
            )]
            logical_id = matches[0]["quattro_session_id"] if matches else None
        if logical_id is None and args.target:
            directory = safe_directory(args.target)
            matches = [row for row in harness().store.list_logical_sessions() if (
                row["repository_path"] == str(directory)
                or row["working_directory"] == str(directory)
            )]
            if matches:
                logical_id = matches[0]["quattro_session_id"]
            else:
                # Backward-compatible native-only path for legacy tasks.
                prepare_codex_launch(config, args.account or str(config["defaultCodexAccount"]))
                native_target = resolve_codex_resume_target(
                    config, directory, session_id=args.session, account_id=args.account
                )
                if native_target is None:
                    die(f"No logical or native resumable Codex session was found for {directory}")
                print(launch_terminal(
                    "codex", str(directory), "resume",
                    account_id=args.account or str(config["defaultCodexAccount"]),
                    native_session_ref=native_target["sessionId"],
                    profile_name=args.policy,
                    confirm_full_access=args.confirm_full_access,
                ))
                return 0
        if logical_id is None:
            die("No recoverable logical Quattro session matched the request")
        prepare_codex_launch(config, args.account or str(config["defaultCodexAccount"]))
        native_rows = scan_codex_sessions(config)
        logical = harness().store.get_logical_session(logical_id)
        native_id = logical.get("current_codex_session_id")
        native_available = bool(native_id and any(
            row.get("sessionId") == native_id and row.get("resumable") for row in native_rows
        ))
        task_id, path = harness().prepare_resume_task(
            logical_id, native_session_available=native_available, account_id=args.account,
        )
        harness().launch_terminal(task_id)
        print(json.dumps({"quattroSessionId": logical_id, "taskId": task_id, "path": path}))
        return 0
    if command == "recover":
        try:
            task_id = harness().prepare_recovery_task(
                args.quattro_session_id, account_id=args.account,
                reason="Explicit forced recovery requested",
            )
            harness().launch_terminal(task_id)
            print(json.dumps({
                "quattroSessionId": args.quattro_session_id,
                "taskId": task_id,
                "path": "checkpoint-recovery",
            }))
            return 0
        except (KeyError, LeaseConflict, RuntimeError, ValueError) as error:
            die(str(error))
    if command == "checkpoint":
        logical_id = args.quattro_session_id or os.environ.get("QUATTRO_SESSION_ID")
        task_id = args.task or os.environ.get("QUATTRO_TASK_ID")
        try:
            if logical_id and not task_id:
                task_id = str(harness().store.get_logical_session(logical_id)["current_task_id"])
            if task_id and not logical_id:
                logical = harness().store.logical_session_for_task(task_id)
                logical_id = str(logical["quattro_session_id"]) if logical else None
            if not logical_id or not task_id:
                cwd = str(pathlib.Path.cwd().resolve())
                matches = [row for row in harness().store.list_logical_sessions() if (
                    row["repository_path"] == cwd or row["working_directory"] == cwd
                )]
                if not matches:
                    die("No logical Quattro session is associated with this directory")
                logical_id = str(matches[0]["quattro_session_id"])
                task_id = str(matches[0]["current_task_id"])
            checkpoint_id = harness().checkpoint_task(
                task_id,
                kind="manual",
                completed=tuple(args.completed),
                important_decisions=tuple(args.decision),
                validation=tuple(args.validation),
                unresolved=tuple(args.unresolved),
                next_action=args.next_action,
            )
            print(json.dumps({
                "quattroSessionId": logical_id,
                "taskId": task_id,
                "checkpointId": checkpoint_id,
                "taskContinues": True,
            }))
            return 0
        except (KeyError, RuntimeError, ValueError) as error:
            die(str(error))
    if command == "status":
        print_status(args.json)
        return 0
    if command == "doctor":
        return doctor(args.json)
    if command == "account":
        if args.action in (None, "list"):
            print(json.dumps({"active": config["defaultCodexAccount"], "accounts": [account_login_state(a) for a in config["accounts"]]}, ensure_ascii=False))
            return 0
        if not args.account_id:
            die("account set requires an account id")
        record = account_record(config, args.account_id)
        state = account_login_state(record)
        if not state["authenticated"]:
            die(f"{args.account_id} is not authenticated")
        config["defaultCodexAccount"] = args.account_id
        harness().persist_config(config)
        print(args.account_id)
        return 0
    if command == "usage":
        if args.account and args.all_accounts:
            die("usage accepts either --account or --all, not both")
        if args.action == "refresh":
            return refresh_all_usage() if args.all_accounts else refresh_usage(args.account)
        if args.all_accounts:
            die("usage status does not support --all")
        print(json.dumps(usage_status(args.account), ensure_ascii=False))
        return 0
    if command == "recent":
        if args.action == "refresh":
            refresh_recent()
        print(json.dumps(read_json(STATE_ROOT / "recent" / "projects.json", {"schemaVersion": 1, "projects": []}), ensure_ascii=False))
        return 0
    if command == "sessions":
        if args.action == "open":
            if not args.session_id:
                die("sessions open requires a session or task id")
            print(json.dumps(open_session(args.session_id), ensure_ascii=False))
            return 0
        if args.action == "stop":
            if not args.session_id:
                die("sessions stop requires a session or task id")
            print(json.dumps(stop_session(args.session_id), ensure_ascii=False))
            return 0
        if args.action == "native":
            refresh_recent()
            print(json.dumps(read_json(
                STATE_ROOT / "recent" / "sessions.json",
                {"schemaVersion": 1, "sessions": []},
            ), ensure_ascii=False))
            return 0
        print(json.dumps({"schemaVersion": 1, "sessions": sessions_status(clean=True)}, ensure_ascii=False))
        return 0
    if command == "new-task":
        agent = args.agent or str(config["defaultAgent"])
        if args.mode == "prompt" and args.prompt:
            return run_prompt(
                agent, args.prompt, args.directory,
                profile_name=args.policy,
                confirm_full_access=args.confirm_full_access,
                write_scopes=args.scope,
            )
        print(launch_terminal(
            agent, args.directory, "interactive", args.prompt,
            profile_name=args.policy,
            confirm_full_access=args.confirm_full_access,
            write_scopes=args.scope,
        ))
        return 0
    if command == "submit":
        resolved_agent = str(config["defaultAgent"]) if args.agent == "auto" else args.agent
        directory = safe_directory(args.directory)
        task_id, _ = harness().submit(
            agent=resolved_agent,
            project=directory,
            prompt=args.prompt,
            mode="prompt",
            profile_name=args.policy,
            confirm_full_access=args.confirm_full_access,
            asynchronous=True,
        )
        print(json.dumps({
            "schemaVersion": 1,
            "taskId": task_id,
            "requestedAgent": args.agent,
            "agent": resolved_agent,
            "routeReason": "configured_default" if args.agent == "auto" else "explicit_agent",
            "state": harness().store.display_task(task_id)["state"],
        }, ensure_ascii=False))
        return 0
    if command == "multi":
        directory = safe_directory(args.directory)
        objective = args.objective.strip() or (
            "Coordinate a bounded repository inventory, implementation pass, validation, "
            "and independent review for the current project. Preserve existing behavior."
        )
        parent_id = harness().create_workflow(
            count=args.count,
            project=directory,
            objective=objective,
            profile_name=args.policy,
            confirm_full_access=args.confirm_full_access,
            write_scopes=args.scope,
        )
        harness().spawn_workflow_worker(parent_id)
        print(parent_id)
        return 0
    if command == "task":
        if args.action == "list":
            print(json.dumps({"schemaVersion": 1, "tasks": harness().list_tasks()}, ensure_ascii=False))
            return 0
        if args.action == "reconcile":
            print(json.dumps({"schemaVersion": 1, "results": harness().reconcile()}, ensure_ascii=False))
            return 0
        if not args.task_id:
            die(f"task {args.action} requires a task id")
        try:
            if args.action == "open":
                return open_task_in_zed(args.task_id)
            if args.action == "show":
                print(json.dumps(
                    harness().show_task(args.task_id), ensure_ascii=False,
                    indent=None if args.json else 2,
                ))
            elif args.action == "events":
                print(json.dumps({"schemaVersion": 1, "events": harness().store.display_events(args.task_id)}, ensure_ascii=False))
            elif args.action == "artifacts":
                print(json.dumps({"schemaVersion": 1, "artifacts": harness().store.artifacts_for_task(args.task_id)}, ensure_ascii=False))
            elif args.action == "cancel":
                harness().request_cancel(args.task_id)
                print(args.task_id)
            elif args.action == "retry":
                harness().retry(args.task_id)
                print(args.task_id)
            return 0
        except (KeyError, RuntimeError, StateTransitionError, ValueError) as error:
            die(str(error))
    if command == "approval":
        if args.action == "list":
            print(json.dumps({
                "schemaVersion": 1,
                "approvals": harness().store.list_display_approvals(limit=100),
            }, ensure_ascii=False))
            return 0
        if not args.approval_id:
            die(f"approval {args.action} requires an approval id")
        try:
            if args.action == "show":
                print(json.dumps(harness().store.display_approval(args.approval_id),
                                 ensure_ascii=False, indent=None if args.json else 2))
            else:
                print(json.dumps(harness().resolve_approval(
                    args.approval_id, approved=args.action == "approve"
                ), ensure_ascii=False))
            return 0
        except (KeyError, StateTransitionError, ValueError) as error:
            die(str(error))
    if command == "workflow":
        directory = safe_directory(args.directory)
        parent_id = harness().create_workflow(
            count=args.agents,
            project=directory,
            objective=args.objective,
            profile_name=args.policy,
            confirm_full_access=args.confirm_full_access,
            write_scopes=args.scope,
        )
        harness().spawn_workflow_worker(parent_id)
        print(parent_id)
        return 0
    if command == "delegate":
        try:
            decision = harness().delegation_decision(
                objective=args.objective, kind=args.kind
            )
            if args.action == "decide":
                print(json.dumps({"schemaVersion": 1, "decision": decision}, ensure_ascii=False))
                return 0
            directory = safe_directory(args.directory)
            parent_task_id = args.parent_task or os.environ.get("QUATTRO_TASK_ID")
            task_id, exit_code, report = harness().delegate_to_pi(
                project=directory,
                objective=args.objective,
                kind=args.kind,
                parent_task_id=parent_task_id,
            )
            print(json.dumps(report, ensure_ascii=False))
            return exit_code if task_id is not None else 0
        except (KeyError, PermissionError, ValueError, OSError) as error:
            die(str(error))
    if command == "collab":
        session_id = args.session or os.environ.get("QUATTRO_COORDINATION_SESSION_ID")
        try:
            if args.action == "status":
                value = harness().coordinator.status()
            elif args.action == "claim":
                if not session_id or not args.summary:
                    die("collab claim requires --summary inside a Quattro session")
                value = harness().coordinator.claim(
                    session_id, summary=args.summary, scopes=tuple(args.scope)
                )
            elif args.action == "depend":
                if not session_id or not args.target:
                    die("collab depend requires a peer session id")
                value = harness().coordinator.add_dependency(session_id, args.target)
            elif args.action == "integrate":
                if not session_id or not args.target:
                    die("collab integrate requires a completed source session id")
                value = harness().coordinator.integrate(
                    session_id, args.target, strategy=args.strategy
                )
            elif args.action == "cleanup":
                target = args.target or session_id
                if not target:
                    die("collab cleanup requires a session id")
                value = harness().coordinator.cleanup(target)
            else:
                target = args.target or session_id
                if not target:
                    die("collab recover requires a session id")
                value = harness().coordinator.get(target)
            print(json.dumps(value, ensure_ascii=False, indent=None if args.json else 2))
            return 0
        except (KeyError, LeaseConflict, OSError, RuntimeError, ValueError) as error:
            die(str(error))
    if command == "config":
        try:
            normalized = harness().config()
            if args.action == "migrate" and not args.dry_run:
                harness().persist_config(normalized)
            print(json.dumps({
                "schemaVersion": normalized["schemaVersion"],
                "defaultPolicyProfile": normalized["defaultPolicyProfile"],
                "fullAccessRequiresConfirmation": normalized["fullAccessRequiresConfirmation"],
                "written": bool(args.action == "migrate" and not args.dry_run),
            }, ensure_ascii=False))
            return 0
        except (ConfigError, OSError, ValueError) as error:
            die(str(error))
    if command == "workspace":
        try:
            resolution = resolve_project_destination(
                project_root=project_root_from_config(config),
                repository=args.repository,
                explicit_destination=args.destination,
                cwd=pathlib.Path.cwd(),
                operation=args.operation,
            )
            task_id = os.environ.get("QUATTRO_TASK_ID")
            if task_id:
                try:
                    harness().store.append_event(
                        task_id, "workspace.destination_resolved", run_id=None,
                        display={**resolution.to_dict(), "policy": "workspace.default_project_root"},
                    )
                except (KeyError, OSError, sqlite3.Error):
                    pass
            print(json.dumps({"schemaVersion": 1, **resolution.to_dict()}, ensure_ascii=False))
            return 0
        except (OSError, ValueError) as error:
            die(str(error))
    if command == "deployment":
        return handle_deployment(args)
    if command == "chatgpt":
        return launch_chatgpt()
    if command == "omniroute":
        return launch_omniroute()
    if command == "memory":
        if args.action in ("init", "status", "open", "open-projects"):
            return memory_command(args.action, args.json)
        return advanced_memory_command(args)
    if command == "retrieval":
        return retrieval_command(args)
    if command == "dictation":
        if args.action == "status":
            print(json.dumps(dictation_status(), ensure_ascii=False))
            return 0
        return dictation_toggle()
    if command == "crash":
        if args.action == "list":
            print(json.dumps({"schemaVersion": 1, "crashes": crash_rows()}, ensure_ascii=False))
            return 0
        pid = args.pid or (crash_rows(1)[0]["pid"] if crash_rows(1) else None)
        if pid is None:
            die("No crash is available to diagnose")
        return diagnose_crash(pid)
    if command == "pr-review":
        review_config = config.get("prReview", {})
        if not isinstance(review_config, dict):
            review_config = {}
        target = parse_target(args.target, args.pr)
        selected_account = args.account or str(review_config.get("codexAccount") or config["defaultCodexAccount"])
        memory_enabled, memory_vault, _ = memory_settings(config)
        project_vault = project_memory_path(config)
        options = ReviewOptions(
            runtime=str(review_config.get("runtime", "codex")),
            account=selected_account,
            mode=args.mode or str(review_config.get("reviewMode", "comment")),
            # Standalone/manual review never inherits a global mutation flag.
            # Unattended publication requires a future separately named,
            # repository-allowlisted automation entry point.
            publish=bool(args.publish),
            depth=args.depth or str(review_config.get("maximumDepth", "full")),
            run_tests=not args.no_tests and bool(review_config.get("runTests", True)),
            security_scan=not args.no_security_scan and bool(review_config.get("securityScanning", True)),
            comments=str(review_config.get("commentBehavior", "summary")),
            severity_threshold=args.severity_threshold or str(review_config.get("severityThreshold", "LOW")),
            model=args.model or review_config.get("model"),
            timeout_seconds=args.timeout or int(review_config.get("timeoutSeconds", 1800)),
            max_files=int(review_config.get("maxFiles", 500)),
            max_diff_bytes=int(review_config.get("maxDiffBytes", 5000000)),
            memory_vault=str(memory_vault) if memory_enabled else None,
            project_memory_vault=str(project_vault) if memory_enabled else None,
            memory_instructions=memory_policy(memory_vault, project_vault) if memory_enabled else None,
        )
        gh = command_path("gh")
        if not gh:
            die("GitHub CLI (gh) is required; install it and run 'gh auth login' using the intended GitHub account")
        expected_github_account = review_config.get("githubAccount")
        if not isinstance(expected_github_account, str) or not expected_github_account:
            expected_github_account = None
        review_task_id = harness().create_task(
            agent="codex",
            project=safe_directory(None),
            prompt=f"Review {target.slug}#{target.number}",
            mode="prompt",
            profile_name="publication-capable" if options.publish else "review-untrusted",
            account_id=selected_account,
            workflow="pr-review",
            title=f"PR review · {target.slug}#{target.number}",
        )
        review_run_id = harness().store.claim_task_for_run(
            review_task_id, agent="codex", account_id=selected_account
        )
        harness().store.transition_task(
            review_task_id, TaskState.RUNNING, expected=TaskState.READY
        )
        pending_effect: dict[str, str] = {}

        def review_process_started(pid: int) -> None:
            review_cancel_check()
            identity = read_process_identity(pid)
            harness().store.mark_run_started(
                review_run_id,
                pid=identity.pid,
                process_start_ticks=identity.start_ticks,
                process_group=identity.process_group,
                expected_executable=identity.expected_executable,
                deadline_at=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=options.timeout_seconds)).isoformat(),
            )

        def review_cancel_check() -> None:
            state = TaskState(harness().store.get_task(review_task_id)["state"])
            if state in {TaskState.CANCELLING, TaskState.CANCELLED, TaskState.INTERRUPTED}:
                raise ReviewError("PR review was cancelled before publication")

        def review_heartbeat() -> None:
            review_cancel_check()
            harness().store.heartbeat_run(review_run_id)

        def review_process_completed(exit_code: int) -> None:
            if RunState(harness().store.get_run(review_run_id)["state"]) is RunState.RUNNING:
                harness().store.transition_run(
                    review_run_id, RunState.SUCCEEDED, exit_code=exit_code
                )

        def review_before_publish(key: str, mode: str, reviewed_sha: str) -> None:
            review_cancel_check()
            effect = harness().store.record_external_effect_intent(
                review_task_id,
                run_id=review_run_id,
                idempotency_key=key,
                provider="github",
                effect_type=f"pr-review.{mode}",
                display_summary=f"Publish review for {target.slug}#{target.number} at {reviewed_sha[:12]}",
            )
            if effect.get("state") == "completed":
                pending_effect["reused"] = key
                harness().store.append_event(
                    review_task_id, "external_effect.reused", run_id=review_run_id,
                    display={"idempotencyKey": key, "provider": "github"},
                )
            elif effect.get("state") == "failed":
                harness().store.retry_external_effect(key)
                pending_effect["key"] = key
            else:
                pending_effect["key"] = key

        def review_after_publish(key: str, action: str) -> None:
            if pending_effect.get("reused") != key:
                harness().store.complete_external_effect(key, external_id=action)
            pending_effect.pop("key", None)
            pending_effect.pop("reused", None)

        options.on_process_started = review_process_started
        options.on_process_completed = review_process_completed
        options.cancellation_check = review_cancel_check
        options.heartbeat = review_heartbeat
        options.before_publish = review_before_publish
        options.after_publish = review_after_publish
        try:
            result = execute_review(target, options, GitHubClient(gh, expected_account=expected_github_account), require("codex"),
                                    codex_home(config, selected_account))
            review_cancel_check()
        except ReviewError as error:
            if pending_effect.get("key"):
                try:
                    harness().store.complete_external_effect(pending_effect["key"], failed=True)
                except (KeyError, StateTransitionError):
                    pass
            run_state = RunState(harness().store.get_run(review_run_id)["state"])
            if run_state in {RunState.CREATED, RunState.STARTING, RunState.RUNNING}:
                harness().store.transition_run(
                    review_run_id, RunState.FAILED, error_code="review_failed"
                )
            task_state = TaskState(harness().store.get_task(review_task_id)["state"])
            if task_state not in {TaskState.CANCELLED, TaskState.INTERRUPTED}:
                harness().store.transition_task(
                    review_task_id, TaskState.FAILED,
                    terminal_code="review_failed", terminal_summary=str(error)[:1000],
                )
            harness().write_projection()
            die(str(error))
        run_state = RunState(harness().store.get_run(review_run_id)["state"])
        if run_state is RunState.RUNNING:
            harness().store.transition_run(review_run_id, RunState.SUCCEEDED, exit_code=0)
        harness().store.append_event(
            review_task_id, "pr_review.completed",
            display={
                "status": result["status"],
                "findings": result["findings"],
                "reviewedHeadSha": result["reviewedHeadSha"],
                "published": result["published"],
            },
        )
        report_artifact = harness().artifact_root / f"{review_task_id}-review.md"
        report_artifact.write_text(result["markdown"][:1_000_000], encoding="utf-8")
        report_artifact.chmod(0o600)
        harness().store.add_artifact(
            review_task_id, run_id=review_run_id, kind="pr-review-report",
            path=report_artifact, display_name="PR review report", calculate_hash=True,
        )
        harness().store.transition_task(review_task_id, TaskState.VALIDATING_RESULT)
        harness().store.transition_task(
            review_task_id, TaskState.SUCCEEDED,
            terminal_code="review_completed",
            terminal_summary="Evidence-gated PR review completed.",
        )
        harness().write_projection()
        if args.output:
            output = expand_path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result["markdown"], encoding="utf-8")
        if args.json:
            print(json.dumps({key: result[key] for key in ("target", "published", "publicationMode", "status", "findings")}, ensure_ascii=False))
        else:
            print(result["markdown"])
            print(f"Execution: {result['target']} · {result['status']} · {result['findings']} findings · {'published' if result['published'] else 'not published'}")
        return 0
    if command == "state":
        print(json.dumps(dashboard(), ensure_ascii=False))
        return 0
    if command == "_session":
        return session_worker(args)
    if command == "_dictation-record":
        return dictation_worker(args.session_id, args.audio)
    if command == "_task-worker":
        return harness().run_terminal_worker(args.task_id)
    if command == "_workflow-worker":
        return harness().run_workflow(args.parent_task_id)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
