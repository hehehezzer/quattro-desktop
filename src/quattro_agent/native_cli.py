"""On-demand native intelligence status, trace, and diagnostic probe commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import uuid
import tomllib
from typing import Any

from .native_intelligence import (
    NativeContext, NativeTelemetry, credential_status, host_version,
    load_native_settings, native_jev_advice, native_telemetry_path,
    write_native_settings,
)
from .shared_intelligence import rtk_status, search_knowledge
from .paths import xdg_config_home


_ACCOUNT_NAME = re.compile(r"account-[1-9][0-9]*$")


def _codex_homes() -> list[Path]:
    home = Path.home()
    paths = []
    configured = os.environ.get("CODEX_HOME")
    if configured:
        paths.append(Path(os.path.expandvars(os.path.expanduser(configured))).resolve())
    paths.append(home / ".codex")
    accounts = home / ".local/share/quattro-ai/codex/accounts"
    if accounts.is_dir():
        paths.extend(path for path in sorted(accounts.iterdir())
                     if path.is_dir() and _ACCOUNT_NAME.fullmatch(path.name))
    result = []
    for path in paths:
        path = path.resolve(strict=False)
        if path not in result:
            result.append(path)
    return result


def _codex_registration() -> list[dict[str, Any]]:
    result = []
    for home in _codex_homes():
        path = home / "config.toml"
        row: dict[str, Any] = {"home": str(home), "config": path.is_file(),
                               "registered": False, "operationalDecision": "missing"}
        if path.is_file() and not path.is_symlink():
            try:
                value = tomllib.loads(path.read_text(encoding="utf-8"))
                server = value.get("mcp_servers", {}).get("quattro_intelligence", {})
                if isinstance(server, dict):
                    row["registered"] = True
                    tools = server.get("tools", {})
                    operation = tools.get("operational_decision") if isinstance(tools, dict) else None
                    row["operationalDecision"] = (
                        operation.get("approval_mode", "configured")
                        if isinstance(operation, dict) else "missing"
                    )
                    row["sharedTools"] = sorted(tools) if isinstance(tools, dict) else []
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                row["config"] = "malformed"
        result.append(row)
    return result


def _pi_registration() -> dict[str, Any]:
    configured = os.environ.get("PI_CODING_AGENT_DIR")
    root = (Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
            if configured else Path.home() / ".pi/agent")
    extension = root / "extensions/quattro-intelligence.ts"
    return {"agentDir": str(root), "extension": str(extension),
            "installed": extension.is_file() and not extension.is_symlink(),
            "supportedGlobalPath": True}


def _counts(rows: list[dict[str, Any]], *, kind: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("kind") == kind:
            key = f"{row.get('stage')}:{row.get('status')}"
            counts[key] = counts.get(key, 0) + int(row.get("count", 1) or 1)
    return counts


def _last(rows: list[dict[str, Any]], *, kind: str) -> dict[str, Any] | None:
    matching = [row for row in rows if row.get("kind") == kind]
    return matching[-1] if matching else None


def native_status() -> dict[str, Any]:
    """Passive status. No Jev, retrieval, index, or RTK command is called."""
    try:
        settings = load_native_settings()
        config_error = None
    except Exception as error:
        settings = None
        config_error = type(error).__name__
    telemetry = NativeTelemetry(enabled=True)
    ordinary = telemetry.lifetime(include_diagnostics=False)
    diagnostics = telemetry.lifetime(diagnostics_only=True)
    sessions = telemetry.sessions(include_diagnostics=False)
    jev_counts = _counts(ordinary, kind="jev")
    retrieval_counts = _counts(ordinary, kind="retrieval")
    rtk_counts = _counts(ordinary, kind="rtk")
    has_jev_request = any(key.startswith("requested:") for key in jev_counts)
    accepted = sum(value for key, value in jev_counts.items() if key.startswith("accepted:"))
    retrieval_results = sum(value for key, value in retrieval_counts.items()
                            if key.startswith("result_returned:"))
    rtk_executions = sum(value for key, value in rtk_counts.items()
                         if key.startswith("executed:"))
    return {
        "schemaVersion": 1,
        "passive": True,
        "native": {
            "configPath": str(settings.path) if settings else str(xdg_config_home() / "quattro/native-intelligence.json"),
            "configured": bool(settings and settings.configured),
            "enabled": settings.enabled if settings else False,
            "categories": list(settings.categories) if settings else [],
            "timeoutMs": settings.timeout_ms if settings else None,
            "credential": credential_status(),
            "fallbackCondition": config_error or ("missing_credential" if credential_status() == "missing" else None),
        },
        "hosts": {
            "codex": {"executable": shutil.which("codex"), "version": host_version("codex"),
                      "mcp": _codex_registration(),
                      "lifecycle": "unsupported_in_installed_codex; MCP tool boundary used"},
            "pi": {"executable": shutil.which("pi"), "version": host_version("pi"),
                   "extension": _pi_registration(),
                   "lifecycle": "supported_session_and_before_agent_start"},
        },
        "usage": {
            "scope": "ordinary_native_sessions_only",
            "jev": {"enabledButNotCalled": bool(settings and settings.enabled and not has_jev_request),
                    "called": has_jev_request, "adviceAccepted": accepted,
                    "counts": jev_counts},
            "rag": {"loadedOrRegistered": any(row.get("registered") is True for row in _codex_registration()) or _pi_registration()["installed"],
                    "queried": bool(any(key.startswith("retrieval_requested:") for key in retrieval_counts)),
                    "zeroResultOrSkipped": retrieval_results == 0 and bool(retrieval_counts),
                    "resultsReturned": retrieval_results, "counts": retrieval_counts},
            "rtk": {"installed": shutil.which("rtk") is not None,
                    "statusChecks": sum(value for key, value in rtk_counts.items() if key.startswith("status_checked:")),
                    "actualExecutions": rtk_executions, "counts": rtk_counts},
        },
        "sessions": sessions,
        "lifetime": ordinary,
        "diagnosticLifetime": diagnostics,
        "telemetry": {"path": str(native_telemetry_path()), "exists": telemetry.exists(),
                       "degraded": telemetry.last_error is not None,
                       "retention": f"{30} days / {5000} events maximum"},
        "authority": {
            "nativeModelAccountPermissionsUnchanged": True,
            "jevCanAuthorize": False,
            "sharedIntelligenceIsNotQuattroModelRouting": True,
        },
    }


def native_trace(session_id: str, *, limit: int = 100,
                 include_diagnostics: bool = False) -> dict[str, Any]:
    telemetry = NativeTelemetry(enabled=True)
    return {"schemaVersion": 1, "sessionId": session_id,
            "events": telemetry.trace(session_id, limit=limit,
                                       include_diagnostics=include_diagnostics),
            "diagnosticsIncluded": include_diagnostics,
            "note": "Delivery/application is UNKNOWN or UNVERIFIED unless a native host boundary recorded it; model reliance is never inferred."}


def native_probe(directory: str | None, query: str | None) -> dict[str, Any]:
    """Explicit diagnostic activity, kept out of ordinary counters."""
    root = str(Path(directory or os.getcwd()).expanduser().resolve())
    session_id = "probe-" + uuid.uuid4().hex[:16]
    context = NativeContext(host="probe", session_id=session_id, project=root, diagnostic=True)
    telemetry = NativeTelemetry(enabled=True)
    request = {
        "decision_type": "context_strategy",
        "available_actions": ["inspect", "retrieve", "sufficient", "agent"],
        "relevant_context": {
            "repository_required": True, "modification_required": False,
            "retrieval_required": True, "multi_step_required": True,
            "verification_required": False, "context_missing": True,
            "independent_steps": False, "tests_available": False,
            "changes_present": False,
        },
        "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                              "retrieval_allowed": True},
        "execution_state": {"revision": 0, "phase": "inspection", "attempt": 0},
        "previous_result": "none",
    }
    jev = native_jev_advice(request, context=context, telemetry=telemetry)
    retrieval = search_knowledge(query or "native intelligence diagnostic retrieval probe",
                                 directory=root, budget=2_000, limit=3,
                                 telemetry_context=context)
    rtk = rtk_status(telemetry_context=context)
    return {
        "schemaVersion": 1, "diagnostic": True, "excludedFromOrdinaryUse": True,
        "sessionId": session_id,
        "jev": {key: jev.get(key) for key in ("selected_action", "confidence", "evidence", "fallback_required", "traceId", "usageEvidence")},
        "retrieval": {key: retrieval.get(key) for key in ("route", "retrievedTokens", "memory", "episodic", "indexPartial", "usageEvidence")},
        "rtk": {key: rtk.get(key) for key in ("available", "version", "reason", "usageEvidence")},
    }


def native_command(args: Any) -> int:
    if args.action == "status":
        value = native_status()
    elif args.action == "trace":
        if not args.session:
            raise ValueError("native trace requires --session; status lists every session and never guesses the latest")
        value = native_trace(args.session, limit=args.limit,
                             include_diagnostics=args.include_diagnostics)
    elif args.action == "probe":
        value = native_probe(args.directory, args.query)
    elif args.action == "set":
        if args.jev is None:
            raise ValueError("native set requires --jev on|off")
        settings = write_native_settings(enabled=args.jev == "on")
        value = {"schemaVersion": 1, "nativeJevEnabled": settings.enabled,
                 "configPath": str(settings.path), "managedRoutingUnchanged": True}
    else:
        raise ValueError(f"unsupported native action: {args.action}")
    print(json.dumps(value, ensure_ascii=False, indent=None if args.json else 2))
    return 0
