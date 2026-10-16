"""Consumer-visible recovery, source eligibility and diagnostic contracts."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_core.config import Config, Source
from quattro_core.doctor import diagnose
from quattro_core.feedback import record, export
from quattro_core.knowledge import KnowledgeService
from quattro_core.mcp import McpRuntime
from quattro_core.native import execute
from quattro_core.receipts import Receipts
from quattro_core.recovery import backup, restore
from quattro_core.retrieval import LocalNeuralEmbeddingBackend


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.path = self.source / "decision.md"
        self.path.write_text("# Storage\nFact: storage=SQLite\nDurableCanary evidence.\n")
        self.config = Config(self.root / "db", (Source("code","alpha",self.source),),
                             ("alpha","beta"), principal="alice", writable=True)
        self.config_path = self.root / "intelligence.json"
        self.config.save(self.config_path)
        self.service = KnowledgeService(self.config)
        self.addCleanup(self.service.close)

    def test_source_lifecycle_content_fingerprint_and_deletion_before_reindex(self):
        self.assertEqual(self.service.get_index_status()["counts"]["pending"],1)
        self.service.index_source("code")
        first = self.service.get_index_status(deep=True)["sources"][0]
        self.assertEqual((first["status"],first["freshness"]),("indexed","current"))
        self.path.write_text("# Storage\nDifferentCanary evidence.\n")
        second = self.service.get_index_status(deep=True)["sources"][0]
        self.assertEqual(second["status"],"stale")
        self.assertEqual(second["indexed_at"],first["indexed_at"])
        self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["results"],[])
        self.service.index_source("code")
        self.assertIn("DifferentCanary",self.service.search_knowledge("alpha","DifferentCanary")["results"][0]["content"])
        self.path.unlink()
        self.assertEqual(self.service.search_knowledge("alpha","DifferentCanary")["results"],[])
        self.assertEqual(self.service.index_source("code")["deleted"],1)
        self.assertEqual(self.service.get_index_status()["documents"],0)

    def test_timestamp_preserving_edits_are_stale(self):
        self.service.index_source("code")
        stamp = self.path.stat()
        self.path.write_text(self.path.read_text().replace("SQLite","Redis!"))
        os.utime(self.path, ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(self.service.get_index_status(deep=True)["sources"][0]["status"],"stale")

    def test_rename_repeat_and_dry_run_do_not_duplicate_or_embed(self):
        self.service.index_source("code")
        self.path.rename(self.source / "new.md")
        planned = self.service.index_source("code",dry_run=True)
        self.assertEqual((planned["updated"],planned["deleted"]),(1,1))
        self.assertEqual(self.service.connection.execute("SELECT path FROM knowledge_files").fetchone()[0],"decision.md")
        self.service.index_source("code")
        with mock.patch.object(self.service.store.embedding_backend,"embed_document",side_effect=AssertionError("unchanged must not embed")):
            self.assertEqual(self.service.index_source("code")["unchanged"],1)
        found = self.service.search_knowledge("alpha","DurableCanary")["results"]
        self.assertEqual([r["citation"]["path"] for r in found],["new.md"])

    def test_missing_root_does_not_disable_other_sources_or_lose_last_success(self):
        self.service.index_source("code")
        self.path.unlink()
        self.source.rmdir()
        loaded = Config.load(self.config_path)
        self.assertEqual(loaded.source("code").root,self.source)
        source = self.service.get_index_status(deep=True)["sources"][0]
        self.assertEqual(source["status"],"stale")
        self.assertIsNotNone(source["last_success"])
        with self.assertRaises(ValueError):
            self.service.index_source("code")
        self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["results"],[])

    def test_explicit_root_change_suppresses_old_index_until_successful_reconciliation(self):
        self.service.index_source("code")
        replacement = self.root / "replacement"
        replacement.mkdir()
        (replacement / "new.md").write_text("ReplacementCanary evidence")
        changed = dataclasses.replace(self.config,sources=(Source("code","alpha",replacement),))
        with closing(KnowledgeService(changed)) as service:
            self.assertEqual(service.get_index_status()["sources"][0]["status"],"stale")
            self.assertEqual(service.search_knowledge("alpha","DurableCanary")["results"],[])
            summary = service.index_source("code")
            self.assertEqual(summary["deleted"],1)
            self.assertEqual(service.search_knowledge("alpha","ReplacementCanary")["results"][0]["citation"]["path"],"new.md")

    def test_partial_failure_and_process_interruption_preserve_committed_records(self):
        self.service.index_source("code")
        original = self.service.connection.execute("SELECT id,content,embedding FROM documents ORDER BY id").fetchall()
        self.path.write_text("ReplacementCanary pending change")
        with mock.patch.object(self.service.store.embedding_backend,"embed_document",side_effect=RuntimeError("backend offline")):
            with self.assertRaises(RuntimeError):
                self.service.index_source("code")
        self.assertEqual([tuple(r) for r in self.service.connection.execute("SELECT id,content,embedding FROM documents ORDER BY id")],[tuple(r) for r in original])
        self.assertIsNotNone(self.service.get_index_status()["sources"][0]["last_failure"])
        script = """import os,sys
from pathlib import Path
from quattro_core.config import Config
from quattro_core.knowledge import KnowledgeService
s=KnowledgeService(Config.load(Path(sys.argv[1])))
s.store.embedding_backend.embed_document=lambda text: os._exit(23)
s.index_source('code')
"""
        result = subprocess.run([sys.executable,"-c",script,str(self.config_path)],
                                env=dict(os.environ,PYTHONPATH=str(Path(__file__).parents[1]/"src")),capture_output=True,timeout=20)
        self.assertEqual(result.returncode,23)
        self.assertEqual([tuple(r) for r in self.service.connection.execute("SELECT id,content,embedding FROM documents ORDER BY id")],[tuple(r) for r in original])
        self.assertEqual(self.service.get_index_status()["sources"][0]["last_failure"]["code"],"in_progress_or_interrupted")
        self.service.index_source("code")
        self.assertEqual(self.service.search_knowledge("alpha","ReplacementCanary")["results"][0]["content"],"ReplacementCanary pending change")

    def test_retryable_embedding_failure_is_bounded_and_failure_remains_observable(self):
        self.service.index_source("code")
        self.path.write_text("RetryCanary change")
        with mock.patch.object(self.service.store.embedding_backend,"embed_document",side_effect=urllib.error.URLError("refused")) as embed:
            with mock.patch("quattro_core.knowledge.time.sleep"):
                with self.assertRaises(urllib.error.URLError):
                    self.service.index_source("code")
        self.assertEqual(embed.call_count,3)
        state = self.service.get_index_status()["sources"][0]
        self.assertEqual(state["status"],"failed")
        self.assertTrue(state["last_failure"]["retryable"])
        self.assertIsNotNone(state["last_success"])
        self.assertEqual(self.service.search_knowledge("alpha","RetryCanary")["results"],[])
        self.service.index_source("code")
        self.assertEqual(self.service.get_index_status()["sources"][0]["status"],"indexed")

    def test_concurrent_index_requests_publish_one_set_of_records(self):
        def index(_):
            with closing(KnowledgeService(self.config)) as service:
                return service.index_source("code")
        with ThreadPoolExecutor(max_workers=3) as workers:
            list(workers.map(index,range(6)))
        self.assertEqual(self.service.connection.execute("SELECT count(*) FROM knowledge_files").fetchone()[0],1)
        self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["total"],1)

    def test_git_ignore_and_new_exclusions_remove_eligibility_immediately(self):
        subprocess.run(["git","init","-q",str(self.source)],check=True)
        (self.source / ".gitignore").write_text("ignored.md\n")
        (self.source / "ignored.md").write_text("IgnoredCanary data")
        self.service.index_source("code")
        self.assertEqual(self.service.search_knowledge("alpha","IgnoredCanary")["results"],[])
        filtered = dataclasses.replace(self.config,sources=(Source("code","alpha",self.source,exclusions=("decision.md",)),))
        with closing(KnowledgeService(filtered)) as service:
            self.assertEqual(service.search_knowledge("alpha","DurableCanary")["results"],[])
            with self.assertRaises(PermissionError):
                service.inspect_source("code","decision.md")

    def test_excluded_and_pending_sources_require_deliberate_scope(self):
        extra = self.root / "extra"
        extra.mkdir()
        config = dataclasses.replace(self.config,sources=(*self.config.sources,
            Source("extra","alpha",extra),Source("excluded","alpha",extra,intent="excluded",exclusion_reason="private material")))
        with closing(KnowledgeService(config)) as service:
            self.assertEqual(service.index_selected(dry_run=True)["results"],[])
            with self.assertRaises(PermissionError):
                service.index_source("excluded")
            service.index_source("code")
            selected = service.index_selected(dry_run=True)
            self.assertEqual([r["source_id"] for r in selected["results"]],["code"])
            result = service.get_project_context("alpha","unsupported",budget=512)
            self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()),512)
            self.assertTrue(result["warnings"])
            self.assertEqual(result["knowledge"],[])

    def test_source_inspection_never_reads_outside_or_secret_files(self):
        (self.source / ".env").write_text("PrivateCanary")
        outside = self.root / "outside.md"
        outside.write_text("OutsideCanary")
        (self.source / "link.md").symlink_to(outside)
        for path in ("../outside.md",".env","link.md"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.service.inspect_source("code",path)
        self.assertIn("DurableCanary",self.service.inspect_source("code","decision.md")["content"])

    def test_real_scores_explain_and_feedback_do_not_promote_knowledge(self):
        self.service.index_source("code")
        result = self.service.search_knowledge("alpha","DurableCanary",strategy="keyword",explain=True)["results"][0]
        explanation = result["explanation"]
        self.assertIsNotNone(explanation["bm25"])
        self.assertEqual(explanation["semantic_rrf"],0)
        self.assertAlmostEqual((explanation["keyword_rrf"]+explanation["exact_or_phrase_boost"])*explanation["quality_multiplier"],result["score"])
        before = self.service.connection.execute("SELECT content,confidence FROM documents WHERE id=?",(result["id"],)).fetchone()
        record(self.service,"alpha",result["id"],"irrelevant")
        self.assertEqual(export(self.service,"alpha")["feedback"][0]["label"],"irrelevant")
        self.assertEqual(tuple(before),tuple(self.service.connection.execute("SELECT content,confidence FROM documents WHERE id=?",(result["id"],)).fetchone()))
        with self.assertRaises(PermissionError):
            record(self.service,"beta",result["id"],"relevant")

    def test_native_receipt_stages_scope_and_failed_delivery_survive_reconnect(self):
        self.service.index_source("code")
        request = {"cwd":str(self.source),"query":"DurableCanary","session_id":"session-a","diagnostic":True}
        result = execute(self.config,"omp","context",request)
        receipt = result["receipt"]
        self.assertTrue(receipt["stages"]["evidence_found"])
        self.assertTrue(receipt["selected_results"])
        self.assertGreater(receipt["context_bytes"],0)
        self.assertEqual(receipt["delivery"],"unverified")
        self.assertNotIn("DurableCanary",json.dumps(receipt))
        bad = {"receipt_id":receipt["id"],"session_id":"another-session","boundary":"omp_context_messages"}
        with self.assertRaises(ValueError):
            execute(self.config,"omp","delivered",bad)
        failed = execute(self.config,"omp","delivery_failed",dict(bad,session_id="session-a"))
        self.assertEqual(failed["delivery"],"failed")
        with closing(Receipts(self.config)) as receipts:
            stored = receipts.recent("omp",{"session_id":"session-a"})["receipts"][0]
            self.assertEqual(stored["delivery"],"failed")
            self.assertEqual(stored["metadata"]["stages"]["answer_cited"],"not_observed")

    def test_receipt_private_project_and_shared_only_scope_are_not_leaked(self):
        with closing(Receipts(self.config)) as receipts:
            receipt = receipts.record("codex",{"session_id":"beta-session"},"beta","context","ready",{"result_count":1,"authorized_scope":["beta"]})
            receipts.record("codex",{},None,"context","ready",{"result_count":1,"authorized_scope":["beta"]})
        restricted = dataclasses.replace(self.config,projects=("alpha",))
        with closing(Receipts(restricted)) as receipts:
            self.assertEqual(receipts.recent("codex",{})["receipts"],[])
            with self.assertRaises(PermissionError):
                receipts.delivered("codex",{"receipt_id":receipt["id"],"session_id":"beta-session","boundary":"codex_model_input_observed"})

    def test_codex_submission_is_not_acceptance_or_use(self):
        with closing(Receipts(self.config)) as receipts:
            receipt = receipts.record("codex",{"session_id":"codex-s"},"alpha","context","ready",{"result_count":1})
            observed = receipts.delivered("codex",{"receipt_id":receipt["id"],"session_id":"codex-s","boundary":"codex_hook_stdout"},"submitted")
            self.assertEqual(observed["delivery"],"submitted")
            self.assertEqual(observed["client_accepted"],"not_observed")
            self.assertEqual(observed["answer_cited"],"not_observed")

    def test_verified_memory_requires_nonblank_provenance_and_agent_authority(self):
        for reference in ([],[""],[" "]):
            with self.assertRaises(ValueError):
                self.service.memory.save("alpha","UnsupportedCanary",verification="verified",references=reference)
        with closing(McpRuntime(dataclasses.replace(self.config,can_verify=False))) as runtime:
            with self.assertRaises(PermissionError):
                runtime.call("save_memory",{"project":"alpha","content":"AgentCanary assertion","verification":"verified","references":["source:fake"]})
        self.service.memory.save("alpha","DisputedCanary",verification="disputed")
        self.assertEqual(self.service.get_project_context("alpha","DisputedCanary")["memories"],[])

    def test_memory_history_is_project_and_private_author_isolated(self):
        memory = self.service.memory.save("alpha","PrivateCanary",author="alice",visibility="private")
        self.service.memory.update("alpha",memory["id"],{"tags":["investigation"]},principal="alice")
        history = self.service.memory.history("alpha",memory["id"],principal="alice")["history"]
        self.assertEqual([r["operation"] for r in history],["create","update"])
        for project,principal in (("beta","alice"),("alpha","bob")):
            with self.assertRaises(KeyError):
                self.service.memory.history(project,memory["id"],principal=principal)

    def test_backup_restore_preserves_vectors_source_mappings_memory_history_and_receipts(self):
        self.service.index_source("code")
        fact = self.service.memory.save("alpha","RecoveryCanary",author="alice",fact_key="storage")
        replacement = self.service.memory.save("alpha","RecoveryCanary current",author="alice",fact_key="storage",supersedes=fact["id"])
        with closing(Receipts(self.config)) as receipts:
            receipts.record("omp",{},"alpha","context","ready",{"result_count":1})
        destination = self.root / "backup"
        result = backup(self.config,destination)
        self.assertTrue(result["complete"])
        restored = self.root / "restored"
        proof = restore(self.config,destination,restored)
        self.assertEqual(proof["integrity"],"ok")
        for name in result["backed_up"]:
            self.assertEqual(hashlib.sha256((destination/name).read_bytes()).digest(),hashlib.sha256((restored/name).read_bytes()).digest())
        with closing(KnowledgeService(dataclasses.replace(self.config,database_dir=restored))) as service:
            self.assertEqual(service.search_knowledge("alpha","DurableCanary")["total"],1)
            self.assertEqual(service.memory.get("alpha",fact["id"],"alice")["superseded_by"],replacement["id"])
            self.assertEqual([e["operation"] for e in service.memory.history("alpha",fact["id"],"alice")["history"]],["create","supersede"])
        with self.assertRaises(FileExistsError):
            restore(self.config,destination,restored)
        with (destination/"memory.sqlite3").open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(ValueError):
            restore(self.config,destination,self.root/"corrupt")
        self.assertFalse((self.root/"corrupt").exists())

    def test_full_store_backup_cannot_bypass_project_or_private_scope(self):
        self.service.index_source("code")
        self.service.memory.save("beta","ForeignCanary",author="bob")
        restricted = dataclasses.replace(self.config,projects=("alpha",))
        with self.assertRaises(PermissionError):
            backup(restricted,self.root/"foreign")
        self.service.memory.save("alpha","PrivateCanary",author="bob",visibility="private")
        with self.assertRaises(PermissionError):
            backup(self.config,self.root/"private")

    def test_doctor_missing_storage_and_incomplete_coverage_are_not_healthy(self):
        absent = dataclasses.replace(self.config,database_dir=self.root/"absent")
        report = diagnose(absent,self.config_path)
        self.assertEqual(report["status"],"unavailable")
        self.assertFalse(absent.database_dir.exists())
        report = diagnose(self.config,self.config_path,project="alpha",deep=True)
        self.assertEqual(report["status"],"degraded")
        self.assertEqual(report["sources"]["counts"]["pending"],1)
        self.assertEqual(report["integrations"]["omp"]["connection"],"not_tested")
        self.assertTrue(all(p["reason"] and p["action"] for p in report["issues"]))

    def test_embedding_wrong_dimension_model_and_degraded_keyword_fallback(self):
        backend = LocalNeuralEmbeddingBackend()
        for body in ({"model":backend.model_id,"data":[{"embedding":[.1]}]},
                     {"model":"wrong-model","data":[{"embedding":[.1]*768}]}):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(body).encode()
            opener = mock.Mock()
            opener.open.return_value = response
            with mock.patch("quattro_core.retrieval.urllib.request.build_opener",return_value=opener), self.assertRaises(RuntimeError):
                backend.embed_query("dimension boundary")
        self.service.index_source("code")
        neural = dataclasses.replace(self.config,embedding="local-neural")
        with closing(KnowledgeService(neural)) as service:
            with mock.patch.object(LocalNeuralEmbeddingBackend,"embed_query",side_effect=urllib.error.URLError("refused")):
                found = service.search_knowledge("alpha","DurableCanary")
                self.assertEqual(found["total"],1)
                self.assertFalse(found["semantic"]["available"])
                self.assertTrue(any("semantic_unavailable" in w for w in found["warnings"]))
                report = diagnose(neural,self.config_path)
        self.assertEqual(report["retrieval"]["hybrid"],"degraded")

    def test_semantic_neighbors_cannot_fabricate_an_identifier_citation(self):
        import struct
        self.service.index_source("code")
        vector = struct.pack("<768f", *([0.1] * 768))
        with closing(KnowledgeService(dataclasses.replace(self.config,embedding="local-neural"))) as service:
            with service.connection:
                service.connection.execute("UPDATE documents SET embedding=?,embedding_model=?",
                                           (vector,service.store.embedding_backend.model_id))
            with mock.patch.object(service.store.embedding_backend,"embed_query",return_value=vector):
                self.assertEqual(service.search_knowledge("alpha","NeverImplementedCanary",strategy="semantic")["results"],[])
                self.assertEqual(service.search_knowledge("alpha","DurableCanary",strategy="semantic")["results"][0]["citation"]["path"],"decision.md")
                self.assertEqual(service.search_knowledge("alpha","durable project recollection",strategy="semantic")["total"],1)

    def test_benchmark_measures_real_scoped_results_and_unavailable_semantics(self):
        from quattro_core.benchmark import evaluate_core, compare_core
        self.service.index_source("code")
        cases = [
            {"id":"supported","query":"DurableCanary","project":"alpha","source_ids":["code"],
             "expected_files":["decision.md"],"answerable":True,"split":"heldout"},
            {"id":"unsupported","query":"NeverImplementedCanary","project":"alpha","source_ids":["code"],
             "expected_files":[],"answerable":False,"split":"heldout"},
        ]
        report = evaluate_core(self.service,cases)
        keyword = report["strategies"]["keyword"]["metrics"]
        self.assertEqual((keyword["recall_at_5"],keyword["mrr"],keyword["no_evidence_accuracy"]),(1,1,1))
        self.assertEqual(keyword["boundary_violations"],0)
        self.assertEqual(report["strategies"]["semantic"]["metrics"]["unavailable_cases"],2)
        self.service.memory.save("alpha","NeverImplementedCanary",author=self.config.principal)
        with_memory = evaluate_core(self.service,cases)
        self.assertEqual(with_memory["strategies"]["keyword"]["metrics"]["no_evidence_accuracy"],0)
        with self.assertRaises(ValueError):
            compare_core(report,with_memory)
        self.path.write_text("ChangedCanary different corpus")
        self.service.index_source("code")
        with self.assertRaises(ValueError):
            compare_core(report,evaluate_core(self.service,cases))

    def test_registered_intent_and_exclusion_survive_reload(self):
        from quattro_core.config import register_source
        register_source(self.config_path, Source("approved","alpha",self.source,intent="intended"))
        register_source(self.config_path, Source("denied","alpha",self.source,intent="excluded",exclusion_reason="private scope"))
        loaded = Config.load(self.config_path)
        self.assertEqual(loaded.source("denied").exclusion_reason,"private scope")
        with closing(KnowledgeService(loaded)) as service:
            self.assertEqual([r["source_id"] for r in service.index_selected()["results"]],["approved"])
            with self.assertRaises(PermissionError):
                service.index_source("denied")
            with self.assertRaises(PermissionError):
                service.inspect_source("denied","decision.md")

    def test_backup_restore_enforce_same_project_source_allowlist(self):
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("other","alpha",self.source)))
        with closing(KnowledgeService(wide)) as service:
            service.index_source("code")
            service.index_source("other")
        full = self.root/"full-backup"
        backup(wide, full)
        with self.assertRaises(PermissionError):
            backup(self.config,self.root/"restricted-backup")
        with self.assertRaises(PermissionError):
            restore(self.config,full,self.root/"restricted-restore")
        self.assertFalse((self.root/"restricted-restore").exists())

    def test_doctor_does_not_repair_damaged_schema_or_change_permissions(self):
        with self.service.connection:
            self.service.connection.execute("DROP TABLE query_cache")
        database = self.config.database_dir/"retrieval.sqlite3"
        self.service.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database.chmod(0o640)
        original = database.read_bytes()
        files = set(self.config.database_dir.iterdir())
        report = diagnose(self.config,self.config_path,deep=True)
        self.assertEqual(report["status"],"unavailable")
        self.assertEqual(database.read_bytes(),original)
        self.assertEqual(database.stat().st_mode & 0o777,0o640)
        self.assertEqual(set(self.config.database_dir.iterdir()),files)
        self.assertIsNone(self.service.connection.execute("SELECT name FROM sqlite_master WHERE name='query_cache'").fetchone())

    def test_index_receipts_use_resolved_source_project_in_both_transports(self):
        from quattro_core.mcp import handle
        beta = self.root/"beta"
        beta.mkdir()
        (beta/"fact.md").write_text("BetaCanary evidence")
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("beta-code","beta",beta)))
        result = execute(wide,"omp","call",{"cwd":str(self.source),"session_id":"alpha-cwd",
                         "name":"index_source","arguments":{"source_id":"beta-code"}})
        self.assertEqual(result["receipt"]["project"],"beta")
        self.assertEqual(result["receipt"]["authorized_sources"],["beta-code"])
        with mock.patch.dict(os.environ,{"QUATTRO_NATIVE_HOST":"codex"}), closing(McpRuntime(wide)) as runtime:
            result = handle({"jsonrpc":"2.0","id":1,"method":"tools/call",
                             "params":{"name":"index_source","arguments":{"source_id":"beta-code"}}},runtime)
            self.assertEqual(result["result"]["_meta"]["quattro.receipt"]["project"],"beta")
        narrowed = dataclasses.replace(self.config,projects=("alpha",))
        with closing(Receipts(narrowed)) as receipts:
            self.assertEqual(receipts.recent("omp",{})["receipts"],[])
            self.assertEqual(receipts.recent("codex",{})["receipts"],[])

    def test_receipt_inspection_respects_same_project_source_allowlist(self):
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("other","alpha",self.source)))
        with closing(Receipts(wide)) as receipts:
            receipts.record("omp",{},"alpha","context","ready",{"selected_results":[{"id":"test-result","source_id":"other"}]})
        with closing(Receipts(self.config)) as receipts:
            self.assertEqual(receipts.recent("omp",{})["receipts"],[])

    def test_excluded_coverage_is_not_confused_with_selected_evidence(self):
        from quattro_core.receipts import scope_allowed
        config = dataclasses.replace(self.config,sources=(*self.config.sources,
            Source("excluded","alpha",self.source,intent="excluded",exclusion_reason="outside scope")))
        self.service.index_source("code")
        result = execute(config,"omp","context",{"cwd":str(self.source),"query":"DurableCanary","session_id":"excluded-coverage"})
        receipt = result["receipt"]
        self.assertEqual({s["source_id"] for s in receipt["selected_results"]},{"code"})
        self.assertTrue(scope_allowed(config,"alpha",receipt))
        with closing(Receipts(config)) as receipts:
            self.assertEqual(receipts.recent("omp",{})["receipts"][0]["id"],receipt["id"])
            self.assertEqual(receipts.delivered("omp",{"receipt_id":receipt["id"],"session_id":"excluded-coverage",
                             "boundary":"omp_context_messages"})["delivery"],"confirmed")
        self.assertEqual(diagnose(config,self.config_path)["integrations"]["omp"]["connection"],"observed_request")
        self.assertTrue(backup(config,self.root/"excluded-coverage-backup")["complete"])
        self.assertFalse(scope_allowed(config,"alpha",{"sources":[{"source_id":"unknown"}]}))
        self.assertFalse(scope_allowed(config,"alpha",{"selected_results":[{"source_id":"excluded"}]}))

    def test_aborted_native_retrieval_retains_attempt_without_claiming_selection(self):
        request = {"cwd":str(self.source),"query":"DurableCanary","session_id":"interrupted-context"}
        with mock.patch.object(McpRuntime,"call",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                execute(self.config,"omp","context",request)
        with closing(Receipts(self.config)) as receipts:
            row = receipts.recent("omp",{"session_id":"interrupted-context"})["receipts"][0]
        self.assertEqual(row["status"],"attempted")
        self.assertTrue(row["metadata"]["stages"]["request_received"])
        self.assertTrue(row["metadata"]["stages"]["retrieval_attempted"])
        self.assertFalse(row["metadata"]["stages"]["context_selected"])
        self.assertEqual(row["delivery"],"unverified")

    def test_ingestion_policy_upgrade_revalidates_existing_content(self):
        import re
        import quattro_core.retrieval as retrieval
        self.service.index_source("code")
        self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["total"],1)
        with mock.patch("quattro_core.knowledge.INGESTION_POLICY_VERSION",2), mock.patch.object(
                retrieval,"SECRET_PATTERNS",(*retrieval.SECRET_PATTERNS,re.compile("DurableCanary"))):
            self.assertEqual(self.service.get_index_status()["sources"][0]["status"],"stale")
            self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["results"],[])
            self.service.index_source("code")
            self.assertEqual(self.service.get_index_status()["documents"],0)

    def test_non_git_document_roots_do_not_require_git_binary(self):
        with mock.patch("quattro_core.knowledge.subprocess.run",side_effect=FileNotFoundError):
            self.service.index_source("code")
            self.assertEqual(self.service.search_knowledge("alpha","DurableCanary")["total"],1)
            (self.source/".gitignore").write_text("decision.md\n")
            with self.assertRaises(ValueError):
                self.service.index_source("code")

    def test_doctor_respects_source_scope_and_reports_broken_lexical_and_receipt_storage(self):
        other = self.root/"other"
        other.mkdir()
        (other/"hidden.md").write_text("health health HiddenCanary")
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("other","alpha",other)))
        with closing(KnowledgeService(wide)) as service:
            service.index_source("other")
        self.assertEqual(diagnose(self.config,self.config_path)["retrieval"]["keyword_probe_matches"],0)
        self.service.index_source("code")
        with self.service.connection:
            self.service.connection.execute("DELETE FROM documents_fts WHERE id IN (SELECT document_id FROM knowledge_documents WHERE source_id='code')")
        report = diagnose(self.config,self.config_path)
        self.assertEqual(report["retrieval"]["keyword"],"degraded")
        self.assertEqual(report["retrieval"]["missing_fts_records"],1)
        (self.config.database_dir/"native-receipts.sqlite3").write_bytes(b"not sqlite")
        report = diagnose(self.config,self.config_path)
        self.assertEqual(report["integrations"]["omp"]["connection"],"unavailable")
        self.assertTrue(any(p["component"] == "omp:receipts" for p in report["issues"]))

    def test_all_source_scoped_attempt_success_and_failure_receipts_remain_isolated(self):
        from quattro_core.mcp import handle
        other = self.root/"other"
        other.mkdir()
        fact = other/"fact.md"
        fact.write_text("OtherCanary")
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("other","alpha",other)))
        path = self.root/"wide.json"
        wide.save(path)
        request = {"cwd":str(self.source),"session_id":"source-b-native","name":"index_source","arguments":{"source_id":"other"}}
        execute(wide,"omp","call",request)
        message = {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"index_source","arguments":{"source_id":"other"}}}
        with mock.patch.dict(os.environ,{"QUATTRO_NATIVE_HOST":"codex"}), closing(McpRuntime(wide)) as runtime:
            self.assertFalse(handle(message,runtime)["result"]["isError"])
            fact.unlink()
            other.rmdir()
            self.assertTrue(handle(message,runtime)["result"]["isError"])
        # Exercise native.main's real exception-to-terminal-receipt boundary.
        failed = subprocess.run([sys.executable,"-m","quattro_core.native","--config",str(path),"--host","omp","call"],
            input=json.dumps(request),capture_output=True,text=True,timeout=20,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).parents[1]/"src")))
        self.assertEqual(failed.returncode,1)
        for host in ("omp","codex"):
            with closing(Receipts(wide)) as receipts:
                rows = receipts.recent(host,{})["receipts"]
            self.assertEqual({r["status"] for r in rows},{"attempted","ready","unavailable"})
            attempts = {r["id"] for r in rows if r["status"] == "attempted"}
            for row in rows:
                self.assertEqual(row["metadata"]["authorized_sources"],["other"])
                if row["status"] != "attempted":
                    self.assertIn(row["metadata"]["request_id"],attempts)
            with closing(Receipts(self.config)) as receipts:
                self.assertEqual(receipts.recent(host,{})["receipts"],[])

    def test_first_failed_explicit_attempt_remains_intended_and_retryable_by_operator(self):
        self.path.unlink()
        self.source.rmdir()
        with self.assertRaises(ValueError):
            self.service.index_source("code")
        source = self.service.get_index_status()["sources"][0]
        self.assertEqual(source["classification"],"intended_but_inaccessible")
        self.assertIsNone(source["last_success"])
        self.source.mkdir()
        self.path.write_text("RecoveredCanary evidence")
        result = self.service.index_selected(retry_failed=True,dry_run=False)
        self.assertEqual([r["source_id"] for r in result["results"]],["code"])
        self.assertEqual(self.service.search_knowledge("alpha","RecoveredCanary")["total"],1)

    def test_restore_never_certifies_orphaned_source_mappings(self):
        self.service.index_source("code")
        with self.service.connection:
            self.service.connection.execute("DELETE FROM knowledge_sources WHERE source_id='code'")
        source = self.root/"broken-mapping-snapshot"
        backup(self.config,source)
        target = self.root/"broken-mapping-restore"
        with self.assertRaises(ValueError):
            restore(self.config,source,target)
        self.assertFalse((target/"recovery-verified.json").exists())
        self.assertEqual(self.service.connection.execute("SELECT count(*) FROM documents").fetchone()[0],1)

    def test_feedback_export_respects_current_source_allowlist(self):
        other = self.root/"feedback-other"
        other.mkdir()
        (other/"other.md").write_text("OtherFeedbackCanary")
        wide = dataclasses.replace(self.config,sources=(*self.config.sources,Source("other","alpha",other)))
        with closing(KnowledgeService(wide)) as service:
            service.index_source("other")
            result = service.search_knowledge("alpha","OtherFeedbackCanary",source_ids=["other"])["results"][0]
            record(service,"alpha",result["id"],"relevant")
            self.assertEqual(export(service,"alpha")["feedback"][0]["source_id"],"other")
        self.assertEqual(export(self.service,"alpha")["feedback"],[])

    def test_doctor_keeps_confirmed_history_separate_from_latest_unconfirmed_delivery(self):
        with closing(Receipts(self.config)) as receipts:
            metadata = {"authorized_scope":["alpha"],"authorized_sources":["code"],"result_count":1}
            old = receipts.record("omp",{"session_id":"earlier"},"alpha","context","ready",metadata)
            receipts.delivered("omp",{"session_id":"earlier","receipt_id":old["id"],"boundary":"omp_context_messages"})
            latest = receipts.record("omp",{"session_id":"later"},"alpha","context","ready",metadata)
        state = diagnose(self.config,self.config_path,project="alpha")["integrations"]["omp"]
        self.assertEqual((state["latest_receipt"],state["delivery"]),(latest["id"],"unverified"))
        self.assertEqual(state["last_confirmed_delivery"]["receipt_id"],old["id"])
        self.assertEqual(state["last_confirmed_delivery"]["boundary"],"omp_context_messages")
        self.assertEqual(state["last_end_to_end_check"],"not_observed")


if __name__ == "__main__":
    unittest.main()
