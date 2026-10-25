"""Operator-scoped relevance annotations; never verification or ranking authority."""
from __future__ import annotations

import json

from .errors import InvalidRequestError, PermissionDeniedError
from .retrieval import utc_now

LABELS = {"relevant", "irrelevant", "outdated", "wrong_project"}


def record(service, project, result_id, label):
    service.config.authorize(project, write=True)
    if label not in LABELS:
        raise InvalidRequestError("unsupported relevance label")
    row = service.connection.execute("SELECT k.source_id,k.file_hash FROM knowledge_documents k WHERE k.document_id=? AND k.project=?",(result_id,project)).fetchone()
    if row is None or not any(s.id == row["source_id"] and s.intent != "excluded" for s in service._sources(project)):
        raise PermissionDeniedError("result not in authorized source scope")
    with service.connection:
        service.connection.execute("""CREATE TABLE IF NOT EXISTS relevance_feedback(
            project TEXT NOT NULL, result_id TEXT NOT NULL, principal TEXT NOT NULL,
            label TEXT NOT NULL, source_id TEXT NOT NULL, file_hash TEXT NOT NULL, recorded_at TEXT NOT NULL,
            PRIMARY KEY(project,result_id,principal))""")
        service.connection.execute("INSERT OR REPLACE INTO relevance_feedback VALUES(?,?,?,?,?,?,?)",
            (project,result_id,service.config.principal,label,row["source_id"],row["file_hash"],utc_now()))
    return {"project":project,"result_id":result_id,"label":label,"principal":service.config.principal,
            "source_revision":row["file_hash"],"effect":"diagnostic_only; no ranking or verification change"}


def export(service, project):
    service.config.authorize(project)
    if not service.connection.execute("SELECT 1 FROM sqlite_master WHERE name='relevance_feedback'").fetchone():
        return {"feedback":[]}
    sources = [s.id for s in service._sources(project) if s.intent != "excluded"]
    if not sources:
        return {"feedback":[]}
    placeholders = ",".join("?" for _ in sources)
    rows = service.connection.execute(f"""SELECT * FROM relevance_feedback
        WHERE project=? AND principal=? AND source_id IN ({placeholders}) ORDER BY recorded_at DESC LIMIT 1000""",
        (project,service.config.principal,*sources))
    return {"feedback":[dict(row) for row in rows],"effect":"evaluation inputs only"}
