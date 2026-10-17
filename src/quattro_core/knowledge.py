"""Authorized, source-scoped knowledge indexing and evidence retrieval."""
from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import pathlib
import sqlite3
import re
import stat
import uuid
import subprocess
import time
import urllib.error
from dataclasses import asdict
from contextlib import closing
from typing import Any

from .memory import MemoryStore
from .retrieval import (
    RetrievalStore, LocalNeuralEmbeddingBackend, FeatureHashEmbeddingBackend,
    MAX_FILE_BYTES, MAX_INDEX_FILES, MAX_TOTAL_FILE_BYTES, MAX_TOTAL_UNITS,
    MAX_UNITS_PER_FILE, TEXT_SUFFIXES, DENIED_PARTS, code_units, document_units,
    classify_markdown, language_for, safe_to_index, repository_state, cosine, split_unit, redact, private_database,
    TOKEN_RE, QUERY_STOPWORDS, utc_now,
)

# Bump when credential/ingestion rules change. Only successful full-source
# validation records this proof; legacy/unvalidated snapshots fail closed below.
INGESTION_POLICY_VERSION = 1


class LexicalBackend:
    model_id = "lexical-only"
    dimensions = 0

    def embed_document(self, text: str) -> bytes:
        return b""

    def embed_query(self, text: str) -> bytes:
        raise RuntimeError("semantic embeddings are disabled")


def _bytes(value: Any) -> int:
    # A UTF-8 byte upper-bound, deliberately not the usual optimistic chars/4.
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))

def _excluded(relative: pathlib.Path, patterns) -> bool:
    name = relative.as_posix()
    return any(fnmatch.fnmatchcase(name, pattern) or relative.match(pattern)
               or any(fnmatch.fnmatchcase(parent.as_posix(), pattern.rstrip("/")) for parent in relative.parents if parent != pathlib.Path("."))
               for pattern in patterns)



def _safe_root(root: pathlib.Path) -> None:
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("source root must be an absolute path without symbolic links")
    if not root.is_dir():
        raise ValueError("source root is not an existing directory")


def _read_file(root: pathlib.Path, relative: pathlib.Path) -> tuple[str, os.stat_result]:
    """Walk directory descriptors: neither ancestor swaps nor leaf links escape root."""
    if os.name == "nt":
        from ._windows import read_file
        return read_file(root, relative, MAX_FILE_BYTES)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        descriptor = os.open("/", flags | os.O_DIRECTORY)
        descriptors.append(descriptor)
        for part in (*root.parts[1:], *relative.parts[:-1]):
            descriptor = os.open(part, flags | os.O_DIRECTORY, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(relative.name, flags, dir_fd=descriptor)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise ValueError("source file is not a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) > MAX_FILE_BYTES or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise OSError("source changed during indexing")
        return raw.decode("utf-8"), after
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _claims(content: str) -> dict[str, str]:
    """Explicit facts and scalar configuration, not speculative NLP extraction."""
    claims = {}
    for match in re.finditer(r"(?mi)^\s*Fact:\s*([A-Za-z][\w.-]{0,79})\s*=\s*([^\n]{1,256})$", content):
        claims[match.group(1).casefold()] = match.group(2).strip()
    try:
        config = json.loads(content)
    except (ValueError, RecursionError):
        config = None
    if isinstance(config, dict):
        for key, value in config.items():
            if isinstance(key, str) and type(value) in {str, bool, int, float}:
                claims[key.casefold()] = str(value)
    return claims


def _walk_error(error: OSError) -> None:
    raise error


def _git_allowed(root):
    """Apply repository ignore rules, without evaluating hooks or fsmonitor."""
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root),
                                 "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
                                capture_output=True, timeout=10, check=False)
    except FileNotFoundError:
        if (root / ".gitignore").is_file() or any((parent / ".git").is_file() or
                (parent / ".git" / "HEAD").is_file() for parent in (root, *root.parents)):
            raise ValueError("Git is required to enforce repository ignore policy")
        return None  # Explicit non-Git document roots do not require a Git install.
    if result.returncode != 0:
        if (root / ".git").exists():
            raise ValueError("repository ignore policy unavailable")
        return None
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError("repository file inventory exceeds limit")
    return set(result.stdout.decode("utf-8").split("\0")) - {""}


def _source_snapshot(source):
    _safe_root(source.root)
    allowed = _git_allowed(source.root)
    files = {}
    scanned = excluded = total = 0
    for directory, dirs, names in os.walk(source.root, followlinks=False, onerror=_walk_error):
        parent = pathlib.Path(directory)
        dirs[:] = sorted(d for d in dirs if d.lower() not in DENIED_PARTS
                         and not (parent / d).is_symlink()
                         and not _excluded((parent / d).relative_to(source.root), source.exclusions))
        for name in sorted(names):
            scanned += 1
            if scanned > MAX_INDEX_FILES:
                raise ValueError("source exceeds indexing file limit")
            path = parent / name
            relative = path.relative_to(source.root)
            if (not safe_to_index(path) or _excluded(relative, source.exclusions) or
                    allowed is not None and relative.as_posix() not in allowed):
                excluded += 1
                continue
            try:
                content, info = _read_file(source.root, relative)
            except (UnicodeDecodeError, ValueError):
                excluded += 1
                continue
            if not safe_to_index(path, content):
                excluded += 1
                continue
            total += info.st_size
            if total > MAX_TOTAL_FILE_BYTES:
                raise ValueError("source exceeds indexing byte limit")
            files[relative.as_posix()] = hashlib.sha256(content.encode()).hexdigest()
    return files, {"scanned": scanned, "excluded": excluded}


def _fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _failure(error):
    retryable = isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))
    if isinstance(error, sqlite3.OperationalError):
        retryable = getattr(error, "sqlite_errorcode", None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    reasons = {FileNotFoundError: "source is missing", PermissionError: "source is inaccessible or unauthorized"}
    if isinstance(error, urllib.error.URLError):
        return {"code":"embedding_unavailable","reason":"local embedding endpoint unavailable","retryable":True}
    if str(error) == "local neural embedding response has the wrong dimensions":
        return {"code":"embedding_dimensions","reason":"embedding response dimensions incompatible with configured vectors","retryable":False}
    return {"code": type(error).__name__, "reason": reasons.get(type(error), "indexing failed; committed index preserved"),
            "retryable": retryable}


class KnowledgeService:
    def __init__(self, config, *, read_only=False):
        self.config = config
        backend = LocalNeuralEmbeddingBackend() if config.embedding == "local-neural" else LexicalBackend()
        self.store = RetrievalStore(config.database_dir / "retrieval.sqlite3", embedding_backend=backend, read_only=read_only)
        try:
            self.memory = MemoryStore(config.database_dir / "memory.sqlite3", read_only=read_only)
        except BaseException:
            self.store.close()
            raise
        self.connection = self.store.connection
        if read_only:
            return
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_sources(
          source_id TEXT PRIMARY KEY, project TEXT NOT NULL, root TEXT NOT NULL,
          indexed_at TEXT, last_attempt TEXT, last_failure TEXT, summary_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS knowledge_files(
          project TEXT NOT NULL, source_id TEXT NOT NULL, path TEXT NOT NULL,
          content_hash TEXT NOT NULL, indexed_at TEXT NOT NULL,
          PRIMARY KEY(project,source_id,path));
        CREATE TABLE IF NOT EXISTS knowledge_documents(
          document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
          project TEXT NOT NULL, source_id TEXT NOT NULL, file_hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS knowledge_scope ON knowledge_documents(project,source_id);
        """)
        self.connection.commit()

    def close(self):
        self.memory.close()
        self.store.close()

    def _sources(self, project, source_ids=None):
        self.config.authorize(project)
        sources = [s for s in self.config.sources if s.project == project]
        if source_ids is not None:
            if not isinstance(source_ids, (list, tuple)) or not all(isinstance(s, str) for s in source_ids):
                raise ValueError("source_ids must be a list of source identifiers")
            allowed = {s.id for s in sources}
            if any(s not in allowed for s in source_ids):
                raise PermissionError("source is not authorized for project")
            sources = [s for s in sources if s.id in source_ids]
        return sources

    def _remove_file(self, project, source_id, path):
        ids = [r[0] for r in self.connection.execute("""SELECT d.id FROM documents d JOIN knowledge_documents k ON k.document_id=d.id
            WHERE k.project=? AND k.source_id=? AND d.path=?""", (project, source_id, path))]
        for identifier in ids:
            self.store.forget(identifier)
        self.connection.execute("DELETE FROM knowledge_files WHERE project=? AND source_id=? AND path=?", (project, source_id, path))

    def index_source(self, source_id, reindex=False, dry_run=False):
        source = self.config.source(source_id)
        if type(reindex) is not bool or type(dry_run) is not bool:
            raise ValueError("index flags must be booleans")
        self.config.authorize(source.project, write=not dry_run)
        if source.intent == "excluded":
            raise PermissionError("source is explicitly excluded")
        for retry in range(3):
            try:
                return self._index_source(source, reindex, dry_run)
            except Exception as error:
                if dry_run or not _failure(error)["retryable"] or retry == 2:
                    raise
                time.sleep(0.1 * (2 ** retry))

    def _index_source(self, source, reindex, dry_run):
        root, attempt = source.root, utc_now()
        try:
            if not dry_run:
                # A crash before publication leaves an explicit recoverable attempt,
                # never a falsely successful replacement.
                with self.connection:
                    self.connection.execute("""INSERT INTO knowledge_sources(source_id,project,root,last_attempt,last_failure)
                        VALUES(?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                        last_attempt=excluded.last_attempt,last_failure=excluded.last_failure""",
                        (source.id, source.project, str(root), attempt,
                         json.dumps({"code":"in_progress_or_interrupted","reason":"index attempt has not committed","retryable":True})))
            files, summary = _source_snapshot(source)
            summary.update(unchanged=0, updated=0, deleted=0, embedded=0,
                           fingerprint=_fingerprint(files), policy_version=INGESTION_POLICY_VERSION)
            if dry_run:
                old = dict(self.connection.execute("SELECT path,content_hash FROM knowledge_files WHERE project=? AND source_id=?", (source.project, source.id)))
                summary.update(unchanged=sum(old.get(p) == h for p, h in files.items()),
                               updated=sum(reindex or old.get(p) != h for p, h in files.items()),
                               deleted=len(old.keys() - files.keys()))
                return {"source_id":source.id,"project":source.project,"dry_run":True,**summary}
            with self.store.transaction():
                old_source = self.connection.execute("SELECT project FROM knowledge_sources WHERE source_id=?", (source.id,)).fetchone()
                if old_source and old_source[0] != source.project:
                    raise PermissionError("source identity belongs to another project")
                state = repository_state(root, include_tracked=True)
                tracked = set(state.get("trackedPaths", ()))
                for name, digest in files.items():
                    path = root / name
                    content, _ = _read_file(root, pathlib.Path(name))
                    if hashlib.sha256(content.encode()).hexdigest() != digest:
                        raise RuntimeError("source changed during indexing; retry")
                    commit_sha = state["commitSha"] if state["dirty"] is False and name in tracked else None
                    old = self.connection.execute("SELECT content_hash FROM knowledge_files WHERE project=? AND source_id=? AND path=?", (source.project, source.id, name)).fetchone()
                    if old and old[0] == digest and not reindex:
                        summary["unchanged"] += 1
                        rows = self.connection.execute("""SELECT d.id,d.metadata_json FROM documents d
                            JOIN knowledge_documents k ON k.document_id=d.id
                            WHERE k.project=? AND k.source_id=? AND d.path=?""", (source.project,source.id,name))
                        for row in rows:
                            metadata = json.loads(row["metadata_json"])
                            metadata.update(workingTreeDirty=state["dirty"], root=str(root))
                            self.connection.execute("UPDATE documents SET commit_sha=?,metadata_json=? WHERE id=?",
                                                    (commit_sha,json.dumps(metadata),row["id"]))
                        continue
                    retained = {r["id"]:(r["content_hash"],r["embedding"],r["embedding_model"]) for r in self.connection.execute(
                        """SELECT d.* FROM documents d JOIN knowledge_documents k ON k.document_id=d.id
                        WHERE k.project=? AND k.source_id=? AND d.path=?""", (source.project,source.id,name))} if self.config.embedding == "lexical" else {}
                    self._remove_file(source.project, source.id, name)
                    units, edges = (document_units(path, content) if path.suffix.lower() in {".md", ".txt", ".rst"} else code_units(path, content))
                    if self.config.embedding == "local-neural":
                        units = [part for unit in units for part in split_unit(unit, 2800)]
                    if len(units) > MAX_UNITS_PER_FILE:
                        raise ValueError("source exceeds per-file unit limit")
                    symbols = {}
                    for index, unit in enumerate(units):
                        identifier = "source_" + hashlib.sha256(f"{source.project}\0{source.id}\0{name}\0{index}".encode()).hexdigest()
                        identifier = self.store.upsert_document(identifier=identifier,
                            source_type=classify_markdown(name) if path.suffix.lower() in {".md", ".txt", ".rst"} else "code",
                            content=unit["content"], repository=source.project, branch=source.id,
                            commit_sha=commit_sha, path=name, symbol=unit.get("symbol"), symbol_type=unit.get("symbol_type"),
                            language=language_for(path), start_line=unit.get("start_line"), end_line=unit.get("end_line"),
                            importance=source.authority, metadata={"source_id":source.id,"namespace":source.project,
                            "root":str(root),"file_hash":digest,"workingTreeDirty":state["dirty"],"claims":_claims(unit["content"])})
                        previous = retained.get(identifier)
                        if previous and previous[0] == hashlib.sha256(unit["content"].encode()).hexdigest():
                            self.connection.execute("UPDATE documents SET embedding=?,embedding_model=? WHERE id=?", (previous[1],previous[2],identifier))
                        self.connection.execute("INSERT INTO knowledge_documents VALUES(?,?,?,?)", (identifier, source.project, source.id, digest))
                        if unit.get("symbol"):
                            symbols[unit["symbol"]] = identifier
                        summary["embedded"] += int(self.store.embedding_backend.dimensions > 0)
                    for symbol, relation, target in edges:
                        identifier = symbols.get(symbol) or next(iter(symbols.values()), None)
                        if identifier:
                            self.connection.execute("INSERT OR REPLACE INTO graph_edges VALUES(?,?,?,?,?,?)", (source.project, source.id, identifier, relation, target, "{}"))
                    self.connection.execute("INSERT OR REPLACE INTO knowledge_files VALUES(?,?,?,?,?)", (source.project, source.id, name, digest, utc_now()))
                    summary["updated"] += 1
                stale = [r[0] for r in self.connection.execute("SELECT path FROM knowledge_files WHERE project=? AND source_id=?", (source.project, source.id)) if r[0] not in files]
                for name in stale:
                    self._remove_file(source.project, source.id, name)
                summary["deleted"] = len(stale)
                if self.connection.execute("SELECT count(*) FROM knowledge_documents WHERE project=? AND source_id=?", (source.project,source.id)).fetchone()[0] > MAX_TOTAL_UNITS:
                    raise ValueError("source exceeds indexing unit limit")
                if _source_snapshot(source)[0] != files:
                    raise RuntimeError("source changed during indexing; retry")
                self.connection.execute("INSERT OR REPLACE INTO knowledge_sources VALUES(?,?,?,?,?,?,?)",
                                        (source.id, source.project, str(root), utc_now(), attempt, None, json.dumps(summary)))
                self.store._bump()
            return {"source_id":source.id,"project":source.project,**summary}
        except BaseException as error:
            if not dry_run:
                try:
                    with self.connection:
                        self.connection.execute("""UPDATE knowledge_sources SET last_failure=?
                            WHERE source_id=? AND last_attempt=?""", (json.dumps(_failure(error)), source.id, attempt))
                except sqlite3.Error:
                    pass  # Preserve the original error; never claim publication.
            raise

    def search_knowledge(self, project, query, limit=10, offset=0, source_ids=None, strategy="hybrid", explain=False):
        if strategy not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("unsupported retrieval strategy")
        sources = self._sources(project, source_ids)
        status = self.get_index_status(project)
        scoped_status = [s for s in status["sources"] if source_ids is None or s["source_id"] in source_ids]
        warnings = []
        if any(s["status"] in {"pending", "failed", "stale"} for s in scoped_status):
            warnings.append("incomplete_scope: inspect index-status before concluding no evidence exists")
        if any(s["status"] == "excluded" for s in scoped_status):
            warnings.append("excluded_sources: operator policy excludes part of requested scope")
        sources = [s for s in sources if s.intent != "excluded" and any(
            t["source_id"] == s.id and t["freshness"] not in {"root_changed", "unavailable"} for t in scoped_status)]
        if not isinstance(query, str) or not query.strip() or len(query.encode()) > 32768:
            raise ValueError("query must be nonempty and bounded")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid pagination")
        # Code identifiers are exact evidence requests, not approximate concepts.
        # A cosine neighbor without the identifier cannot support a code citation.
        identifier_query = bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", query.strip()) and
                                ("_" in query or "." in query or re.search(r"[a-z][A-Z]", query)))
        identifier_match = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(query.strip()) +
                                      r"(?![A-Za-z0-9_])", re.I) if identifier_query else None
        semantic = {"available":False,"backend":self.store.embedding_backend.model_id,"reason":"semantic embeddings are disabled; lexical search only"}
        if strategy == "keyword":
            semantic["reason"] = "not requested: keyword strategy"
        if not sources:
            return {"results":[],"total":0,"limit":limit,"offset":offset,"semantic":semantic,"warnings":warnings}
        ids = [s.id for s in sources]
        scope = "k.project=? AND k.source_id IN (" + ",".join("?" for _ in ids) + ") AND d.valid_until IS NULL AND d.superseded_by IS NULL"
        params = [project, *ids]
        candidates = {}
        terms = list(dict.fromkeys(word for word in TOKEN_RE.findall(query) if word.casefold() not in QUERY_STOPWORDS))[:32]
        if terms and strategy != "semantic":
            match = " OR ".join('"' + word.replace('"','""') + '"' for word in terms)
            rows = self.connection.execute(f"""SELECT d.*,k.source_id,k.file_hash,bm25(documents_fts) AS rank FROM documents_fts
                JOIN documents d ON d.id=documents_fts.id JOIN knowledge_documents k ON k.document_id=d.id
                WHERE documents_fts MATCH ? AND {scope} ORDER BY rank""", [match,*params]).fetchall()
            for rank, row in enumerate(rows, 1):
                score = self.config.lexical_weight / (self.config.rrf_k + rank)
                candidates[row["id"]] = {"row":row,"score":score,"lexical":True,"semantic":0.0,
                                        "bm25":row["rank"],"keyword_rrf":score}
        all_rows = self.connection.execute(f"SELECT d.*,k.source_id,k.file_hash FROM documents d JOIN knowledge_documents k ON k.document_id=d.id WHERE {scope}", params).fetchall()
        normalized = query.strip().strip('"').lower()
        for row in all_rows if strategy != "semantic" else ():
            exact = (row["symbol"] or "").lower() == normalized or (row["path"] or "").lower() == normalized
            phrase = bool(terms) and normalized in row["content"].lower()
            if exact or phrase:
                item = candidates.setdefault(row["id"], {"row":row,"score":0.0,"lexical":True,"semantic":0.0})
                item["score"] += 1.0 if exact else 0.1
                item["exact_boost"] = 1.0 if exact else 0.1
        if self.config.embedding == "local-neural" and strategy != "keyword":
            try:
                vector = self.store.embedding_backend.embed_query(query)
                compatible = [r for r in all_rows if r["embedding_model"] == self.store.embedding_backend.model_id and len(r["embedding"]) == len(vector)]
                ranked = sorted(((cosine(vector, r["embedding"]), r) for r in compatible), key=lambda x:x[0], reverse=True)
                for rank, (similarity, row) in enumerate(ranked, 1):
                    if similarity < 0.35:
                        continue
                    item = candidates.setdefault(row["id"], {"row":row,"score":0.0,"lexical":False,"semantic":0.0})
                    item["score"] += self.config.semantic_weight / (self.config.rrf_k + rank)
                    item["semantic"] = similarity
                    item["semantic_rrf"] = self.config.semantic_weight / (self.config.rrf_k + rank)
                semantic = {"available":bool(compatible),"backend":self.store.embedding_backend.model_id,"reason":None if compatible else "no compatible neural vectors indexed"}
            except Exception:
                semantic["reason"] = "local neural query failed; lexical fallback used"
        output = []
        seen = set()
        spans = {}
        roots = {s.id:s.root for s in sources}
        source_map = {s.id: s for s in sources}
        current_time = dt.datetime.now(dt.timezone.utc)
        provenances = {}
        policies = {}
        for source in sources:
            try:
                _safe_root(source.root)
                policies[source.id] = _git_allowed(source.root)
            except (OSError, ValueError, subprocess.SubprocessError):
                policies[source.id] = set()
                warnings.append("source_policy_unavailable: inspect doctor")
        for item in candidates.values():
            row = item["row"]
            age = max(0, (current_time - dt.datetime.fromisoformat(row["updated_at"])).total_seconds())
            quality = source_map[row["source_id"]].authority * row["confidence"]
            item["quality_multiplier"] = 0.5 + quality + 0.1 / (1 + age / (86400 * 180))
            item["score"] *= item["quality_multiplier"]
            location = (row["source_id"], row["path"], row["file_hash"])
            if location not in provenances:
                provenance = "missing"
                try:
                    relative = pathlib.Path(row["path"] or "")
                    if relative.is_absolute() or ".." in relative.parts or not relative.name:
                        raise ValueError("invalid indexed provenance")
                    content, _ = _read_file(roots[row["source_id"]], relative)
                    source = source_map[row["source_id"]]
                    allowed = policies[source.id]
                    if (not safe_to_index(source.root / relative) or _excluded(relative, source.exclusions)
                            or allowed is not None and relative.as_posix() not in allowed):
                        raise ValueError("source evidence is no longer eligible")
                    provenance = "current" if hashlib.sha256(content.encode()).hexdigest() == row["file_hash"] else "outdated"
                    policy = next(s.get("policy_version") for s in scoped_status if s["source_id"] == source.id)
                    if provenance == "current" and policy != INGESTION_POLICY_VERSION and not safe_to_index(source.root / relative, content):
                        provenance = "excluded"
                except (OSError, ValueError, UnicodeDecodeError):
                    pass
                provenances[location] = provenance
            item["provenance"] = provenances[location]
            item["score"] *= {"current": 1.0, "outdated": 0.5, "missing": 0.25, "excluded":0.0}[item["provenance"]]
        for item in sorted(candidates.values(), key=lambda x:(-x["score"],x["row"]["id"])):
            row = item["row"]
            if identifier_match and not identifier_match.search(
                    " ".join((row["content"], row["symbol"] or "", row["path"] or ""))):
                continue
            if item["provenance"] != "current":
                continue  # Retain last-known-good storage, never deliver deleted/stale evidence.
            key = row["content_hash"]
            if key in seen:
                continue
            seen.add(key)
            location = (row["source_id"], row["path"])
            start, end = row["start_line"], row["end_line"]
            if start is not None and end is not None and any(start <= old_end and end >= old_start for old_start, old_end in spans.get(location, ())):
                continue
            if start is not None and end is not None:
                spans.setdefault(location, []).append((start, end))
            provenance = item["provenance"]
            metadata = json.loads(row["metadata_json"])
            citation = {"path":row["path"],"start_line":row["start_line"],"end_line":row["end_line"],"content_hash":row["content_hash"],"file_hash":row["file_hash"],"source_id":row["source_id"],"source_kind":source_map[row["source_id"]].kind,"namespace":project,"project":project,"provenance":provenance,"commit_sha":None if metadata.get("workingTreeDirty") else row["commit_sha"]}
            output.append({"id":row["id"],"content":row["content"],"symbol":row["symbol"],"source_type":row["source_type"],"score":item["score"],"semantic_score":item["semantic"],"citation":citation,"claims":metadata.get("claims", {}),"authority":source_map[row["source_id"]].authority,"updated_at":row["updated_at"],"untrusted":True})
            if explain:
                output[-1]["explanation"] = {
                    "rank":len(output), "bm25":item.get("bm25"), "keyword_rrf":item.get("keyword_rrf",0.0),
                    "semantic_similarity":item["semantic"] if item["semantic"] else None,
                    "semantic_rrf":item.get("semantic_rrf",0.0), "exact_or_phrase_boost":item.get("exact_boost",0.0),
                    "quality_multiplier":item["quality_multiplier"],"final_score":item["score"],
                    "indexed_at":next(s["indexed_at"] for s in scoped_status if s["source_id"] == row["source_id"]),
                    "freshness":provenance,"memory_verification":None,"supersession":"active",
                    "selected_for_context":None,"delivered":None,
                }
        if any(item["provenance"] != "current" for item in candidates.values()):
            warnings.append("stale_evidence_suppressed: refresh changed or missing sources")
        if strategy != "keyword" and not semantic["available"]:
            warnings.append("semantic_unavailable: " + semantic["reason"])
        if not output and any(s["freshness"] == "not_tested" for s in scoped_status):
            warnings.append("coverage_freshness_unverified: inspect sources --deep before inferring absence")
        return {"results":output[offset:offset+limit],"total":len(output),"limit":limit,"offset":offset,
                "semantic":semantic,"warnings":list(dict.fromkeys(warnings))[:4]}

    def get_project_context(self, project, query, budget=2000, limit=10, source_ids=None, strategy="hybrid"):
        if isinstance(budget,bool) or not isinstance(budget,int) or budget < 512 or budget > 32768:
            raise ValueError("context budget must be between 512 and 32768 UTF-8 bytes")
        found = self.search_knowledge(project, query, limit=limit, source_ids=source_ids, strategy=strategy)
        top_score = max((entry["score"] for entry in found["results"]), default=0)
        context_results = [entry for entry in found["results"] if entry["score"] >= top_score * 0.72]
        memories = [m for m in self.memory.recall(project, query=query, limit=limit, principal=self.config.principal)["results"] if m["verification"] != "disputed"]
        result = {"project":project,"knowledge":[],"memories":[],"conflicts":[],"outdated":[],"semantic":found["semantic"],"untrusted":True,"budget":{"limit":budget,"estimated_used":0,"unit":"utf8-byte-upper-bound"}}
        result["warnings"] = found["warnings"]
        if _bytes(result) + 16 > budget:
            result["warnings"] = ["degraded: inspect doctor"] if found["warnings"] else []
            result["semantic"] = {**found["semantic"], "reason":"unavailable; inspect doctor" if not found["semantic"]["available"] else None}

        def append_evidence(key, evidence, byte_cap=budget):
            candidate = dict(evidence, truncated=False)
            text = candidate["content"]
            result[key].append(candidate)
            low, high, best = 1, len(text), 0
            while low <= high:
                middle = (low + high) // 2
                candidate.update(content=text[:middle], truncated=middle < len(text))
                allocation = _bytes(result[key]) if key == "memories" else _bytes(candidate)
                if _bytes(result) + 16 <= budget and allocation <= byte_cap:
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1
            if best:
                candidate.update(content=text[:best], truncated=best < len(text))
            else:
                result[key].pop()

        facts = {}
        memories.sort(key=lambda m: (m["verification"] == "verified", m["updated_at"]), reverse=True)
        evidence_claims = {}
        contradicted_memories = set()
        for entry in found["results"]:
            if entry["citation"]["provenance"] != "current":
                continue
            for key, value in entry.get("claims", {}).items():
                prior = evidence_claims.get(key)
                if prior and str(prior["value"]).casefold() != str(value).casefold():
                    priority = lambda evidence: (evidence["authority"], evidence["citation"]["source_kind"] == "repository")
                    preferred = entry if priority(entry) > priority(prior["entry"]) else prior["entry"]
                    conflict = {"fact_key":key,"evidence_ids":[prior["entry"]["id"],entry["id"]],
                                "preferred_id":preferred["id"],"reason":"explicit source facts disagree; source authority determines preference"}
                    result["conflicts"].append(conflict)
                    if _bytes(result) + 16 > budget:
                        result["conflicts"].pop()
                if not prior or (entry["authority"], entry["citation"]["source_kind"] == "repository") > (prior["entry"]["authority"], prior["entry"]["citation"]["source_kind"] == "repository"):
                    evidence_claims[key] = {"value":value,"entry":entry}
        for memory in memories:
            claims = memory["metadata"].get("claims", {})
            if not isinstance(claims, dict):
                continue
            for key, value in claims.items():
                current = evidence_claims.get(key.casefold())
                if current and str(current["value"]).casefold() != str(value).casefold():
                    contradicted_memories.add(memory["id"])
                    conflict = {"fact_key":key,"memory_id":memory["id"],"evidence_id":current["entry"]["id"],
                                "preferred_id":current["entry"]["id"],"reason":"current source evidence contradicts a recorded memory claim"}
                    result["conflicts"].append(conflict)
                    if _bytes(result) + 16 > budget:
                        result["conflicts"].pop()
        for memory in memories:
            key = memory.get("fact_key")
            if key and key in facts and facts[key].get("content") != memory.get("content"):
                conflict = {"fact_key":key,"memory_ids":[facts[key]["id"],memory["id"]],"reason":"different stored values for the same explicit fact key"}
                result["conflicts"].append(conflict)
                if _bytes(result) + 16 > budget:
                    result["conflicts"].pop()
            if key:
                facts[key] = memory
            if memory["id"] not in contradicted_memories:
                evidence = {key: memory[key] for key in ("id", "category", "content", "verification",
                            "confidence", "references", "tags", "fact_key", "updated_at", "untrusted")}
                append_evidence("memories", evidence, max(256, budget * 35 // 100) if found["results"] else budget)
        historical = self.memory.recall(project, query=query, limit=limit, historical=True, principal=self.config.principal)["results"]
        for memory in historical:
            if memory.get("state") == "active":
                continue
            note = {"memory_id":memory["id"],"reason":memory.get("state", "historical"),"superseded_by":memory.get("superseded_by")}
            result["outdated"].append(note)
            if _bytes(result) + 16 > budget:
                result["outdated"].pop()
            key = memory.get("fact_key")
            current = facts.get(key) if key else None
            if current and current.get("content") != memory.get("content"):
                conflict = {"fact_key":key,"current_memory_id":current["id"],"outdated_memory_id":memory["id"],"reason":"explicit fact changed through recorded supersession"}
                result["conflicts"].append(conflict)
                if _bytes(result) + 16 > budget:
                    result["conflicts"].pop()
        for entry in context_results:
            if entry["citation"]["provenance"] != "current":
                note = {"id":entry["id"],"citation":entry["citation"],"reason":"indexed source changed or is unavailable"}
                result["outdated"].append(note)
                if _bytes(result) + 16 > budget:
                    result["outdated"].pop()
                continue
            content_hash = entry["citation"]["content_hash"]
            if any(m.get("content") == entry["content"] for m in result["memories"]) or any(k["citation"]["content_hash"] == content_hash for k in result["knowledge"]):
                continue
            append_evidence("knowledge", entry)
        # Include the accounting field itself, including its final digit width.
        for _ in range(3):
            result["budget"]["estimated_used"] = _bytes(result)
        if _bytes(result) > budget:
            raise ValueError("context metadata exceeds requested budget")
        return result

    def inspect_source(self, source_id, path=None):
        source = self.config.source(source_id)
        if source.intent == "excluded":
            raise PermissionError("source is excluded")
        status = next(s for s in self.get_index_status(source.project, deep=True)["sources"] if s["source_id"] == source_id)
        if path is None:
            return status
        relative = pathlib.Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise PermissionError("source path escapes authorized root")
        files, _ = _source_snapshot(source)
        if relative.as_posix() not in files:
            raise PermissionError("source file is not eligible for inspection")
        content, _ = _read_file(source.root, relative)
        if hashlib.sha256(content.encode()).hexdigest() != files[relative.as_posix()]:
            raise ValueError("source changed during inspection")
        return {"source":status,"path":relative.as_posix(),"content":content[:24000],
                "revision":files[relative.as_posix()],"truncated":len(content)>24000,"untrusted":True}

    def get_index_status(self, project=None, deep=False):
        projects = [project] if project is not None else list(self.config.projects)
        output = []
        for value in projects:
            for source in self._sources(value):
                row = self.connection.execute("SELECT * FROM knowledge_sources WHERE source_id=?", (source.id,)).fetchone()
                summary = json.loads(row["summary_json"]) if row else {}
                success = row["indexed_at"] if row else None
                failure = row["last_failure"] if row else None
                if failure:
                    try:
                        failure = json.loads(failure)
                    except (ValueError, TypeError):
                        failure = {"code":"legacy_failure","reason":"previous indexing failed","retryable":True}
                exists = source.root.is_dir() and not any(p.is_symlink() for p in (source.root, *source.root.parents))
                intended = source.intent == "intended" or source.intent != "excluded" and bool(success or row and row["last_attempt"])
                state = "indexed" if success else "pending"
                freshness = "not_tested" if success else "never_indexed"
                reason = None
                if success and summary.get("policy_version") != INGESTION_POLICY_VERSION:
                    state, reason = "stale", "source indexing policy requires validation refresh"
                if failure:
                    state, reason = "failed", failure["reason"]
                if not exists:
                    state, freshness, reason = "stale" if success else "failed", "unavailable", "source root is missing or inaccessible"
                if row and (row["project"] != source.project or row["root"] != str(source.root)):
                    state, freshness, reason = "stale", "root_changed", "configured source assignment changed; explicit reindex required"
                indexed = dict(self.connection.execute("SELECT path,content_hash FROM knowledge_files WHERE project=? AND source_id=?", (value,source.id)))
                fingerprint = summary.get("fingerprint")
                if deep and success and exists and freshness not in {"root_changed", "unavailable"}:
                    try:
                        current, _ = _source_snapshot(source)
                        freshness = "current" if current == indexed else "stale"
                        if freshness == "stale" and not failure:
                            state, reason = "stale", "source content or indexing eligibility changed"
                        fingerprint = _fingerprint(indexed)
                    except (OSError, ValueError, subprocess.SubprocessError):
                        state, freshness, reason = "failed", "unavailable", "source freshness check failed"
                if source.intent == "excluded":
                    state, intended, reason = "excluded", False, source.exclusion_reason
                classification = ("intentionally_excluded" if state == "excluded" else
                                  "intended_but_inaccessible" if intended and not exists else
                                  "intended_and_eligible" if intended else
                                  "missing_or_invalid" if not exists else "requires_scope_decision")
                output.append({"source_id":source.id,"project":value,"root":str(source.root),"kind":source.kind,
                    "exists":exists,"intended":intended,"classification":classification,"status":state,
                    "policy_version":summary.get("policy_version"),
                    "reason":reason,"freshness":freshness,"fingerprint":fingerprint,
                    "indexed_at":success,"last_success":success,"last_attempt":row["last_attempt"] if row else None,
                    "last_failure":failure,"files":len(indexed),
                    "documents":self.connection.execute("SELECT count(*) FROM knowledge_documents WHERE project=? AND source_id=?", (value,source.id)).fetchone()[0],
                    "remediation":None if state == "indexed" else
                    "Review scope before explicit index" if not intended and state == "pending" else
                    "Fix source access/configuration, then run index SOURCE" if state != "excluded" else "Excluded by operator policy"})
        counts = {name:sum(s["status"] == name for s in output) for name in ("indexed","pending","stale","failed","excluded")}
        counts.update(registered=len(output), intended=sum(s["intended"] for s in output))
        return {"sources":output,"counts":counts,"files":sum(s["files"] for s in output),"documents":sum(s["documents"] for s in output)}

    def index_selected(self, project=None, source_ids=None, retry_failed=False, dry_run=True):
        status = self.get_index_status(project, deep=True)
        if source_ids is not None:
            projects = [project] if project else self.config.projects
            allowed = {s.id for p in projects for s in self._sources(p)}
            if any(s not in allowed for s in source_ids):
                raise PermissionError("source is not authorized")
        selected = [s for s in status["sources"] if s["status"] != "excluded" and
                    (s["source_id"] in source_ids if source_ids is not None else s["intended"]) and
                    (not retry_failed or s["status"] == "failed")]
        results = []
        for source in selected:
            try:
                results.append(self.index_source(source["source_id"], dry_run=dry_run))
            except Exception as error:
                results.append({"source_id":source["source_id"],"failure":_failure(error)})
        return {"dry_run":dry_run,"results":results}

    def health(self):
        status = self.get_index_status()
        database = "ok" if self.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok" else "error"
        memory_database = "ok" if self.memory.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok" else "error"
        semantic = {"available":False,"backend":self.store.embedding_backend.model_id,"reason":"lexical-only"}
        if self.config.embedding == "local-neural":
            try:
                self.store.embedding_backend.embed_query("health")
                semantic.update(available=True, reason=None)
            except Exception:
                semantic["reason"] = "local neural endpoint unavailable"
        return {"ok":database == "ok" and memory_database == "ok" and not any(s["last_failure"] for s in status["sources"]),"database":database,"memory_database":memory_database,"semantic":semantic,**status}


def migrate_legacy_database(source: pathlib.Path, destination: pathlib.Path, *, project=None, source_id=None, source_root=None):
    """Copy legacy knowledge online, preserving originals and quarantining unmapped rows."""
    source, destination = pathlib.Path(source), pathlib.Path(destination)
    if source == destination or destination.exists() or not source.is_file() or any(p.is_symlink() for p in (source,*source.parents,destination,*destination.parents)):
        raise ValueError("migration requires a regular source and a new destination")
    if bool(project) != bool(source_id):
        raise ValueError("project and source_id must be supplied together")
    if project:
        from .config import identifier, safe_path
        identifier(project)
        identifier(source_id)
        if source_root is not None:
            source_root = safe_path(source_root, directory=True)
    private_database(destination)
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        with closing(sqlite3.connect(destination)) as target:
            original.backup(target)
    finally:
        original.close()
    os.chmod(destination,0o600)
    store = RetrievalStore(destination)
    try:
        with store.transaction():
            store.connection.execute("CREATE TABLE IF NOT EXISTS legacy_quarantine(document_id TEXT PRIMARY KEY, original_repository TEXT, assigned_project TEXT, assigned_source_id TEXT)")
            rows = store.connection.execute("SELECT * FROM documents").fetchall()
            assigned = []
            for row in rows:
                metadata = json.loads(row["metadata_json"])
                matches = bool(project and row["repository"] == project)
                if project and source_root is not None:
                    matches = matches or row["repository"] == str(source_root)
                    authoritative = metadata.get("authoritativePath")
                    if isinstance(authoritative, str):
                        matches = matches or pathlib.Path(authoritative).is_relative_to(source_root)
                if redact(row["content"])[1] or redact(json.dumps(metadata))[1]:
                    matches = False
                store.connection.execute("INSERT OR REPLACE INTO legacy_quarantine VALUES(?,?,?,?)",
                                         (row["id"],row["repository"],project if matches else None,source_id if matches else None))
                if matches:
                    assigned.append(row)
            if project:
                store.connection.execute("CREATE TABLE IF NOT EXISTS knowledge_documents(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,project TEXT NOT NULL,source_id TEXT NOT NULL,file_hash TEXT NOT NULL)")
                for row in assigned:
                    original_file = store.connection.execute("SELECT content_hash FROM indexed_files WHERE repository=? AND branch=? AND path=?",
                        (str(source_root) if source_root else row["repository"], row["branch"] or "__unversioned__", row["path"])).fetchone()
                    file_hash = original_file[0] if original_file else row["content_hash"]
                    store.connection.execute("INSERT OR REPLACE INTO knowledge_documents VALUES(?,?,?,?)", (row["id"],project,source_id,file_hash))
        imported_memories = 0
        if project:
            memories = MemoryStore(destination.parent / "memory.sqlite3")
            try:
                for row in assigned:
                    metadata = json.loads(row["metadata_json"])
                    if (metadata.get("explicit") or metadata.get("approvedConsolidation")) and not row["valid_until"] and not row["superseded_by"] and len(row["content"].encode()) <= 24000:
                        try:
                            memories.save(project, row["content"], author="legacy-import",
                                references=[f"legacy:{source_id}:{row['id']}:{row['content_hash']}"],
                                confidence=row["confidence"], metadata={"legacy_id":row["id"],
                                "legacy_metadata":metadata,"legacy_superseded_by":row["superseded_by"],
                                "legacy_valid_until":row["valid_until"],"legacy_created_at":row["created_at"]})
                            imported_memories += 1
                        except ValueError:
                            # Keep incompatible metadata/content in the copied legacy store.
                            continue
            finally:
                memories.close()
        return {"destination":str(destination),"documents":len(rows),"assigned":len(assigned),"quarantined":len(rows)-len(assigned),"project":project,"source_id":source_id,"imported_memories":imported_memories}
    finally:
        store.close()
