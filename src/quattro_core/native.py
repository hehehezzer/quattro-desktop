"""Native-client retrieval and content-free receipts; never agent execution policy."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time
from contextlib import closing

from .config import Config, default_config_path, safe_path
from .mcp import McpRuntime, TOOLS, TOOL_MAP, strict_json
from .retrieval import redact
from .receipts import Receipts, source_scope

MAX_INPUT = 65536
HOSTS = ("omp", "codex")




def project_for(config: Config, cwd: str):
    root = safe_path(pathlib.Path(cwd), directory=True)
    candidates = [source for source in config.sources if source.project != "shared" and root.is_relative_to(source.root)]
    if not candidates:
        return None
    return max(candidates, key=lambda source: len(source.root.parts)).project


def source_status(runtime, projects):
    """Observe coverage without doing unbounded indexing inside a native prompt hook."""
    statuses = []
    for project in projects:
        for source in runtime.service.get_index_status(project)["sources"]:
            statuses.append({**{key:source[key] for key in ("source_id","project","indexed_at","last_failure","files","documents","status","freshness")},
                             "refresh_needed":source["status"] in {"pending","stale","failed"}})
    return statuses


def summary(receipt):
    semantics = receipt.get("semantic", {})
    mode = "semantic not assessed"
    if "available" in semantics:
        mode = "semantic+lexical" if semantics["available"] else "lexical fallback"
    scope = receipt.get("project") or "shared-only (cwd unregistered)"
    sources = receipt.get("sources", [])
    coverage = "coverage not assessed"
    if sources:
        coverage = "index refresh required" if any(source["last_failure"] or source.get("refresh_needed") for source in sources) else "indexed snapshots; full freshness not assessed"
    return f"Quattro {receipt['id']}: {receipt['status']}; {mode}; scope {scope}; {coverage}; {receipt.get('result_count',0)} evidence/memories; context delivery unverified."


def evidence_metadata(result):
    contexts = result.get("projects", [result])
    evidence = []
    for context in contexts:
        for item in context.get("knowledge", context.get("results", [])):
            citation = item.get("citation", {})
            evidence.append({"id":item["id"],"project":citation.get("project"),
                             "source_id":citation.get("source_id"),"revision":citation.get("file_hash"),
                             "freshness":citation.get("provenance")})
        for memory in context.get("memories", []):
            evidence.append({"id":memory["id"],"revision":memory.get("updated_at"),
                             "verification":memory.get("verification")})
    return {"selected_results":evidence[:100],
            "context_bytes":len(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()),
            "strategy":"hybrid","citation_observed":False}


def execute(config: Config, host: str, action: str, request: dict):
    if host not in HOSTS or not isinstance(request, dict):
        raise ValueError("invalid native request")
    request.pop("_quattro_request", None)
    with closing(Receipts(config)) as receipts:
        if action == "status":
            return receipts.recent(host, request)
        if action in {"delivered", "submitted", "delivery_failed"}:
            return receipts.delivered(host, request, {"delivered":"confirmed","submitted":"submitted","delivery_failed":"failed"}[action])
        if action == "tools":
            return {"tools":TOOLS,"projects":list(config.projects)}
        cwd = request.get("cwd")
        if not isinstance(cwd, str):
            raise ValueError("cwd is required")
        project = project_for(config, cwd)
        started = time.monotonic()
        arguments = request.get("arguments", {}) if action == "call" else {}
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        operation = request.get("name") if action == "call" else action
        if action == "call" and operation not in TOOL_MAP:
            raise ValueError("unknown native tool")
        target = config.source(arguments.get("source_id")).project if operation == "index_source" else arguments.get("project",project)
        if target is not None:
            config.authorize(target)
        scope = ([target] if target else []) + (["shared"] if action == "context" and "shared" in config.projects else [])
        resolved_sources = list(dict.fromkeys(s for p in scope for s in source_scope(config,operation,p,arguments)))
        attempt = receipts.record(host,request,target,operation,"attempted",{
            "authorized_scope":scope,"authorized_sources":resolved_sources,
            "result_count":0})
        request["_quattro_request"] = {"id":attempt["id"],"project":target,"scope":scope,"sources":resolved_sources}
        with closing(McpRuntime(config)) as runtime:
            if action == "call":
                name = request.get("name")
                arguments = request.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
                arguments = dict(arguments)
                if name != "index_source" and "project" not in arguments:
                    if project is None:
                        raise PermissionError("working directory is not registered; specify an authorized project")
                    arguments["project"] = project
                selected = config.source(arguments.get("source_id")).project if name == "index_source" else arguments.get("project", project)
                result = runtime.call(name, arguments)
                semantic = result.get("semantic", {}) if isinstance(result, dict) else {}
                count = (len(result.get("results",result.get("knowledge",[]))) + len(result.get("memories",[]))) if isinstance(result, dict) else 0
                receipt = receipts.record(host,request,selected,name,"ready",{
                    "semantic":semantic,"result_count":count,"latency_ms":round((time.monotonic()-started)*1000,2),
                    **(evidence_metadata(result) if isinstance(result, dict) else {}),
                    "authorized_scope":[selected] if selected else [],
                    "request_id":attempt["id"],
                    "authorized_sources":resolved_sources,
                    "strategy":arguments.get("strategy","hybrid")})
                return {"status":"ready","project":selected,"result":result,"receipt":receipt,"summary":summary(receipt)}
            if action != "context":
                raise ValueError("unsupported native operation")
            query = request.get("query", "")
            if not isinstance(query,str) or len(query)>2000 or not query.strip():
                raise ValueError("query must contain 1 to 2000 characters")
            query = redact(query)[0]
            projects = ([project] if project else []) + (["shared"] if "shared" in config.projects else [])
            if not projects:
                receipt = receipts.record(host,request,None,"context","unregistered",{"semantic":{"available":False,"reason":"working directory is not registered"},"result_count":0})
                return {"status":"unregistered","project":None,"context":None,"receipt":receipt,"summary":summary(receipt)}
            sources = source_status(runtime,projects)
            contexts = []
            for name in projects:
                contexts.append(runtime.call("get_project_context",{"project":name,"query":query,"limit":6,"budget":9000 if name==project else 3000}))
            available = bool(contexts) and all(c["semantic"].get("available") for c in contexts)
            semantic = {"available":available,"backend":runtime.service.store.embedding_backend.model_id,
                        "reason":None if available else next((c["semantic"].get("reason") for c in contexts if not c["semantic"].get("available")),"unavailable")}
            count = sum(len(c["knowledge"])+len(c["memories"]) for c in contexts)
            metadata = {"semantic":semantic,"result_count":count,"sources":sources,"project_registered":project is not None,
                        "latency_ms":round((time.monotonic()-started)*1000,2),"model_reliance":"unknown",
                        "request_id":attempt["id"],
                        "authorized_scope":projects,"authorized_sources":resolved_sources,**evidence_metadata({"projects":contexts})}
            receipt = receipts.record(host,request,project,"context","ready",metadata)
            return {"status":"ready","project":project,"context":{"projects":contexts,"sources":sources,"untrusted":True},"receipt":receipt,"summary":summary(receipt)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Native Quattro context and content-free usage receipts; no model routing")
    parser.add_argument("--config",type=pathlib.Path,default=default_config_path())
    parser.add_argument("--host",choices=HOSTS,required=True)
    parser.add_argument("--session",help="Filter status to a native session ID")
    parser.add_argument("action",choices=("context","call","delivered","submitted","delivery_failed","status","tools"))
    args = parser.parse_args(argv)
    config = None
    request = {}
    try:
        raw = b"" if sys.stdin.isatty() and args.action in {"status","tools"} else sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT:
            raise ValueError("native input exceeds limit")
        request = strict_json(raw) if raw.strip() else {}
        if args.session is not None:
            request["session_id"] = args.session
        config = Config.load(args.config)
        result = execute(config,args.host,args.action,request)
    except Exception as error:
        result = {"status":"unavailable","error":type(error).__name__,"summary":"Quattro intelligence unavailable; no retrieval or delivery success claimed."}
        if config is not None and isinstance(request, dict) and args.action in {"context", "call"}:
            try:
                with closing(Receipts(config)) as receipts:
                    trace = request.get("_quattro_request", {})
                    result["receipt"] = receipts.record(args.host,request,trace.get("project"),args.action,"unavailable",
                        {"semantic":{"available":False,"reason":"native operation failed"},"result_count":0,
                         "request_id":trace.get("id"),"authorized_scope":trace.get("scope",[]),
                         "authorized_sources":trace.get("sources",[]),"error_type":type(error).__name__})
            except (ValueError, OSError, sqlite3.Error):
                # An invalid identity or inaccessible receipt store cannot become a success.
                result["receipt_unavailable"] = True
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result.get("status") != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
