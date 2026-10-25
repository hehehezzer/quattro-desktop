"""Native scope, delivery attribution, privacy and concurrent-reader regressions."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from quattro_core.config import Config, Source
from quattro_core.knowledge import KnowledgeService
from quattro_core.mcp import McpRuntime, handle
from quattro_core.native import execute, main as native_main, project_for
from quattro_core.receipts import Receipts


class NativeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.a,self.b,self.shared = (self.root/name for name in ("a","b","shared"))
        for path in (self.a,self.b,self.shared):
            path.mkdir()
        (self.a/"fact.md").write_text("# Copper journal\nCopper journal commits survive a restart.")
        (self.b/"fact.md").write_text("# Copper journal\nCopper journal belongs only to the unrelated violet tenant.")
        (self.shared/"lesson.md").write_text("# Copper journal\nCopper journal must preserve prior committed evidence.")
        self.config = Config(self.root/"state",(Source("a","alpha",self.a),Source("b","beta",self.b),Source("s","shared",self.shared)),
            ("alpha","beta","shared"),principal="omp",writable=True)
        with closing(KnowledgeService(self.config)) as service:
            for source in ("a","b","s"):
                service.index_source(source)
        self.request = {"cwd":str(self.a),"query":"Copper journal","session_id":"native-session","turn_id":"turn-1","diagnostic":True}

    def native(self, request, config=None, *, raw=None):
        incoming = io.TextIOWrapper(io.BytesIO(raw if raw is not None else json.dumps(request).encode("utf-8")))
        output = io.StringIO()
        with incoming, patch("sys.stdin", incoming), redirect_stdout(output):
            with patch("quattro_core.native.Config.load", return_value=config or self.config):
                code = native_main(["--host", "omp", "call"])
        return code, json.loads(output.getvalue())

    def mcp(self, name, arguments, config=None):
        with patch.dict(os.environ, {"QUATTRO_NATIVE_HOST": "codex"}):
            with closing(McpRuntime(config or self.config)) as runtime:
                return handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": arguments}}, runtime)["result"]

    def assert_failure_receipt(self, receipt, status, code):
        self.assertEqual(receipt["status"], status)
        self.assertEqual(receipt["error_code"], code)
        self.assertEqual(receipt["result_count"], 0)
        self.assertEqual(receipt["delivery"], "unverified")
        self.assertFalse(receipt["stages"]["context_selected"])
        self.assertNotIn("message", receipt)
        self.assertNotIn("details", receipt)

    def test_native_and_mcp_rejections_are_failed_safe_and_consistent(self):
        synthetic = "api_key=" + "synthetic-not-a-real-credential-" * 3
        cases = [
            (replace(self.config, writable=False), {"project": "alpha", "content": "write-denied-marker"}, "forbidden", "permission_denied"),
            (self.config, {"project": "alpha", "content": "verify-denied-marker", "verification": "verified", "references": ["source:a"]}, "forbidden", "permission_denied"),
            (self.config, {"project": "unauthorized-private-project", "content": "namespace-denied-marker"}, "forbidden", "permission_denied"),
            (self.config, {"project": "alpha", "content": synthetic}, "invalid_request", "invalid_arguments"),
            (self.config, {"project": "alpha", "content": "metadata-denied-marker", "metadata": {"note": synthetic}}, "invalid_request", "invalid_arguments"),
            (self.config, {"project": "alpha", "content": "schema-denied-marker", "confidence": True}, "invalid_request", "invalid_arguments"),
        ]
        for config, arguments, status, error_code in cases:
            with self.subTest(status=status, arguments=list(arguments)):
                code, native = self.native(dict(self.request, name="save_memory", arguments=arguments), config)
                mcp = self.mcp("save_memory", arguments, config)
                self.assertEqual(code, 1)
                self.assertTrue(mcp["isError"])
                for field in ("status", "code", "message"):
                    self.assertEqual(native[field], mcp["structuredContent"][field])
                self.assertEqual((native["status"], native["code"]), (status, error_code))
                self.assertIn(error_code, native["summary"])
                self.assertNotIn("details", native)
                for value in (arguments["content"], synthetic, "unauthorized-private-project"):
                    self.assertNotIn(value, json.dumps([native, mcp]))
                self.assert_failure_receipt(native["receipt"], status, error_code)
                if arguments["project"] == "alpha":
                    self.assertEqual(native["receipt"]["authorized_scope"], ["alpha"])
                    self.assertIsNotNone(native["receipt"]["request_id"])
                    self.assert_failure_receipt(mcp["_meta"]["quattro.receipt"], status, error_code)
                else:
                    self.assertEqual(native["receipt"]["authorized_scope"], [])
        with closing(KnowledgeService(self.config)) as service:
            self.assertEqual(service.memory.recall("alpha", principal="omp", historical=True)["total"], 0)
        with closing(Receipts(self.config)) as receipts:
            dump = "\n".join(receipts.connection.iterdump())
        self.assertNotIn(synthetic, dump)
        self.assertNotIn("-denied-marker", dump)

    def test_fact_mismatch_preserves_lineage_and_guidance_in_legacy_summary(self):
        with closing(KnowledgeService(self.config)) as service:
            old = service.memory.save("alpha", "Signer remains isolated.", author="omp",
                                      fact_key="product_signer_live_tmpfs_export")
            before = "\n".join(service.memory.connection.iterdump())
        arguments = {"project": "alpha", "content": "Release activation is complete.",
                     "fact_key": "product_release_activation", "supersedes": old["id"]}
        code, native = self.native(dict(self.request, name="save_memory", arguments=arguments))
        mcp = self.mcp("save_memory", arguments)
        self.assertEqual(code, 1)
        self.assertTrue(mcp["isError"])
        for field in ("status", "code", "message", "details"):
            self.assertEqual(native[field], mcp["structuredContent"][field])
        self.assertEqual((native["status"], native["code"]), ("conflict", "fact_identity_mismatch"))
        self.assertEqual(native["details"], {"memory_id": old["id"],
                         "existing_fact_key": old["fact_key"], "requested_fact_key": arguments["fact_key"]})
        self.assertIn(native["code"], native["summary"])
        self.assertIn(native["message"], native["summary"])
        for receipt in (native["receipt"], mcp["_meta"]["quattro.receipt"]):
            self.assert_failure_receipt(receipt, "conflict", "fact_identity_mismatch")
            self.assertIsNotNone(receipt["request_id"])
            self.assertEqual(receipt["authorized_scope"], ["alpha"])
            self.assertEqual(receipt["authorized_sources"], [])
            self.assertEqual(receipt["operation"], "save_memory")
        with closing(KnowledgeService(self.config)) as service:
            self.assertEqual("\n".join(service.memory.connection.iterdump()), before)
        with closing(Receipts(self.config)) as receipts:
            dump = "\n".join(receipts.connection.iterdump())
        for sensitive in (arguments["content"], old["id"], old["fact_key"], arguments["fact_key"], native["message"]):
            self.assertNotIn(sensitive, dump)
        corrected = {key: value for key, value in arguments.items() if key != "supersedes"}
        code, saved = self.native(dict(self.request, name="save_memory", arguments=corrected))
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ready")
        with closing(KnowledgeService(self.config)) as service:
            memories = service.memory.recall("alpha", principal="omp", historical=True)["results"]
            self.assertEqual({row["fact_key"] for row in memories}, {old["fact_key"], arguments["fact_key"]})
            self.assertTrue(all(row["state"] == "active" and row["revision"] == 1 for row in memories))

    def test_private_and_missing_supersession_have_identical_safe_rejections(self):
        with closing(KnowledgeService(self.config)) as service:
            private = service.memory.save("alpha", "Private signer marker.", author="other",
                                          visibility="private", fact_key="private_signer_identity")
        failures = []
        for memory_id in (private["id"], "mem_missing"):
            arguments = {"project": "alpha", "content": "Different release marker.",
                         "fact_key": "release_identity", "supersedes": memory_id}
            code, native = self.native(dict(self.request, name="save_memory", arguments=arguments))
            mcp = self.mcp("save_memory", arguments)
            self.assertEqual(code, 1)
            self.assertTrue(mcp["isError"])
            self.assertEqual((native["status"], native["code"]), ("not_found", "memory_not_found"))
            for field in ("status", "code", "message"):
                self.assertEqual(native[field], mcp["structuredContent"][field])
            self.assertNotIn("details", native)
            self.assertNotIn(private["id"], json.dumps([native, mcp]))
            self.assertNotIn(private["fact_key"], json.dumps([native, mcp]))
            failures.append(mcp["structuredContent"])
        self.assertEqual(failures[0], failures[1])

    def test_storage_schema_value_error_is_unavailable_not_caller_invalid(self):
        with closing(sqlite3.connect(self.config.database_dir / "memory.sqlite3")) as connection:
            connection.execute("PRAGMA user_version=99")
        code, result = self.native(dict(self.request, name="recall_memory", arguments={"project": "alpha"}))
        self.assertEqual(code, 1)
        self.assertEqual((result["status"], result["code"]), ("unavailable", "operation_unavailable"))
        self.assert_failure_receipt(result["receipt"], "unavailable", "operation_unavailable")
        self.assertEqual(result["receipt"]["authorized_scope"], ["alpha"])
        self.assertIsNotNone(result["receipt"]["request_id"])
        with closing(sqlite3.connect(self.config.database_dir / "memory.sqlite3")) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_corrupt_stored_json_is_unavailable_but_malformed_input_is_invalid(self):
        with closing(KnowledgeService(self.config)) as service:
            old = service.memory.save("alpha", "Stored record marker.", author="omp")
            with service.memory.connection:
                service.memory.connection.execute("UPDATE memories SET references_json=? WHERE id=?",
                                                  ("corrupt-private-storage-marker", old["id"]))
        code, native = self.native(dict(self.request, name="recall_memory", arguments={"project": "alpha"}))
        mcp = self.mcp("recall_memory", {"project": "alpha"})
        self.assertEqual(code, 1)
        self.assertTrue(mcp["isError"])
        self.assertEqual((native["status"], native["code"]), ("unavailable", "operation_unavailable"))
        for field in ("status", "code", "message"):
            self.assertEqual(native[field], mcp["structuredContent"][field])
        self.assertNotIn("corrupt-private-storage-marker", json.dumps([native, mcp]))
        self.assert_failure_receipt(native["receipt"], "unavailable", "operation_unavailable")
        self.assert_failure_receipt(mcp["_meta"]["quattro.receipt"], "unavailable", "operation_unavailable")
        code, invalid = self.native({}, raw=b'{"private-input-marker":')
        self.assertEqual(code, 1)
        self.assertEqual((invalid["status"], invalid["code"]), ("invalid_request", "invalid_arguments"))
        self.assertNotIn("private-input-marker", json.dumps(invalid))

    def test_runtime_faults_do_not_echo_exception_text(self):
        for error in (RuntimeError("private-runtime-marker"), sqlite3.OperationalError("private-storage-marker"),
                      ValueError("private-value-marker"), TypeError("private-type-marker"),
                      KeyError("private-key-marker"), PermissionError("private-filesystem-marker")):
            with self.subTest(error=type(error).__name__), patch.object(McpRuntime, "call", side_effect=error):
                code, native = self.native(dict(self.request, name="recall_memory", arguments={"project": "alpha"}))
                mcp = self.mcp("recall_memory", {"project": "alpha"})
            self.assertEqual(code, 1)
            self.assertTrue(mcp["isError"])
            self.assertEqual((native["status"], native["code"]), ("unavailable", "operation_unavailable"))
            self.assertNotIn(str(error), json.dumps([native, mcp]))
            for field in ("status", "code", "message"):
                self.assertEqual(native[field], mcp["structuredContent"][field])
            self.assert_failure_receipt(native["receipt"], "unavailable", "operation_unavailable")
            self.assert_failure_receipt(mcp["_meta"]["quattro.receipt"], "unavailable", "operation_unavailable")

    def test_missing_registered_source_root_is_runtime_unavailable(self):
        self.a.rename(self.root / "moved-source")
        request = dict(self.request, cwd=str(self.root), name="index_source", arguments={"source_id": "a"})
        code, native = self.native(request)
        mcp = self.mcp("index_source", {"source_id": "a"})
        self.assertEqual(code, 1)
        self.assertTrue(mcp["isError"])
        self.assertEqual((native["status"], native["code"]), ("unavailable", "operation_unavailable"))
        for field in ("status", "code", "message"):
            self.assertEqual(native[field], mcp["structuredContent"][field])
        self.assertNotIn(str(self.a), json.dumps([native, mcp]))
        for receipt in (native["receipt"], mcp["_meta"]["quattro.receipt"]):
            self.assert_failure_receipt(receipt, "unavailable", "operation_unavailable")
            self.assertEqual(receipt["authorized_scope"], ["alpha"])
            self.assertEqual(receipt["authorized_sources"], ["a"])
            self.assertIsNotNone(receipt["request_id"])

    def test_corrupt_stored_results_and_mutations_are_unavailable_without_changes(self):
        with closing(KnowledgeService(self.config)) as service:
            saved = service.memory.save("alpha", "Stored serialization marker.", author="omp",
                                        fact_key="serialization_fact")
        corruptions = [
            (json.dumps(["private-corruption-marker-\ud800"]), "{}"),
            ("[]", '{"private-corruption-marker":NaN}'),
        ]
        operations = [
            ("recall_memory", {"project": "alpha"}),
            ("invalidate_memory", {"project": "alpha", "id": saved["id"], "reason": "Record is outdated."}),
            ("update_memory", {"project": "alpha", "id": saved["id"],
                               "patch": {"tags": ["reviewed"], "expected_revision": saved["revision"]}}),
            ("save_memory", {"project": "alpha", "content": "Changed serialization fact.",
                             "fact_key": saved["fact_key"], "supersedes": saved["id"]}),
        ]
        for references, metadata in corruptions:
            with closing(sqlite3.connect(self.config.database_dir / "memory.sqlite3")) as connection:
                with connection:
                    connection.execute("UPDATE memories SET references_json=?,metadata_json=? WHERE id=?",
                                       (references, metadata, saved["id"]))
                before = "\n".join(connection.iterdump())
            for name, arguments in operations:
                with self.subTest(references=references, metadata=metadata, operation=name):
                    code, native = self.native(dict(self.request, name=name, arguments=arguments))
                    self.assertEqual(code, 1)
                    with closing(sqlite3.connect(self.config.database_dir / "memory.sqlite3")) as connection:
                        self.assertEqual("\n".join(connection.iterdump()), before)
                    mcp = self.mcp(name, arguments)
                    self.assertTrue(mcp["isError"])
                    for field in ("status", "code", "message"):
                        self.assertEqual(native[field], mcp["structuredContent"][field])
                    self.assertEqual((native["status"], native["code"]), ("unavailable", "operation_unavailable"))
                    self.assertNotIn("private-corruption-marker", json.dumps([native, mcp]))
                    self.assertNotIn(saved["content"], json.dumps([native, mcp]))
                    self.assertNotIn("result", native)
                    for receipt in (native["receipt"], mcp["_meta"]["quattro.receipt"]):
                        self.assert_failure_receipt(receipt, "unavailable", "operation_unavailable")
                        self.assertEqual(receipt["operation"], name)
                        self.assertEqual(receipt["authorized_scope"], ["alpha"])
                        self.assertIsNotNone(receipt["request_id"])
                    with closing(Receipts(self.config)) as receipts:
                        statuses = receipts.connection.execute("SELECT status FROM native_receipts").fetchall()
                    self.assertTrue(all(row["status"] in {"attempted", "unavailable"} for row in statuses))
                    with closing(sqlite3.connect(self.config.database_dir / "memory.sqlite3")) as connection:
                        self.assertEqual("\n".join(connection.iterdump()), before)

    def test_native_envelope_render_failure_returns_safe_failed_json(self):
        for invalid in ("\ud800", float("nan")):
            with self.subTest(kind=type(invalid).__name__):
                with patch("quattro_core.native.execute", return_value={"status": "ready", "summary": invalid}):
                    code, result = self.native(dict(self.request, name="recall_memory", arguments={"project": "alpha"}))
                self.assertEqual(code, 1)
                self.assertEqual((result["status"], result["code"]), ("unavailable", "operation_unavailable"))
                self.assert_failure_receipt(result["receipt"], "unavailable", "operation_unavailable")
                json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def test_automatic_context_combines_only_current_project_and_shared(self):
        result = execute(self.config,"omp","context",self.request)
        contexts = result["context"]["projects"]
        self.assertEqual([context["project"] for context in contexts],["alpha","shared"])
        evidence = [row for context in contexts for row in context["knowledge"]]
        self.assertEqual({row["citation"]["source_id"] for row in evidence},{"a","s"})
        self.assertTrue(all(row["citation"]["provenance"]=="current" for row in evidence))
        self.assertNotIn("violet tenant",json.dumps(result))
        self.assertFalse(result["receipt"]["semantic"]["available"])
        self.assertEqual(result["receipt"]["delivery"],"unverified")

    def test_unknown_directory_is_explicitly_shared_only(self):
        request = dict(self.request,cwd=str(self.root))
        result = execute(self.config,"omp","context",request)
        self.assertIsNone(result["project"])
        self.assertEqual([context["project"] for context in result["context"]["projects"]],["shared"])
        self.assertFalse(result["receipt"]["project_registered"])
        self.assertIn("cwd unregistered",result["summary"])

    def test_prompt_context_does_not_silently_index_modified_sources(self):
        (self.a/"fact.md").write_text("# NewCopperSymbol\nNewCopperSymbol commits survive publication.")
        result = execute(self.config,"omp","context",dict(self.request,query="NewCopperSymbol"))
        current = result["context"]["projects"][0]
        self.assertEqual(current["knowledge"],[])
        self.assertNotIn("NewCopperSymbol",json.dumps(current))
        execute(self.config,"omp","call",dict(self.request,name="index_source",arguments={"source_id":"a"}))
        published = execute(self.config,"omp","context",dict(self.request,query="NewCopperSymbol"))
        self.assertIn("NewCopperSymbol",published["context"]["projects"][0]["knowledge"][0]["content"])

    def test_longest_registered_root_wins_and_symlink_does_not_authorize(self):
        nested = self.a/"nested"
        nested.mkdir()
        config = replace(self.config,sources=(*self.config.sources,Source("nested","beta",nested)))
        self.assertEqual(project_for(config,str(nested)),"beta")
        alias = self.root/"alias"
        alias.symlink_to(self.a,target_is_directory=True)
        with self.assertRaises(ValueError):
            project_for(config,str(alias))

    def test_delivery_requires_matching_host_session_and_real_boundary(self):
        result = execute(self.config,"omp","context",self.request)
        receipt = result["receipt"]["id"]
        delivery = {"receipt_id":receipt,"session_id":"native-session","boundary":"omp_context_messages"}
        for host,request in (("codex",delivery),("omp",dict(delivery,session_id="different-session")),("omp",dict(delivery,boundary="adapter_returned"))):
            with self.assertRaises(ValueError):
                execute(self.config,host,"delivered",request)
        confirmed = execute(self.config,"omp","delivered",delivery)
        self.assertEqual(confirmed["delivery"],"confirmed")
        self.assertEqual(confirmed["model_reliance"],"unknown")
        recent = execute(self.config,"omp","status",{"session_id":"native-session"})["receipts"]
        self.assertEqual(recent[0]["boundary"],"omp_context_messages")
        self.assertEqual(execute(self.config,"omp","status",{"session_id":"different-session"})["receipts"],[])

    def test_receipts_do_not_persist_query_or_source_content(self):
        request = dict(self.request,query="Copper journal private-task-marker-9224")
        execute(self.config,"omp","context",request)
        with closing(Receipts(self.config)) as receipts:
            dump = "\n".join(receipts.connection.iterdump())
        self.assertNotIn("private-task-marker-9224",dump)
        self.assertNotIn("commits survive",dump)
        self.assertNotIn("preserve prior committed",dump)
        self.assertIn("turn-1",dump)

    def test_committed_retrieval_remains_available_during_atomic_index_write(self):
        writer = sqlite3.connect(self.config.database_dir/"retrieval.sqlite3")
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE documents SET content='Uncommitted evidence must stay invisible' WHERE repository='alpha'")
        with closing(KnowledgeService(replace(self.config,writable=False))) as reader:
            result = reader.search_knowledge("alpha","Copper journal")
            self.assertIn("commits survive",result["results"][0]["content"])
            self.assertNotIn("Uncommitted",json.dumps(result))
        writer.rollback()

    def test_mcp_receipt_preserves_budget_and_does_not_claim_native_delivery(self):
        with patch.dict(os.environ,{"QUATTRO_NATIVE_HOST":"codex","QUATTRO_DIAGNOSTIC":"1"}):
            with closing(McpRuntime(self.config)) as runtime:
                initialized = handle({"jsonrpc":"2.0","id":0,"method":"initialize","params":{
                    "protocolVersion":"2025-06-18","capabilities":{"elicitation":{},"experimental":{}},
                    "clientInfo":{"name":"native-codex","version":"0.158.0","title":"Codex"}}},runtime)
                self.assertNotIn("error",initialized)
                discovered = handle({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{"progressToken":1}}},runtime)
                context_tool = next(tool for tool in discovered["result"]["tools"] if tool["name"]=="get_project_context")
                response = handle({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"_meta":{"progressToken":"context"},"name":context_tool["name"],"arguments":{"project":"alpha","query":"Copper journal","budget":2400}}},runtime)
        result = response["result"]
        self.assertFalse(result["isError"])
        context = result["structuredContent"]
        self.assertLessEqual(len(json.dumps(context,ensure_ascii=False,sort_keys=True).encode()),2400)
        self.assertIn("commits survive",json.dumps(context))
        receipt = result["_meta"]["quattro.receipt"]
        self.assertEqual(receipt["host"],"codex")
        self.assertEqual(receipt["delivery"],"unverified")
        self.assertTrue(receipt["session_id"].startswith("codex-mcp-"))
        self.assertNotIn("receipt",context)

    def test_transport_metadata_cannot_grant_verified_memory_authority(self):
        with closing(McpRuntime(self.config)) as runtime:
            denied = handle({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
                "_meta":{"can_verify":True,"principal":"operator"},
                "name":"save_memory","arguments":{"project":"alpha","content":"transport-authority-marker",
                    "verification":"verified","references":["source:a"]}}},runtime)
            self.assertTrue(denied["result"]["isError"])
            self.assertEqual(runtime.service.memory.recall("alpha",query="transport-authority-marker",principal="omp")["results"],[])


if __name__ == "__main__":
    unittest.main()
