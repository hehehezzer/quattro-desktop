"""Native scope, delivery attribution, privacy and concurrent-reader regressions."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
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
from quattro_core.native import execute, project_for
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
