from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))
from quattro_core.config import Config, Source
from quattro_core.knowledge import KnowledgeService, migrate_legacy_database
from quattro_core.retrieval import RetrievalStore, redact


class KnowledgeCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.a = self.root / "a"
        self.b = self.root / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.config = Config(self.root / "db", (Source("a", "alpha", self.a), Source("b", "beta", self.b)), ("alpha", "beta"), writable=True)
        self.service = KnowledgeService(self.config)
        self.addCleanup(self.service.close)

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_explicit_namespace_and_source_isolation_same_relative_path(self):
        self.write(self.a, "same.py", "def ExactSymbol():\n    return 'alpha'\n")
        self.write(self.b, "same.py", "def ExactSymbol():\n    return 'beta'\n")
        self.service.index_source("a")
        self.service.index_source("b")
        alpha = self.service.search_knowledge("alpha", "ExactSymbol")
        self.assertEqual(alpha["total"], 1)
        self.assertIn("alpha", alpha["results"][0]["content"])
        self.assertEqual(alpha["results"][0]["citation"]["source_id"], "a")
        with self.assertRaises(PermissionError):
            self.service.search_knowledge("alpha", "ExactSymbol", source_ids=["b"])
        with self.assertRaises(PermissionError):
            self.service.search_knowledge("unknown", "ExactSymbol")
        self.service.store.upsert_document(source_type="code", content="ExactSymbol global secret context")
        self.assertEqual(self.service.search_knowledge("alpha", "ExactSymbol")["total"], 1)

    def test_same_root_can_be_assigned_to_distinct_sources(self):
        self.write(self.a, "shared.md", "# shared\nshared root phrase")
        config = dataclasses.replace(self.config, sources=(Source("first", "alpha", self.a), Source("second", "beta", self.a)))
        other = KnowledgeService(config)
        try:
            other.index_source("first")
            other.index_source("second")
            self.assertEqual(other.search_knowledge("alpha", "shared")["results"][0]["citation"]["source_id"], "first")
            self.assertEqual(other.search_knowledge("beta", "shared")["results"][0]["citation"]["source_id"], "second")
        finally:
            other.close()

    def test_incremental_changes_deletion_rename_and_no_unchanged_embedding(self):
        path = self.write(self.a, "before.md", "# indexing\nold unique phrase")
        self.service.index_source("a")
        with mock.patch.object(self.service.store.embedding_backend, "embed_document", side_effect=AssertionError("unchanged must not embed")):
            self.assertEqual(self.service.index_source("a")["unchanged"], 1)
        path.write_text("# indexing\nnew unique phrase")
        self.assertEqual(self.service.search_knowledge("alpha", "old")["results"], [])
        self.service.index_source("a")
        self.assertEqual(self.service.search_knowledge("alpha", "old")["total"], 0)
        path.rename(self.a / "after.md")
        summary = self.service.index_source("a")
        self.assertEqual(summary["deleted"], 1)
        self.assertEqual(self.service.search_knowledge("alpha", "new")["results"][0]["citation"]["path"], "after.md")
        (self.a / "after.md").unlink()
        self.service.index_source("a")
        self.assertEqual(self.service.get_index_status("alpha")["documents"], 0)

    def test_index_failure_rolls_back_whole_source_and_reports_failure(self):
        path = self.write(self.a, "one.md", "# stable\nold evidence")
        self.service.index_source("a")
        path.write_text("# changed\nreplacement evidence")
        self.write(self.a, "two.md", "# second\nother evidence")
        with mock.patch.object(self.service.store.embedding_backend, "embed_document", side_effect=RuntimeError("embedding offline")):
            with self.assertRaises(RuntimeError):
                self.service.index_source("a")
        self.assertIn("old evidence", self.service.connection.execute("SELECT content FROM documents").fetchone()[0])
        self.assertEqual(self.service.search_knowledge("alpha", "old")["results"], [])
        self.assertEqual(self.service.search_knowledge("alpha", "replacement")["total"], 0)
        self.assertIsNotNone(self.service.get_index_status("alpha")["sources"][0]["last_failure"])
        self.service.index_source("a")
        self.assertIsNone(self.service.get_index_status("alpha")["sources"][0]["last_failure"])

    def test_exclusions_credentials_build_outputs_and_symlink_ancestors(self):
        self.write(self.a, "public.md", "# public\npublic evidence")
        self.write(self.a, "credentials.json", '{"password": "hunter-two"}')
        self.write(self.a, "leak.json", '{"api_key": "private-value"}')
        self.write(self.a, "dist/output.md", "private build artifact")
        self.write(self.a, "ignore.md", "ignored material")
        (self.a / "link").symlink_to(self.b, target_is_directory=True)
        self.write(self.b, "outside.md", "outside evidence")
        other = KnowledgeService(dataclasses.replace(self.config, sources=(Source("filtered", "alpha", self.a, exclusions=("ignore.md",)),)))
        try:
            summary = other.index_source("filtered")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(other.search_knowledge("alpha", "private outside ignored")["total"], 0)
        finally:
            other.close()
        for secret in ('{"password": "hunter-two"}', '-----BEGIN PRIVATE KEY-----', 'Cookie: session=abcdefghijklmnopqrstuvwxyz'):
            self.assertTrue(redact(secret)[1])
        self.assertFalse(redact("Documentation explains password rotation and api_key handling.")[1])

    def test_exact_symbols_semantics_fallback_and_full_budget_citations(self):
        self.write(self.a, "symbols.py", "def precise_identifier():\n    return 42\n\ndef other():\n    return 'precise identifier'\n")
        self.service.index_source("a")
        found = self.service.search_knowledge("alpha", "precise_identifier")
        self.assertEqual(found["results"][0]["symbol"], "precise_identifier")
        self.assertFalse(found["semantic"]["available"])
        context = self.service.get_project_context("alpha", "precise_identifier", budget=1800)
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode()), 1800)
        citation = context["knowledge"][0]["citation"]
        for field in ("path", "start_line", "end_line", "content_hash", "file_hash", "source_id", "namespace", "provenance"):
            self.assertIn(field, citation)
        self.assertEqual(citation["provenance"], "current")
        neural = KnowledgeService(dataclasses.replace(self.config, embedding="local-neural"))
        try:
            with mock.patch.object(neural.store.embedding_backend, "embed_query", side_effect=RuntimeError("offline")):
                fallback = neural.search_knowledge("alpha", "precise_identifier")
            self.assertTrue(fallback["results"])
            self.assertFalse(fallback["semantic"]["available"])
            self.assertIn("fallback", fallback["semantic"]["reason"])
        finally:
            neural.close()

    def test_legacy_import_preserves_original_and_quarantines(self):
        legacy = self.root / "legacy.sqlite3"
        with RetrievalStore(legacy) as store:
            identifier = store.upsert_document(source_type="documentation", content="legacy retained evidence")
        digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
        destination = self.root / "imported.sqlite3"
        report = migrate_legacy_database(legacy, destination)
        self.assertEqual(report["quarantined"], 1)
        self.assertEqual(hashlib.sha256(legacy.read_bytes()).hexdigest(), digest)
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM documents").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT document_id FROM legacy_quarantine").fetchone()[0], identifier)

    def test_read_only_index_authorization(self):
        other = KnowledgeService(dataclasses.replace(self.config, writable=False))
        try:
            with self.assertRaises(PermissionError):
                other.index_source("a")
            self.assertEqual(other.get_index_status("alpha")["files"], 0)
        finally:
            other.close()

    def test_context_merges_only_authorized_relevant_memory(self):
        self.service.memory.save("alpha", "architecture prior decision", author="local")
        self.service.memory.save("alpha", "architecture private other", author="other", visibility="private")
        self.service.memory.save("beta", "architecture other namespace", author="local")
        context = self.service.get_project_context("alpha", "architecture", budget=2400)
        self.assertEqual([m["content"] for m in context["memories"]], ["architecture prior decision"])
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode()), 2400)

    def test_mapped_legacy_explicit_memory_and_vectors_preserved(self):
        legacy = self.root / "mapped.sqlite3"
        with RetrievalStore(legacy) as store:
            identifier = store.upsert_document(source_type="memory", content="retained operator decision", repository=str(self.a), metadata={"explicit":True})
            vector = store.connection.execute("SELECT embedding FROM documents WHERE id=?", (identifier,)).fetchone()[0]
        destination = self.config.database_dir / "mapped-copy.sqlite3"
        report = migrate_legacy_database(legacy, destination, project="alpha", source_id="a", source_root=self.a)
        self.assertEqual(report["imported_memories"], 1)
        self.assertTrue(self.service.memory.recall("alpha", "operator")["results"])
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT embedding FROM documents WHERE id=?", (identifier,)).fetchone()[0], vector)

    def test_future_version_is_rejected_without_deleting_rows(self):
        database = self.root / "future.sqlite3"
        with RetrievalStore(database) as store:
            store.upsert_document(source_type="code", content="future preserved data")
            store.connection.execute("UPDATE retrieval_meta SET value='999' WHERE key='index_version'")
            store.connection.commit()
        with self.assertRaises(ValueError):
            RetrievalStore(database)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM documents").fetchone()[0], 1)

    def test_migration_never_relabels_another_project_or_global_memory(self):
        legacy = self.root / "scopes.sqlite3"
        with RetrievalStore(legacy) as store:
            alpha = store.upsert_document(source_type="memory", content="Alpha lasting decision", repository=str(self.a), metadata={"explicit": True})
            beta = store.upsert_document(source_type="memory", content="Beta private decision", repository=str(self.b), metadata={"explicit": True})
            global_id = store.upsert_document(source_type="memory", content="Unassigned historical observation", metadata={"explicit": True})
        destination = self.root / "mapped" / "retrieval.sqlite3"
        report = migrate_legacy_database(legacy, destination, project="alpha", source_id="a", source_root=self.a)
        self.assertEqual((report["documents"], report["assigned"], report["quarantined"]), (3, 1, 2))
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute("SELECT document_id FROM knowledge_documents").fetchall(), [(alpha,)])
            self.assertEqual({r[0] for r in connection.execute("SELECT id FROM documents")}, {alpha, beta, global_id})

    def test_current_repository_facts_override_conflicting_notes_and_memories(self):
        notes = self.root / "notes"
        notes.mkdir()
        config = dataclasses.replace(self.config, sources=(*self.config.sources, Source("notes", "alpha", notes, "obsidian", authority=0.4)))
        self.write(self.a, "ARCHITECTURE.md", "# Storage\nFact: database=SQLite\n")
        self.write(notes, "DECISIONS.md", "# Storage\nFact: database=PostgreSQL\n")
        service = KnowledgeService(config)
        try:
            service.index_source("a")
            service.index_source("notes")
            service.memory.save("alpha", "database is PostgreSQL", metadata={"claims": {"database": "PostgreSQL"}})
            context = service.get_project_context("alpha", "database", budget=5000)
            self.assertTrue(context["conflicts"])
            self.assertTrue(any(c.get("preferred_id") in {r["id"] for r in context["knowledge"]} for c in context["conflicts"]))
            self.assertEqual(context["memories"], [])
        finally:
            service.close()

    def test_long_source_tail_imports_and_configuration_are_searchable(self):
        self.write(self.a, "module.py", "import urllib.request\nCONFIGURED_LIMIT = 17\n\ndef short_symbol():\n    return 1\n")
        self.write(self.a, "long.md", "preamble context\n# Large section\n" + "ordinary prose\n" * 3000 + "\nTAIL_TECHNICAL_IDENTIFIER\n")
        self.service.index_source("a")
        self.assertEqual(self.service.search_knowledge("alpha", "CONFIGURED_LIMIT")["results"][0]["symbol"], "CONFIGURED_LIMIT")
        self.assertTrue(self.service.search_knowledge("alpha", "urllib.request")["results"])
        found = self.service.search_knowledge("alpha", "TAIL_TECHNICAL_IDENTIFIER")
        self.assertTrue(found["results"])
        self.assertGreater(found["results"][0]["citation"]["start_line"], 1)
        context = self.service.get_project_context("alpha", "ordinary prose", budget=1800)
        self.assertTrue(context["knowledge"])
        self.assertTrue(context["knowledge"][0]["truncated"])
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode()), 1800)

    def test_overlapping_document_content_is_deduplicated_across_sources(self):
        notes = self.root / "notes"
        notes.mkdir()
        self.write(self.a, "architecture.md", "# Database\nSQLite is the shared persistent storage engine.")
        self.write(notes, "memo.md", "# Database\nSQLite is the shared persistent storage engine.")
        config = dataclasses.replace(self.config, sources=(*self.config.sources, Source("notes", "alpha", notes, "obsidian")))
        service = KnowledgeService(config)
        try:
            service.index_source("a")
            service.index_source("notes")
            self.assertEqual(service.search_knowledge("alpha", "persistent storage")["total"], 1)
        finally:
            service.close()

    def test_generic_imports_and_overlapping_class_methods_are_retrievable(self):
        self.write(self.a, "client.ts", 'import { durableAdapter } from "persist-library";\nexport const RETRY_LIMIT = 17;\nexport function reconnect() { return durableAdapter(); }\n')
        self.write(self.a, "store.py", "class JournalStore:\n    def remember_lesson(self):\n        return 'durable lesson'\n")
        self.service.index_source("a")
        for query in ("persist-library", "RETRY_LIMIT"):
            self.assertEqual(self.service.search_knowledge("alpha", query)["results"][0]["citation"]["path"], "client.ts")
        result = self.service.search_knowledge("alpha", "remember_lesson")
        self.assertEqual(result["results"][0]["symbol"], "remember_lesson")
        self.assertEqual([r["symbol"] for r in result["results"] if r["citation"]["path"] == "store.py"], ["remember_lesson"])

    def test_distinct_character_chunks_remain_retrievable_when_citation_lines_overlap(self):
        for newline in ("", "\n"):
            with self.subTest(multiline=bool(newline)):
                first = ("copper firstpassage " + newline + "alpha " * 6000)[:32000]
                second = ("copper secondpassage " + "beta " * 7000)[:32000]
                self.write(self.a, "long.txt", first + second)
                self.service.index_source("a")
                result = self.service.search_knowledge("alpha", "copper", strategy="keyword")
                self.assertEqual(result["total"], 2)
                self.assertEqual({row["content"] for row in result["results"]}, {first, second})
                page = self.service.search_knowledge("alpha", "copper", strategy="keyword",
                                                     limit=1, offset=1)
                self.assertEqual(page["total"], 2)
                self.assertEqual([row["id"] for row in page["results"]],
                                 [row["id"] for row in result["results"][1:2]])

    def test_unrecognized_database_is_rejected_without_mutation(self):
        path = self.root / "unrelated.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE historical_knowledge(id TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO historical_knowledge VALUES(?,?)", ("old", "preserved"))
            db.commit()
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            RetrievalStore(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT value FROM historical_knowledge").fetchone()[0], "preserved")
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='documents'").fetchone())

    @unittest.skipUnless(shutil.which("git"), "Git provenance requires Git")
    def test_git_citations_refresh_without_reembedding_uncommitted_or_ignored_files(self):
        def git(*arguments):
            return subprocess.run(["git", "-C", str(self.a), "-c", "user.name=Quattro Test",
                                   "-c", "user.email=example@invalid.test", "-c", "commit.gpgsign=false",
                                   "-c", "core.hooksPath=" + str(self.root / "no-hooks"),
                                   "-c", "core.fsmonitor=false", *arguments],
                                  check=True, capture_output=True, text=True).stdout.strip()

        git("init", "-q", "-b", "main")
        self.write(self.a, "README.md", "# Versioned project\nInitial project evidence.")
        self.write(self.a, ".gitignore", "ignored.py\n")
        git("add", "README.md", ".gitignore")
        git("commit", "-qm", "Initial evidence")
        self.write(self.a, "new.py", "def newly_published_symbol():\n    return 1\n")
        self.write(self.a, "ignored.py", "def intentionally_unversioned_symbol():\n    return 1\n")
        self.service.index_source("a")
        self.assertIsNone(self.service.search_knowledge("alpha", "newly_published_symbol")["results"][0]["citation"]["commit_sha"])
        git("add", "new.py")
        git("commit", "-qm", "Publish unchanged indexed evidence")
        commit = git("rev-parse", "HEAD")
        result = self.service.index_source("a")
        self.assertEqual((result["updated"], result["embedded"]), (0, 0))
        self.assertEqual(self.service.search_knowledge("alpha", "newly_published_symbol")["results"][0]["citation"]["commit_sha"], commit)
        self.assertEqual(self.service.search_knowledge("alpha", "intentionally_unversioned_symbol")["results"], [])
        self.write(self.a, "new.py", "def newly_published_symbol():\n    return 2\n")
        self.service.index_source("a")
        self.assertIsNone(self.service.search_knowledge("alpha", "newly_published_symbol")["results"][0]["citation"]["commit_sha"])
