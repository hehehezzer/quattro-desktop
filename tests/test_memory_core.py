from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))
from quattro_core.memory import MemoryStore
from quattro_core.config import Config, Source


class MemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.path = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_restart_namespaces_private_visibility_and_verification(self):
        fact = self.store.save("alpha", "SQLite stores verified architectural facts", author="alice",
                               references=["repo:architecture.md:12"], verification="verified", tags=["database"])
        self.store.save("beta", "Redis is beta project storage", author="bob")
        private = self.store.save("alpha", "Private investigation evidence", author="alice", visibility="private")
        self.store.close()
        self.store = MemoryStore(self.path)
        rows = self.store.recall("alpha", "architectural facts", principal="bob")["results"]
        self.assertEqual([r["id"] for r in rows], [fact["id"]])
        self.assertEqual(rows[0]["references"], ["repo:architecture.md:12"])
        self.assertEqual(rows[0]["verification"], "verified")
        self.assertEqual(self.store.recall("alpha", "Redis", principal="alice")["results"], [])
        self.assertNotIn(private["id"], [r["id"] for r in self.store.recall("alpha", principal="bob")["results"]])
        self.assertIn(private["id"], [r["id"] for r in self.store.recall("alpha", principal="alice")["results"]])
        with self.assertRaises(KeyError):
            self.store.update("beta", fact["id"], {"tags": ["wrong-project"]}, principal="alice")
        with self.assertRaises(KeyError):
            self.store.invalidate("alpha", private["id"], "unauthorized", principal="bob")

    def test_duplicate_conflict_supersession_invalidation_and_deletion(self):
        old = self.store.save("alpha", "Database uses SQLite", fact_key="database")
        duplicate = self.store.save("alpha", " Database  uses SQLite ", fact_key="database")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(old["id"], duplicate["id"])
        with self.assertRaises(ValueError):
            self.store.save("alpha", "Database uses PostgreSQL", fact_key="database")
        with self.assertRaises(ValueError):
            self.store.update("alpha", old["id"], {"content": "Database uses PostgreSQL"})
        replacement = self.store.save("alpha", "Database uses PostgreSQL", fact_key="database", supersedes=old["id"])
        self.assertEqual([r["id"] for r in self.store.recall("alpha", "Database")["results"]], [replacement["id"]])
        historical = self.store.recall("alpha", "Database", historical=True)["results"]
        prior = next(r for r in historical if r["id"] == old["id"])
        self.assertEqual(prior["superseded_by"], replacement["id"])
        self.assertEqual(prior["state"], "superseded")
        self.store.invalidate("alpha", replacement["id"], "Current repository contradicts the observation")
        self.assertEqual(self.store.recall("alpha", "Database")["results"], [])
        self.store.delete("alpha", replacement["id"])
        self.assertEqual([r["id"] for r in self.store.recall("alpha", historical=True)["results"]], [old["id"]])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory_events WHERE memory_id=?", (replacement["id"],)).fetchone()[0], 0)
        self.assertEqual(self.store.stats("alpha")["integrity"], "ok")

    def test_supersession_identity_conflict_is_actionable_and_atomic(self):
        signer = self.store.save("alpha", "Signer exports into temporary storage", fact_key="signer")
        original = self.store.get("alpha", signer["id"])
        with self.assertRaises(ValueError) as rejected:
            self.store.save("alpha", "Release activation passed", fact_key="release",
                            supersedes=signer["id"])
        self.assertEqual(getattr(rejected.exception, "code", None), "fact_identity_mismatch")
        self.assertEqual(rejected.exception.details, {
            "memory_id": signer["id"], "existing_fact_key": "signer",
            "requested_fact_key": "release",
        })
        self.assertEqual(self.store.get("alpha", signer["id"]), original)
        self.assertEqual(self.store.recall("alpha", "activation")["results"], [])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory_events").fetchone()[0], 1)

        release = self.store.save("alpha", "Release activation passed", fact_key="release")
        self.assertEqual({row["id"] for row in self.store.recall("alpha")["results"]},
                         {signer["id"], release["id"]})
        self.assertEqual(self.store.get("alpha", signer["id"])["state"], "active")

    def test_private_supersession_target_does_not_disclose_fact_identity(self):
        private = self.store.save("alpha", "Private signing evidence", author="alice",
                                  visibility="private", fact_key="private-signing")
        with self.assertRaises(KeyError) as rejected:
            self.store.save("alpha", "Release activation passed", author="bob",
                            fact_key="release", supersedes=private["id"])
        self.assertNotIn("private-signing", str(rejected.exception))
        self.assertEqual(self.store.recall("alpha", principal="bob")["results"], [])
        self.assertEqual(self.store.get("alpha", private["id"], principal="alice")["revision"], 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory_events").fetchone()[0], 1)

    def test_revision_conflict_and_failed_update_preserve_original(self):
        memory = self.store.save("alpha", "Investigated the index timeout", category="episodic",
                                 fact_key="index_timeout")
        changed = self.store.update("alpha", memory["id"], {"tags": ["timeout"], "expected_revision": 1})
        self.assertEqual(changed["revision"], 2)
        with self.assertRaises(ValueError) as stale:
            self.store.update("alpha", memory["id"], {"content": "Stale writer wins", "expected_revision": 1})
        self.assertEqual(stale.exception.code, "revision_conflict")
        self.assertEqual(stale.exception.details["current_revision"], 2)
        with self.assertRaises(ValueError) as overwrite:
            self.store.update("alpha", memory["id"], {"content": "Different fact content", "expected_revision": 2})
        self.assertEqual(overwrite.exception.code, "supersession_required")
        with self.assertRaises(ValueError):
            self.store.update("alpha", memory["id"], {"confidence": float("nan")})
        current = self.store.recall("alpha", "timeout")["results"][0]
        self.assertEqual(current["content"], memory["content"])
        self.assertEqual(current["revision"], 2)

    def test_credentials_in_content_references_metadata_and_reasons_rejected(self):
        secrets = ['-----BEGIN PRIVATE KEY-----\nabc', '"password": "super-secret-value"',
                   '"api_key": "sample-secret-value"', 'Bearer abcdefghijklmnopqrstuv']
        for secret in secrets:
            with self.subTest(secret_type=secret.split(":")[0]):
                with self.assertRaises(ValueError):
                    self.store.save("alpha", secret)
                with self.assertRaises(ValueError):
                    self.store.save("alpha", "Safe fact", metadata={"evidence": secret})
                with self.assertRaises(ValueError):
                    self.store.save("alpha", "Safe fact", references=[secret])
        self.assertEqual(self.store.stats("alpha")["total"], 0)
        with self.assertRaises(ValueError):
            self.store.save("alpha", "Fact without evidence", verification="verified")

    def test_independent_concurrent_connections_deduplicate_atomically(self):
        def save(_):
            store = MemoryStore(self.path)
            try:
                return store.save("alpha", "One durable shared fact", fact_key="unique")["id"]
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(save, range(12)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.store.stats("alpha")["total"], 1)

    def test_pagination_tag_filters_and_private_stats(self):
        one = self.store.save("alpha", "Investigated connection pooling", category="procedural", tags=["sqlite"], author="alice")
        self.store.save("alpha", "Private diagnostics", visibility="private", author="alice")
        rows = self.store.recall("alpha", tags=["sqlite"], category="procedural", limit=1, principal="bob")
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["results"][0]["id"], one["id"])
        self.assertEqual(self.store.stats("alpha", principal="bob")["total"], 1)
        self.assertEqual(self.store.recall("alpha", tags=["sqlite"], offset=1)["results"], [])

    def test_fact_identity_cannot_be_cleared_changed_or_lost_by_deduplication(self):
        fact = self.store.save("alpha", "Database uses SQLite", fact_key="database")
        observation = self.store.save("alpha", "Database uses PostgreSQL")
        for patch in ({"fact_key": None}, {"fact_key": "renamed"}):
            with self.assertRaises(ValueError):
                self.store.update("alpha", fact["id"], patch)
        with self.assertRaises(ValueError):
            self.store.save("alpha", observation["content"], fact_key="database")
        with self.assertRaises(ValueError):
            self.store.save("alpha", observation["content"], fact_key="new-fact")
        self.assertEqual(self.store.get("alpha", fact["id"])["revision"], 1)
        self.assertEqual(self.store.get("alpha", observation["id"])["fact_key"], None)

    def test_encoded_credentials_fail_without_mutating_memory_or_audit(self):
        record = self.store.save("alpha", "Safe investigation")
        encoded = [r'{\"password\": \"example-only-value\"}',
                   r'{"pass\u0077ord": "example-only-value"}']
        for content in encoded:
            for field in ("content", "references", "metadata"):
                patch = {field: content if field == "content" else [content] if field == "references" else {"nested": content}}
                with self.assertRaises(ValueError):
                    self.store.update("alpha", record["id"], patch)
            with self.assertRaises(ValueError):
                self.store.invalidate("alpha", record["id"], content)
        self.assertEqual(self.store.get("alpha", record["id"])["revision"], 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM memory_events").fetchone()[0], 1)

    def test_verified_updates_require_atomic_verification_authority(self):
        record = self.store.save("alpha", "Verified architectural constraint",
                                 verification="verified", references=["repo:architecture.md:1"])
        with self.assertRaises(PermissionError):
            self.store.update("alpha", record["id"], {"tags": ["changed"]}, can_verify=False)
        self.assertEqual(self.store.get("alpha", record["id"])["revision"], 1)
        changed = self.store.update("alpha", record["id"], {"verification": "unverified"}, can_verify=False)
        self.assertEqual(changed["verification"], "unverified")


class ConfigCoreTests(unittest.TestCase):
    def test_round_trip_and_authorized_root_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "repo"
            source.mkdir()
            config = Config(root / "db", (Source("code", "alpha", source),), ("alpha",))
            path = root / "intelligence.json"
            config.save(path)
            loaded = Config.load(path)
            self.assertEqual(loaded.source("code").root, source)
            with self.assertRaises(PermissionError):
                loaded.authorize("beta")
            with self.assertRaises(PermissionError):
                loaded.authorize("alpha", write=True)
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            with self.assertRaises(ValueError):
                Source("alias", "alpha", alias)
            with self.assertRaises(ValueError):
                Config(root / "db", (Source("code", "beta", source),), ("alpha",))
