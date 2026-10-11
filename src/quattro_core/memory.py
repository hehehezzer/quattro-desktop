"""Transactional, namespace-isolated memory with explicit verification and lineage."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import uuid
from typing import Any

from .config import identifier, safe_path
from .retrieval import QUERY_STOPWORDS, private_database, redact

CATEGORIES = {"episodic", "semantic", "procedural", "shared"}
VERIFICATIONS = {"unverified", "verified", "disputed"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def clean_json(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("memory metadata must be valid JSON") from error
    if len(encoded.encode()) > 32_000 or redact(encoded)[1]:
        raise ValueError("memory contains oversized or credential-shaped data")
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and redact(item)[1]:
            raise ValueError("memory contains credential-shaped data")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return encoded


def validate(record: dict[str, Any]) -> None:
    identifier(record["project"])
    identifier(record["author"])
    if record["category"] not in CATEGORIES or record["verification"] not in VERIFICATIONS:
        raise ValueError("invalid memory category or verification")
    content = record["content"]
    if not isinstance(content, str) or not content.strip() or len(content.encode()) > 24_000:
        raise ValueError("memory content must contain 1 to 24000 UTF-8 bytes")
    if record["visibility"] not in {"project", "private"}:
        raise ValueError("invalid memory visibility")
    confidence = record["confidence"]
    if type(confidence) not in {int, float} or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid memory confidence")
    for field in ("references", "tags"):
        values = record[field]
        if not isinstance(values, list) or len(values) > 50 or any(not isinstance(v, str) or len(v) > 1000 for v in values):
            raise ValueError("invalid memory references or tags")
    if record["verification"] == "verified" and not record["references"]:
        raise ValueError("verified memory requires source references")
    if not isinstance(record["metadata"], dict):
        raise ValueError("memory metadata must be an object")
    if record["fact_key"] is not None:
        identifier(record["fact_key"])
    clean_json(record)


def digest(content: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", content).strip().casefold().encode()).hexdigest()


class MemoryStore:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = safe_path(path)
        private_database(self.path)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("unsupported memory schema; database was preserved")
            if version == 0:
                tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables:
                    raise ValueError("unrecognized memory database; import explicitly without overwriting")
                schema = """
                CREATE TABLE memories(
                  id TEXT PRIMARY KEY, project TEXT NOT NULL, category TEXT NOT NULL,
                  content TEXT NOT NULL, content_hash TEXT NOT NULL, author TEXT NOT NULL,
                  references_json TEXT NOT NULL, confidence REAL NOT NULL,
                  verification TEXT NOT NULL, tags_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                  visibility TEXT NOT NULL, fact_key TEXT, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                  state TEXT NOT NULL DEFAULT 'active', invalidation_reason TEXT,
                  superseded_by TEXT REFERENCES memories(id) ON DELETE SET NULL
                );
                CREATE INDEX memory_scope ON memories(project,state,visibility,author);
                CREATE INDEX memory_fact ON memories(project,fact_key,state);
                CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED,content,tags,metadata);
                CREATE TABLE memory_events(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
                  project TEXT NOT NULL, operation TEXT NOT NULL, actor TEXT NOT NULL,
                  occurred_at TEXT NOT NULL, snapshot_json TEXT NOT NULL
                );
                PRAGMA user_version=1;
                """
                for statement in schema.split(";"):
                    if statement.strip():
                        self.connection.execute(statement)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            self.close()
            raise
        os.chmod(path, 0o600)

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _projection(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for field in ("references", "tags", "metadata"):
            value[field] = json.loads(value.pop(field + "_json"))
        value.pop("content_hash", None)
        value["untrusted"] = True
        return value

    def _get(self, project: str, memory_id: str, principal: str) -> dict[str, Any]:
        identifier(project)
        identifier(principal)
        row = self.connection.execute(
            "SELECT * FROM memories WHERE id=? AND project=? AND (visibility='project' OR author=?)",
            (memory_id, project, principal)).fetchone()
        if row is None:
            raise KeyError("memory not found in authorized namespace")
        return self._projection(row)

    def get(self, project: str, id: str, principal: str = "local") -> dict[str, Any]:
        return self._get(project, id, principal)

    def _event(self, record: dict[str, Any], operation: str, actor: str) -> None:
        self.connection.execute("INSERT INTO memory_events(memory_id,project,operation,actor,occurred_at,snapshot_json) VALUES(?,?,?,?,?,?)",
                                (record["id"], record["project"], operation, actor, now(), clean_json(record)))

    def _fts(self, record: dict[str, Any]) -> None:
        self.connection.execute("DELETE FROM memory_fts WHERE id=?", (record["id"],))
        self.connection.execute("INSERT INTO memory_fts VALUES(?,?,?,?)", (record["id"], record["content"],
                               clean_json(record["tags"]), clean_json(record["metadata"])))

    def save(self, project: str, content: str, category: str = "semantic", author: str = "local",
             references: list[str] | None = None, confidence: float = 0.5,
             verification: str = "unverified", tags: list[str] | None = None,
             metadata: dict[str, Any] | None = None, visibility: str = "project",
             fact_key: str | None = None, supersedes: str | None = None) -> dict[str, Any]:
        record = dict(project=project, content=content, category=category, author=author,
                      references=[] if references is None else references, confidence=confidence, verification=verification,
                      tags=[] if tags is None else tags, metadata={} if metadata is None else metadata,
                      visibility=visibility, fact_key=fact_key)
        validate(record)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            old = self._get(project, supersedes, author) if supersedes else None
            if old and (old["state"] != "active" or old["content"] == content):
                raise ValueError("supersession requires an active, different memory")
            if old and old["fact_key"] and fact_key != old["fact_key"]:
                raise ValueError("supersession must preserve the fact identity")
            duplicate = self.connection.execute(
                "SELECT * FROM memories WHERE project=? AND content_hash=? AND state='active' AND visibility=? AND (visibility='project' OR author=?)",
                (project, digest(content), visibility, author)).fetchone()
            if fact_key:
                facts = self.connection.execute(
                    "SELECT id FROM memories WHERE project=? AND fact_key=? AND state='active' AND visibility=? AND (visibility='project' OR author=?)",
                    (project, fact_key, visibility, author)).fetchall()
                permitted = {supersedes, duplicate["id"] if duplicate else None}
                if any(r[0] not in permitted for r in facts):
                    raise ValueError("active fact conflicts; explicit supersession is required")
            if duplicate:
                if supersedes:
                    raise ValueError("replacement already exists; do not create ambiguous lineage")
                if duplicate["fact_key"] != fact_key:
                    raise ValueError("duplicate content has a different fact identity")
                result = self._projection(duplicate)
                self.connection.commit()
                return {**result, "duplicate": True}
            record.update(id="mem_" + uuid.uuid4().hex, created_at=now(), updated_at=now(), revision=1,
                          state="active", invalidation_reason=None, superseded_by=None)
            self.connection.execute("""INSERT INTO memories(id,project,category,content,content_hash,author,references_json,
                confidence,verification,tags_json,metadata_json,visibility,fact_key,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (record["id"], project, category, content, digest(content), author,
                clean_json(record["references"]), confidence, verification, clean_json(record["tags"]),
                clean_json(record["metadata"]), visibility, fact_key, record["created_at"], record["updated_at"]))
            self._fts(record)
            if old:
                self.connection.execute("UPDATE memories SET state='superseded',superseded_by=?,updated_at=?,revision=revision+1 WHERE id=?",
                                        (record["id"], now(), supersedes))
                self._event(self._get(project, supersedes, author), "supersede", author)
            self._event(record, "create", author)
            self.connection.commit()
            return {**record, "untrusted": True, "duplicate": False}
        except BaseException:
            self.connection.rollback()
            raise

    def recall(self, project: str, query: str = "", limit: int = 10, offset: int = 0,
               historical: bool = False, principal: str = "local", category: str | None = None,
               tags: list[str] | None = None, verification: str | None = None) -> dict[str, Any]:
        identifier(project)
        identifier(principal)
        if (not isinstance(query, str) or len(query) > 2000 or type(limit) is not int
                or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 100_000
                or type(historical) is not bool):
            raise ValueError("invalid memory query bounds")
        if category is not None and category not in CATEGORIES or verification is not None and verification not in VERIFICATIONS:
            raise ValueError("invalid memory filters")
        if tags is not None and (not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)):
            raise ValueError("invalid tag filter")
        where = ["m.project=?", "(m.visibility='project' OR m.author=?)"]
        params: list[Any] = [project, principal]
        if not historical:
            where.append("m.state='active'")
        for field, value in (("category", category), ("verification", verification)):
            if value is not None:
                where.append(f"m.{field}=?")
                params.append(value)
        for tag in tags or []:
            where.append("EXISTS(SELECT 1 FROM json_each(m.tags_json) WHERE value=?)")
            params.append(tag)
        terms = [term for term in re.findall(r"[\w]+", query, flags=re.UNICODE) if term.casefold() not in QUERY_STOPWORDS][:20]
        if query.strip() and not terms:
            return {"results": [], "total": 0, "limit": limit, "offset": offset}
        join = ""
        order = "m.updated_at DESC,m.id"
        if terms:
            join = " JOIN memory_fts ON memory_fts.id=m.id"
            where.append("memory_fts MATCH ?")
            params.append(" OR ".join('"' + term.replace('"', '""') + '"' for term in dict.fromkeys(terms)))
            order = "bm25(memory_fts),m.updated_at DESC,m.id"
        predicate = " AND ".join(where)
        total = self.connection.execute(f"SELECT count(*) FROM memories m{join} WHERE {predicate}", params).fetchone()[0]
        rows = self.connection.execute(f"SELECT m.* FROM memories m{join} WHERE {predicate} ORDER BY {order} LIMIT ? OFFSET ?",
                                       [*params, limit, offset]).fetchall()
        return {"results": [self._projection(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    def update(self, project: str, id: str, patch: dict[str, Any], principal: str = "local",
               *, can_verify: bool = True) -> dict[str, Any]:
        allowed = {"content", "category", "references", "confidence", "verification", "tags", "metadata", "fact_key", "expected_revision"}
        if not isinstance(patch, dict) or not patch or set(patch) - allowed:
            raise ValueError("unsupported memory update")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            record = self._get(project, id, principal)
            if record["state"] != "active":
                raise ValueError("inactive memories cannot be updated")
            expected = patch.get("expected_revision")
            if expected is not None and (type(expected) is not int or expected != record["revision"]):
                raise ValueError("memory revision conflict")
            if "content" in patch and patch["content"] != record["content"] and record["fact_key"]:
                raise ValueError("facts must be superseded rather than overwritten")
            if record["fact_key"] and "fact_key" in patch and patch["fact_key"] != record["fact_key"]:
                raise ValueError("fact identity changes require explicit supersession")
            record.update({k: v for k, v in patch.items() if k != "expected_revision"})
            if record["verification"] == "verified" and not can_verify:
                raise PermissionError("verified memory updates require verification authority")
            validate(record)
            duplicate = self.connection.execute("SELECT id FROM memories WHERE project=? AND content_hash=? AND state='active' AND id!=? AND visibility=? AND (visibility='project' OR author=?)",
                (project, digest(record["content"]), id, record["visibility"], record["author"])).fetchone()
            if duplicate:
                raise ValueError("update duplicates an active memory")
            if record["fact_key"] and self.connection.execute("SELECT 1 FROM memories WHERE project=? AND fact_key=? AND state='active' AND id!=? AND visibility=? AND (visibility='project' OR author=?)",
                (project, record["fact_key"], id, record["visibility"], record["author"])).fetchone():
                raise ValueError("active fact conflicts")
            record["updated_at"] = now()
            record["revision"] += 1
            self.connection.execute("""UPDATE memories SET content=?,content_hash=?,category=?,references_json=?,confidence=?,
                verification=?,tags_json=?,metadata_json=?,fact_key=?,updated_at=?,revision=? WHERE id=?""",
                (record["content"], digest(record["content"]), record["category"], clean_json(record["references"]),
                 record["confidence"], record["verification"], clean_json(record["tags"]), clean_json(record["metadata"]),
                 record["fact_key"], record["updated_at"], record["revision"], id))
            self._fts(record)
            self._event(record, "update", principal)
            self.connection.commit()
            return record
        except BaseException:
            self.connection.rollback()
            raise

    def invalidate(self, project: str, id: str, reason: str, principal: str = "local") -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError("invalidation requires a bounded reason")
        clean_json(reason)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            record = self._get(project, id, principal)
            if record["state"] != "active":
                raise ValueError("memory is not active")
            self.connection.execute("UPDATE memories SET state='invalid',invalidation_reason=?,updated_at=?,revision=revision+1 WHERE id=?", (reason, now(), id))
            record = self._get(project, id, principal)
            self._event(record, "invalidate", principal)
            self.connection.commit()
            return record
        except BaseException:
            self.connection.rollback()
            raise

    def delete(self, project: str, id: str, principal: str = "local") -> dict[str, Any]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._get(project, id, principal)
            self.connection.execute("DELETE FROM memory_fts WHERE id=?", (id,))
            # Explicit deletion removes historical content as well as the active row.
            self.connection.execute("DELETE FROM memory_events WHERE memory_id=? AND project=?", (id, project))
            self.connection.execute("DELETE FROM memories WHERE id=? AND project=?", (id, project))
            self.connection.commit()
            return {"id": id, "deleted": True}
        except BaseException:
            self.connection.rollback()
            raise

    def stats(self, project: str | None = None, principal: str = "local") -> dict[str, Any]:
        if project is not None:
            identifier(project)
        identifier(principal)
        where = "WHERE (visibility='project' OR author=?)" + (" AND project=?" if project else "")
        params = [principal, project] if project else [principal]
        rows = self.connection.execute(f"SELECT category,state,count(*) FROM memories {where} GROUP BY category,state", params)
        counts = [{"category": r[0], "state": r[1], "count": r[2]} for r in rows]
        return {"schema_version": 1, "total": sum(r["count"] for r in counts), "counts": counts,
                "integrity": self.connection.execute("PRAGMA quick_check").fetchone()[0]}
