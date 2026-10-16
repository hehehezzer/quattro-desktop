"""Consistent private SQLite snapshots and restore-to-new-directory verification."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
from contextlib import ExitStack, closing

from .config import safe_path
from .retrieval import utc_now

DATABASES = ("retrieval.sqlite3", "memory.sqlite3", "native-receipts.sqlite3")


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integrity(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        check = db.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        if check != [("ok",)] or foreign_keys:
            raise ValueError("database integrity check failed")
        return {"integrity":"ok", "user_version":db.execute("PRAGMA user_version").fetchone()[0]}


def _authorize_snapshot(config, directory, names):
    projects = set()
    from .receipts import scope_allowed
    if "retrieval.sqlite3" in names:
        with closing(sqlite3.connect((directory / "retrieval.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            version = db.execute("SELECT value FROM retrieval_meta WHERE key='index_version'").fetchone()
            if version is None or version[0] != "3":
                raise ValueError("unsupported retrieval recovery schema")
            allowed = {s.id:(s.project,str(s.root)) for s in config.sources if s.intent != "excluded"}
            for source_id, project, root in db.execute("SELECT source_id,project,root FROM knowledge_sources"):
                if allowed.get(source_id) != (project,root):
                    raise PermissionError("snapshot contains a source outside configured authority")
            for source_id, project in db.execute("SELECT DISTINCT source_id,project FROM knowledge_documents UNION SELECT DISTINCT source_id,project FROM knowledge_files"):
                if source_id not in allowed or allowed[source_id][0] != project:
                    raise PermissionError("snapshot contains unauthorized source mappings")
            projects |= {r[0] for r in db.execute("SELECT DISTINCT project FROM knowledge_sources")}
            projects |= {r[0] for r in db.execute("SELECT DISTINCT project FROM knowledge_documents")}
            unmapped = db.execute("SELECT count(*) FROM documents d LEFT JOIN knowledge_documents k ON d.id=k.document_id WHERE k.document_id IS NULL").fetchone()[0]
            if unmapped and not config.can_verify:
                raise PermissionError("unmapped historical content requires full operator authority")
    if "memory.sqlite3" in names:
        with closing(sqlite3.connect((directory / "memory.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("unsupported memory recovery schema")
            projects |= {r[0] for r in db.execute("SELECT DISTINCT project FROM memories UNION SELECT DISTINCT project FROM memory_events")}
            private = db.execute("SELECT count(*) FROM memories WHERE visibility='private' AND author!=?", (config.principal,)).fetchone()[0]
            if private and not config.can_verify:
                raise PermissionError("private memory export requires full operator authority")
    if "native-receipts.sqlite3" in names:
        with closing(sqlite3.connect((directory / "native-receipts.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            for project, metadata in db.execute("SELECT project,metadata_json FROM native_receipts"):
                if project:
                    projects.add(project)
                projects.update(json.loads(metadata).get("authorized_scope", []))
                if not scope_allowed(config, project, json.loads(metadata)):
                    raise PermissionError("snapshot receipts contain unauthorized source scope")
    if projects - set(config.projects):
        raise PermissionError("snapshot includes projects outside configured authority")


def backup(config, destination):
    if not config.writable:
        raise PermissionError("full-store backup requires operator write authority")
    destination = safe_path(destination)
    # Authorization is rechecked while all writer reservations are held below.
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"version":1, "created_at":utc_now(), "projects":sorted(config.projects),
                "embedding":config.embedding, "files":{}, "complete":False,
                "sources":[{"id":s.id,"project":s.project,"root":str(s.root),"kind":s.kind,
                            "intent":s.intent,"exclusions":list(s.exclusions)} for s in config.sources]}
    with ExitStack() as stack:
        # Hold writer reservations across every snapshot. Readers continue in WAL.
        # Independent read connections avoid backing up an active write transaction.
        names = [n for n in DATABASES if (config.database_dir / n).is_file()]
        if not all(n in names for n in DATABASES[:2]):
            raise ValueError("required database missing")
        for name in names:
            path = safe_path(config.database_dir / name)
            lock = stack.enter_context(closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)))
            lock.execute("BEGIN IMMEDIATE")
        _authorize_snapshot(config, config.database_dir, names)
        for name in names:
            target = destination / name
            target.touch(mode=0o600, exist_ok=False)
            original = stack.enter_context(closing(sqlite3.connect((config.database_dir / name).as_uri() + "?mode=ro", uri=True)))
            with closing(sqlite3.connect(target)) as replica:
                original.backup(replica)
            manifest["files"][name] = {"sha256":_hash(target), **integrity(target)}
        manifest["complete"] = True
        with (destination / "manifest.json").open("x", encoding="utf-8") as stream:
            os.chmod(stream.name, 0o600)
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
    return {"backed_up":names,"manifest":"manifest.json","complete":True}


def verify_backup(config, source):
    source = safe_path(source, directory=True)
    manifest_path = safe_path(source / "manifest.json")
    if manifest_path.stat().st_size > 128000:
        raise ValueError("oversized recovery manifest")
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get("files", {})
    if (manifest.get("version") != 1 or manifest.get("complete") is not True or
            set(manifest.get("projects", [])) - set(config.projects) or
            not set(DATABASES[:2]).issubset(files) or set(files) - set(DATABASES)):
        raise ValueError("unsupported or unauthorized recovery manifest")
    for name, metadata in files.items():
        path = safe_path(source / name)
        if _hash(path) != metadata["sha256"] or integrity(path)["user_version"] != metadata["user_version"]:
            raise ValueError("backup checksum or schema mismatch")
    _authorize_snapshot(config, source, files)
    return manifest


def restore(config, source, destination):
    """Never overwrite a live store; a failed restore remains an unusable new directory."""
    if not config.writable:
        raise PermissionError("restore requires operator write authority")
    source, destination = safe_path(source, directory=True), safe_path(destination)
    manifest_path = source / "manifest.json"
    files = verify_backup(config, source)["files"]
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in files:
        target = destination / name
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output, (source / name).open("rb") as original:
            for block in iter(lambda: original.read(1024 * 1024), b""):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if _hash(target) != files[name]["sha256"]:
            raise ValueError("restored copy checksum mismatch")
        integrity(target)
    # Check mapping consistency without mutating restored content or derived vectors.
    with closing(sqlite3.connect(destination / "retrieval.sqlite3")) as db:
        broken = db.execute("""SELECT count(*) FROM knowledge_documents k
            LEFT JOIN documents d ON d.id=k.document_id
            LEFT JOIN knowledge_sources s ON s.source_id=k.source_id AND s.project=k.project
            WHERE d.id IS NULL OR s.source_id IS NULL""").fetchone()[0]
        if broken:
            raise ValueError("restored source references are broken")
    report = {"version":1,"verified_at":utc_now(),"integrity":"ok","restored":list(files),
              "source_manifest_sha256":_hash(manifest_path),"destination_is_new":True}
    path = destination / "recovery-verified.json"
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(report, stream, sort_keys=True)
    return report
