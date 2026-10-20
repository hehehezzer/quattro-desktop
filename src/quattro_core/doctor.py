"""Read-only operational observations, never configuration-as-connectivity claims."""
from __future__ import annotations

import json
import pathlib
import sqlite3
from contextlib import closing

from . import __version__
from .knowledge import KnowledgeService
from .config import safe_path


def diagnose(config, config_path, project=None, deep=False, backup_path=None, recovery_path=None):
    if project is not None:
        config.authorize(project)
    issues = []
    def issue(severity, component, reason, action):
        issues.append(dict(severity=severity, component=component, reason=reason, action=action))
    report = {"version":__version__, "configuration":str(config_path),
              "scope":[project] if project else list(config.projects), "active_project":project,
              "freshness_check":"content fingerprints" if deep else "not tested; use --deep",
              "system":{"status":"not_tested"}, "embeddings":{"status":"not_tested"},
              "retrieval":{"status":"not_tested"}, "memory":{"status":"not_tested"},
              "integrations":{}, "issues":issues}
    missing = [name for name in ("retrieval.sqlite3","memory.sqlite3") if not (config.database_dir/name).is_file()]
    if missing:
        issue("error","database","Required storage is unavailable","Restore a verified backup into a new directory or initialize/index an authorized source")
        report["system"] = {"status":"unavailable","missing":missing}
        report["status"] = "unavailable"
        return report
    try:
        for name, required in (("retrieval.sqlite3", {"knowledge_sources","knowledge_files","knowledge_documents","knowledge_scope",
                               "documents","documents_scope","documents_symbol","documents_validity","documents_fts",
                               "retrieval_meta","indexed_files","graph_edges","query_cache","retrieval_runs"}),
                               ("memory.sqlite3", {"memories","memory_events","memory_fts","memory_scope","memory_fact"})):
            with closing(sqlite3.connect(safe_path(config.database_dir/name).as_uri() + "?mode=ro",uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
                if not required.issubset(tables):
                    raise ValueError("uninitialized schema; read-only diagnostics do not migrate")
                if name == "retrieval.sqlite3" and db.execute("SELECT value FROM retrieval_meta WHERE key='index_version'").fetchone() != ("3",):
                    raise ValueError("schema migration required")
                if name == "memory.sqlite3" and db.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValueError("schema migration required")
        with closing(KnowledgeService(config, read_only=True)) as service:
            health = service.health()
            sources = service.get_index_status(project, deep=deep)
            report["sources"] = sources
            report["system"] = {"status":"healthy" if health["database"] == health["memory_database"] == "ok" else "unavailable",
                                "database":health["database"],"memory_database":health["memory_database"]}
            backend = service.store.embedding_backend
            semantic = health["semantic"]
            report["embeddings"] = {"status":"healthy" if semantic["available"] else "not_configured" if config.embedding == "lexical" else "unavailable",
                                    "configured_model":backend.model_id,"expected_dimensions":backend.dimensions,
                                    "observed_dimensions":getattr(backend,"observed_dimensions",None),
                                    "observed_model":getattr(backend,"observed_model",None),
                                    "endpoint":getattr(backend,"endpoint",None),"reason":semantic["reason"]}
            if config.embedding == "local-neural" and not semantic["available"]:
                issue("error","embeddings","Local embedding request failed or returned incompatible dimensions",
                      "Inspect http://127.0.0.1:20218/v1/models and quattro-embeddings.service; lexical evidence remains labeled")
            scope_projects = [project] if project else list(config.projects)
            placeholders = ",".join("?" for _ in scope_projects)
            source_ids = [s["source_id"] for s in sources["sources"] if s["status"] != "excluded"]
            source_clause = " AND k.source_id IN (" + ",".join("?" for _ in source_ids) + ")" if source_ids else " AND 0"
            scope_parameters = [*scope_projects, *source_ids]
            scope_sql = f"k.project IN ({placeholders})" + source_clause
            keyword = service.connection.execute(f"""SELECT count(*) FROM documents_fts f
                JOIN knowledge_documents k ON k.document_id=f.id WHERE documents_fts MATCH ?
                AND {scope_sql}""", ['"health"', *scope_parameters]).fetchone()[0]
            compatible = service.connection.execute(f"""SELECT count(*) FROM documents d
                JOIN knowledge_documents k ON k.document_id=d.id WHERE d.embedding_model=? AND length(d.embedding)=?
                AND d.valid_until IS NULL AND d.superseded_by IS NULL AND {scope_sql}""",
                (backend.model_id,backend.dimensions * 4,*scope_parameters)).fetchone()[0] if backend.dimensions else 0
            total = service.connection.execute(f"""SELECT count(*) FROM documents d JOIN knowledge_documents k ON k.document_id=d.id
                WHERE d.valid_until IS NULL AND d.superseded_by IS NULL AND {scope_sql}""",scope_parameters).fetchone()[0]
            missing_fts = service.connection.execute(f"""SELECT count(*) FROM documents d JOIN knowledge_documents k ON k.document_id=d.id
                LEFT JOIN documents_fts f ON f.id=d.id WHERE f.id IS NULL AND {scope_sql}""",scope_parameters).fetchone()[0]
            semantic_state = "healthy" if semantic["available"] and compatible == total and total else "degraded" if semantic["available"] and compatible else "unavailable"
            report["retrieval"] = {"keyword":"healthy" if not missing_fts else "degraded", "semantic":semantic_state,
                                   "hybrid":"healthy" if semantic_state == "healthy" and not missing_fts else "degraded",
                                   "compatible_vectors":compatible,"eligible_documents":total,
                                   "missing_fts_records":missing_fts,"keyword_probe_matches":keyword}
            if config.embedding == "local-neural" and semantic["available"] and compatible < total:
                issue("warning","index","Semantic vector coverage is incomplete in resolved scope",
                      "Inspect sources and explicitly run index SOURCE --reindex after reviewing the dry-run")
            if missing_fts:
                issue("warning","keyword","Scoped documents are missing lexical entries","Explicitly reindex affected authorized sources; preserve a backup first")
            broken = service.connection.execute(f"""SELECT count(*) FROM knowledge_documents k
                LEFT JOIN documents d ON d.id=k.document_id LEFT JOIN knowledge_sources s ON s.source_id=k.source_id AND s.project=k.project
                WHERE (d.id IS NULL OR s.source_id IS NULL) AND {scope_sql}""", scope_parameters).fetchone()[0]
            report["system"]["broken_source_references"] = broken
            if broken:
                issue("error","index","Broken source/document mappings detected","Restore a verified snapshot or explicitly reconcile affected sources")
            report["memory"] = {"status":"healthy" if health["memory_database"] == "ok" else "unavailable",
                                "integrity":health["memory_database"],"backup_availability":"not_tested",
                                "last_verified_recovery":"not_tested"}
            if backup_path is not None:
                from .recovery import verify_backup
                try:
                    manifest = verify_backup(config, backup_path)
                    report["memory"].update(backup_availability="verified",last_backup_at=manifest["created_at"])
                except (OSError, ValueError, KeyError, sqlite3.Error, PermissionError):
                    report["memory"]["backup_availability"] = "unavailable"
                    issue("error","backup","Backup validation failed","Inspect manifest, checksums, schema and project authority; keep the original live store")
            if recovery_path is not None:
                from .recovery import integrity, _authorize_snapshot, DATABASES
                try:
                    directory = safe_path(recovery_path, directory=True)
                    marker = safe_path(directory / "recovery-verified.json")
                    if marker.stat().st_size > 128000:
                        raise ValueError("oversized recovery marker")
                    recovery = json.loads(marker.read_text())
                    names = [n for n in DATABASES if (directory/n).is_file()]
                    for name in names:
                        integrity(safe_path(directory/name))
                    _authorize_snapshot(config, directory, names)
                    if recovery.get("integrity") != "ok" or not all(n in names for n in DATABASES[:2]):
                        raise ValueError("recovery proof unavailable")
                    report["memory"]["last_verified_recovery"] = recovery["verified_at"]
                except (OSError, ValueError, KeyError, sqlite3.Error, PermissionError):
                    issue("error","recovery","Recovery proof is unavailable or invalid","Rerun restore into a new isolated directory and verify application retrieval and memory history")
            for source in sources["sources"]:
                if source["status"] not in {"indexed","excluded"}:
                    issue("info" if source["classification"] == "requires_scope_decision" else "warning", "source:" + source["source_id"],
                          source["reason"] or "Source has never successfully indexed; registration is not coverage", source["remediation"])
    except (sqlite3.Error, OSError, ValueError) as error:
        report["system"] = {"status":"unavailable","error_type":type(error).__name__}
        issue("error","database","Storage or schema could not be inspected","Check file permissions and schema compatibility; do not rebuild or overwrite live data")
    receipt_path = safe_path(config.database_dir / "native-receipts.sqlite3")
    for host in ("omp","codex"):
        configured = (pathlib.Path(config_path).parent / "clients" / (host + ".json")).is_file()
        state = {"configuration":"present" if configured else "not_configured","connection":"not_tested",
                 "retrieval":"not_tested","delivery":"not_tested","citation":"not_observed",
                 "last_confirmed_delivery":{"status":"not_observed","receipt_window":100}}
        if receipt_path.is_file():
            try:
                with closing(sqlite3.connect(receipt_path.as_uri() + "?mode=ro",uri=True)) as db:
                    db.row_factory = sqlite3.Row
                    rows = db.execute("SELECT * FROM native_receipts WHERE host=? ORDER BY created_at DESC,rowid DESC LIMIT 100",(host,))
                    for row in rows:
                        meta = json.loads(row["metadata_json"])
                        from .receipts import scope_allowed
                        scope = meta.get("authorized_scope", [row["project"]] if row["project"] else [])
                        if not scope_allowed(config,row["project"],meta) or project and project not in scope:
                            continue
                        if state["connection"] != "observed_request":
                            state.update(connection="observed_request",latest_request_at=row["created_at"],
                                         retrieval=row["status"],delivery=row["delivery"],latest_receipt=row["id"],
                                         client_accepted="not_observed",last_end_to_end_check="not_observed")
                        if row["delivery"] == "confirmed":
                            state["last_confirmed_delivery"] = {"status":"observed","receipt_id":row["id"],
                                "at":row["delivered_at"],"boundary":row["boundary"],"receipt_window":100}
                            break
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                state.update(connection="unavailable",delivery="not_tested")
                issue("warning",host+":receipts","Receipt storage could not be inspected",
                      "Check receipt database integrity or recover its verified snapshot; no delivery success is inferred")
        report["integrations"][host] = state
    report["status"] = ("unavailable" if report["system"]["status"] == "unavailable" else
                        "degraded" if issues or report["retrieval"].get("hybrid") == "degraded" else "healthy")
    return report


def render(report, details=False):
    lines = [f"Quattro {report['version']}: {report['status']}",
             "Scope: " + ", ".join(report["scope"]), "Database: " + report["system"]["status"],
             "Embeddings: " + report["embeddings"]["status"], "Freshness: " + report["freshness_check"]]
    if "sources" in report:
        lines.append("Sources: " + ", ".join(f"{k}={v}" for k,v in report["sources"]["counts"].items()))
    for host,state in report["integrations"].items():
        confirmed_at = state["last_confirmed_delivery"].get("at","not_observed_in_recent_receipts")
        lines.append(f"{host}: configuration={state['configuration']}; connection={state['connection']}; retrieval={state['retrieval']}; delivery={state['delivery']}; last_confirmed={confirmed_at}; citation={state['citation']}")
    for problem in report["issues"]:
        if details or problem["severity"] != "info":
            lines.append(f"[{problem['severity']}] {problem['component']}: {problem['reason']}. Action: {problem['action']}")
    hidden = sum(p["severity"] == "info" for p in report["issues"])
    if hidden and not details:
        lines.append(f"{hidden} scope decisions pending. Use --details or --json for source-level remediation.")
    return "\n".join(lines)
