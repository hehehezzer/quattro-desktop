"""Consumer-visible independent CLI/MCP contracts; no agent runtime or mocks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import subprocess
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"


class StdioClient:
    def __init__(self, config: Path) -> None:
        env = dict(os.environ, PYTHONPATH=str(SRC))
        self.process = subprocess.Popen([sys.executable, "-m", "quattro_intelligence_mcp", "--config", str(config)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=env)
        self.sequence = 0
        self.responses = queue.Queue()
        self.reader = threading.Thread(target=self._read_responses, daemon=True)
        self.reader.start()

    def _read_responses(self):
        try:
            for line in self.process.stdout:
                self.responses.put(line)
        finally:
            self.responses.put(None)

    def raw(self, payload: bytes) -> dict:
        try:
            self.process.stdin.write(payload + b"\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            pass  # A rejected oversized frame can close input after queuing its error.
        try:
            line = self.responses.get(timeout=10)
        except queue.Empty:
            self.process.kill()
            self.process.wait(timeout=10)
            raise AssertionError("MCP response timed out") from None
        if not line:
            raise AssertionError("MCP server closed without a response")
        return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.sequence += 1
        value = {"jsonrpc": "2.0", "id": self.sequence, "method": method}
        if params is not None:
            value["params"] = params
        response = self.raw(json.dumps(value).encode())
        if response.get("id") != self.sequence:
            raise AssertionError("MCP response correlation mismatch")
        return response

    def call(self, name: str, **arguments) -> dict:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise AssertionError(response)
        return response["result"]

    def close(self) -> None:
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        timed_out = False
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.process.kill()
            self.process.wait(timeout=10)
        finally:
            self.reader.join(timeout=10)
            stderr = self.process.stderr.read().decode()
            self.process.stdout.close()
            self.process.stderr.close()
        if timed_out:
            raise AssertionError("MCP process did not terminate")
        if self.process.returncode != 0:
            raise AssertionError("MCP process failed: " + stderr)


class CoreInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "intelligence.json"
        self.db = self.root / "db"
        self.repo = self.root / "repository"
        self.repo.mkdir()
        (self.repo / "FACT.md").write_text("The silver otter opens the copper gate.\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "FACT.md"], check=True)
        self.cli("config-init", "--database-dir", str(self.db), "--project", "alpha", "--project", "beta", "--principal", "alice", "--writable")
        self.cli("register-source", "--project", "alpha", "--id", "repo", "--root", str(self.repo))

    def cli(self, *args: str, input: str | None = None, ok: bool = True, config: Path | None = None):
        result = subprocess.run([sys.executable, "-m", "quattro_core.cli", "--config", str(config or self.config), *args],
                                input=input, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, PYTHONPATH=str(SRC)))
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def client(self, config: Path | None = None) -> StdioClient:
        client = StdioClient(config or self.config)
        self.addCleanup(client.close)
        return client

    def native(self, request, config: Path | None = None):
        process = subprocess.run(
            [sys.executable, "-m", "quattro_core.native", "--config", str(config or self.config),
             "--host", "omp", "call"],
            input=json.dumps(request), capture_output=True, text=True, timeout=20,
            env=dict(os.environ, PYTHONPATH=str(SRC)))
        self.assertEqual(process.stderr, "")
        return process.returncode, json.loads(process.stdout)

    def test_native_and_stdio_fact_correction_preserve_both_identities(self) -> None:
        client = self.client()
        old = client.call("save_memory", project="alpha", content="Signer is isolated.",
                          fact_key="product_signer_live_tmpfs_export")["structuredContent"]
        arguments = {"project": "alpha", "content": "Release is activated.",
                     "fact_key": "product_release_activation", "supersedes": old["id"]}
        cli_rejected = self.cli("memory", "save", "--project", "alpha",
                                "--content", arguments["content"], "--fact-key", arguments["fact_key"],
                                "--supersedes", old["id"], ok=False)
        self.assertIn("fact_identity_mismatch", cli_rejected.stderr)
        self.assertNotIn(arguments["content"], cli_rejected.stderr)
        rejected = client.call("save_memory", **arguments)
        exit_code, native = self.native({"cwd": str(self.repo), "session_id": "rejection-smoke",
                                         "name": "save_memory", "arguments": arguments})
        self.assertEqual(exit_code, 1)
        self.assertTrue(rejected["isError"])
        for field in ("status", "code", "message", "details"):
            self.assertEqual(native[field], rejected["structuredContent"][field])
        self.assertEqual(native["code"], "fact_identity_mismatch")
        self.assertEqual(native["status"], "conflict")
        self.assertIn(native["message"], native["summary"])
        unchanged = client.call("recall_memory", project="alpha", historical=True)["structuredContent"]
        self.assertEqual(unchanged["total"], 1)
        self.assertEqual(unchanged["results"][0]["id"], old["id"])
        self.assertEqual(unchanged["results"][0]["state"], "active")
        self.assertEqual(unchanged["results"][0]["revision"], old["revision"])
        arguments.pop("supersedes")
        exit_code, corrected = self.native({"cwd": str(self.repo), "session_id": "correction-smoke",
                                            "name": "save_memory", "arguments": arguments})
        self.assertEqual(exit_code, 0)
        self.assertEqual(corrected["status"], "ready")
        memories = client.call("recall_memory", project="alpha", historical=True)["structuredContent"]["results"]
        self.assertEqual({memory["fact_key"] for memory in memories}, {old["fact_key"], arguments["fact_key"]})
        self.assertTrue(all(memory["state"] == "active" for memory in memories))

    def test_native_config_failure_and_invalid_request_are_distinct(self) -> None:
        invalid = self.root / "invalid.json"
        invalid.write_text('{"private-configuration-marker":', encoding="utf-8")
        request = {"cwd": str(self.repo), "name": "recall_memory", "arguments": {"project": "alpha"}}
        exit_code, unavailable = self.native(request, invalid)
        self.assertEqual(exit_code, 1)
        self.assertEqual((unavailable["status"], unavailable["code"]), ("unavailable", "operation_unavailable"))
        self.assertNotIn("private-configuration-marker", json.dumps(unavailable))
        self.assertNotIn(str(invalid), json.dumps(unavailable))
        mcp = subprocess.run([sys.executable, "-m", "quattro_intelligence_mcp", "--config", str(invalid)],
                             input="", capture_output=True, text=True, timeout=20,
                             env=dict(os.environ, PYTHONPATH=str(SRC)))
        self.assertNotEqual(mcp.returncode, 0)
        self.assertEqual(mcp.stdout, "")
        self.assertNotIn("private-configuration-marker", mcp.stderr)
        self.assertNotIn(str(invalid), mcp.stderr)
        for malformed in ([], {"cwd": str(self.repo), "name": "save_memory", "arguments": []}):
            exit_code, rejected = self.native(malformed)
            self.assertEqual(exit_code, 1)
            self.assertEqual((rejected["status"], rejected["code"]), ("invalid_request", "invalid_arguments"))

    def test_native_credential_and_permission_rejections_remain_failed(self) -> None:
        synthetic = "api_key=" + "example-not-a-real-key-" * 4
        for arguments, expected in (
            ({"project": "alpha", "content": synthetic}, ("invalid_request", "invalid_arguments")),
            ({"project": "alpha", "content": "Verification authority marker.", "verification": "verified"}, ("forbidden", "permission_denied")),
            ({"project": "private-unregistered-project", "content": "Namespace marker."}, ("forbidden", "permission_denied")),
        ):
            exit_code, result = self.native({"cwd": str(self.repo), "name": "save_memory", "arguments": arguments})
            self.assertEqual(exit_code, 1)
            self.assertEqual((result["status"], result["code"]), expected)
            self.assertEqual(result["receipt"]["status"], expected[0])
            self.assertEqual(result["receipt"]["error_code"], expected[1])
            self.assertNotIn(arguments["content"], json.dumps(result))
            self.assertNotIn("private-unregistered-project", json.dumps(result))
        client = self.client()
        self.assertEqual(client.call("recall_memory", project="alpha", historical=True)["structuredContent"]["total"], 0)

    def test_stdio_discovery_initialize_ping_and_strict_protocol(self) -> None:
        client = self.client()
        initialized = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "quattro-intelligence-core")
        self.assertEqual(client.request("ping")["result"], {})
        tools = client.request("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"search_knowledge", "get_project_context", "index_source", "get_index_status", "save_memory", "recall_memory", "update_memory", "invalidate_memory", "delete_memory"})
        self.assertTrue(all(t["inputSchema"]["additionalProperties"] is False for t in tools))
        for malformed in (b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}', b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}', b'not-json'):
            self.assertEqual(client.raw(malformed)["error"]["code"], -32700)
        self.assertEqual(client.request("unknown-private-string")["error"]["message"], "Method not found")
        self.assertEqual(client.request("ping", {"extra": "private"})["error"]["code"], -32602)

    def test_mcp_schema_auth_project_and_safe_error_boundaries(self) -> None:
        client = self.client()
        for name, args in (
            ("save_memory", {"project": "alpha", "content": "public fact", "author": "mallory"}),
            ("save_memory", {"project": "alpha", "content": "fact", "verification": "verified"}),
            ("save_memory", {"project": "alpha", "content": "fact", "confidence": True}),
            ("save_memory", {"project": "alpha", "content": "x" * 16385}),
            ("save_memory", {"project": "alpha", "content": "fact", "category": "unknown"}),
            ("recall_memory", {"project": "alpha", "limit": True}),
            ("recall_memory", {"project": "alpha", "limit": 51}),
            ("get_index_status", {"project": "forbidden"}),
            ("search_knowledge", {"project": "beta", "query": "copper", "source_ids": ["repo"]}),
            ("index_source", {"source_id": "repo", "root": "arbitrary-private-path"}),
            ("index_source", {"source_id": "arbitrary-private-path"}),
            ("rtk_run", {"command": ["private"]}),
        ):
            result = client.call(name, **args)
            self.assertTrue(result["isError"], (name, args))
            self.assertNotIn("arbitrary-private-path", json.dumps(result))
            self.assertNotIn("mallory", json.dumps(result))
        self.assertFalse(client.call("save_memory", project="alpha", content="safe principal fact")["isError"])

    def test_persistence_private_principal_and_revision_lifecycle(self) -> None:
        client = StdioClient(self.config)
        try:
            saved = client.call("save_memory", project="alpha", content="The silver otter remembers copper.", visibility="private")["structuredContent"]
            memory_id = saved["id"]
            self.assertEqual(saved["author"], "alice")
        finally:
            client.close()
        restarted = self.client()
        recalled = restarted.call("recall_memory", project="alpha", query="silver", limit=1, offset=0)["structuredContent"]
        self.assertEqual(recalled["results"][0]["id"], memory_id)
        self.assertEqual(recalled["total"], 1)
        self.assertEqual(recalled["limit"], 1)
        self.assertEqual(recalled["offset"], 0)
        self.assertEqual(restarted.call("recall_memory", project="beta", query="silver")["structuredContent"]["total"], 0)
        other_config = self.root / "bob.json"
        data = json.loads(self.config.read_text())
        data["principal"] = "bob"
        other_config.write_text(json.dumps(data))
        bob = self.client(other_config)
        self.assertEqual(bob.call("recall_memory", project="alpha")["structuredContent"]["total"], 0)
        for name, extra in (("update_memory", {"patch": {"content": "not mine"}}), ("invalidate_memory", {"reason": "not mine"}), ("delete_memory", {})):
            rejection = bob.call(name, project="alpha", id=memory_id, **extra)
            self.assertTrue(rejection["isError"])
            self.assertEqual(rejection["structuredContent"]["status"], "not_found")
            self.assertEqual(rejection["structuredContent"]["code"], "memory_not_found")
            self.assertNotIn("details", rejection["structuredContent"])
            self.assertNotIn(memory_id, json.dumps(rejection))
        revision = saved["revision"]
        self.assertFalse(restarted.call("update_memory", project="alpha", id=memory_id, patch={"content": "The silver otter remembers bronze.", "expected_revision": revision})["isError"])
        self.assertTrue(restarted.call("update_memory", project="alpha", id=memory_id, patch={"content": "stale", "expected_revision": revision})["isError"])
        self.assertFalse(restarted.call("invalidate_memory", project="alpha", id=memory_id, reason="outdated")["isError"])
        self.assertEqual(restarted.call("recall_memory", project="alpha")["structuredContent"]["total"], 0)
        self.assertEqual(restarted.call("recall_memory", project="alpha", historical=True)["structuredContent"]["total"], 1)
        self.assertFalse(restarted.call("delete_memory", project="alpha", id=memory_id)["isError"])
        self.assertEqual(restarted.call("recall_memory", project="alpha", historical=True)["structuredContent"]["total"], 0)

    def test_read_only_default_and_verified_permission(self) -> None:
        readonly = self.root / "readonly.json"
        self.cli("config-init", "--database-dir", str(self.db), "--project", "alpha", config=readonly)
        reader = self.client(readonly)
        self.assertFalse(reader.call("recall_memory", project="alpha")["isError"])
        self.assertTrue(reader.call("save_memory", project="alpha", content="not allowed")["isError"])
        self.assertTrue(reader.call("delete_memory", project="alpha", id="missing")["isError"])
        self.cli("memory", "save", "--project", "alpha", "--content", "not allowed", config=readonly, ok=False)
        data = json.loads(self.config.read_text())
        data["can_verify"] = True
        verified = self.root / "verified.json"
        verified.write_text(json.dumps(data))
        verifier = self.client(verified)
        denied = verifier.call("save_memory", project="alpha", content="Fact without provenance", verification="verified")
        self.assertTrue(denied["isError"])
        accepted = verifier.call("save_memory", project="alpha", content="Fact with provenance", verification="verified", references=["FACT.md"])
        self.assertFalse(accepted["isError"])
        verified_id = accepted["structuredContent"]["id"]
        plain = self.client()
        self.assertTrue(plain.call("update_memory", project="alpha", id=verified_id,
                                   patch={"content": "Changed without verification authority"})["isError"])
        self.assertFalse(plain.call("update_memory", project="alpha", id=verified_id,
                                    patch={"verification": "unverified"})["isError"])

    def test_operator_commands_retrieval_budget_backup_and_migration(self) -> None:
        self.cli("index", "repo")
        self.cli("reindex", "repo")
        query = self.cli("query", "--project", "alpha", "silver otter", "--source-id", "repo", "--limit", "1")
        self.assertTrue(query["results"])
        self.assertEqual(query["limit"], 1)
        context = self.cli("context", "--project", "alpha", "silver otter", "--budget", "2000")
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode()), 2000)
        mcp = self.client()
        self.assertFalse(mcp.call("search_knowledge", project="alpha", query="silver otter", source_ids=["repo"])["isError"])
        self.assertFalse(mcp.call("get_project_context", project="alpha", query="silver otter", budget=2000)["isError"])
        self.assertFalse(mcp.call("get_index_status", project="alpha")["isError"])
        self.cli("index-status", "--project", "alpha")
        self.cli("index-status")
        self.cli("health")
        self.cli("diagnostics")
        saved = self.cli("memory", "save", "--project", "alpha", "--stdin", input="Operator silver otter memory")
        memory_id = saved["id"]
        self.assertEqual(self.cli("memory", "recall", "--project", "alpha", "silver")["total"], 1)
        self.cli("memory", "stats")
        content_file = self.root / "content.txt"
        content_file.write_text("Operator updated otter memory")
        self.cli("memory", "update", "--project", "alpha", memory_id, "--file", str(content_file))
        large_file = self.root / "large.txt"
        large_file.write_text("bounded operator memory " * 800)
        large = self.cli("memory", "save", "--project", "alpha", "--file", str(large_file))
        self.assertGreater(len(large["content"]), 16384)
        self.cli("memory", "delete", "--project", "alpha", large["id"])
        patch_file = self.root / "patch.json"
        patch_file.write_text(json.dumps({"tags": ["operator"], "expected_revision": 2}))
        self.cli("memory", "update", "--project", "alpha", memory_id, "--patch", str(patch_file))
        self.cli("memory", "invalidate", "--project", "alpha", memory_id, "--reason", "changed")
        self.cli("memory", "delete", "--project", "alpha", memory_id)
        backup = self.root / "backup"
        self.assertEqual(set(self.cli("backup", str(backup))["backed_up"]), {"memory.sqlite3", "retrieval.sqlite3"})
        migrated = self.root / "migrated.json"
        self.cli("config-init", "--database-dir", str(self.root / "migrated-db"), "--project", "alpha", "--writable", config=migrated)
        self.cli("migrate", str(backup / "retrieval.sqlite3"), config=migrated)
        self.assertTrue((self.root / "migrated-db" / "retrieval.sqlite3").is_file())

    def test_project_restrictions_apply_to_aggregate_status_and_stats(self) -> None:
        self.cli("memory", "save", "--project", "beta", "--content", "Beta-only memory")
        narrow = self.root / "narrow.json"
        data = json.loads(self.config.read_text())
        data["projects"] = ["alpha"]
        narrow.write_text(json.dumps(data))
        self.assertEqual(set(self.cli("memory", "stats", config=narrow)["projects"]), {"alpha"})
        self.assertEqual(set(self.cli("index-status", config=narrow)["projects"]), {"alpha"})
        client = self.client(narrow)
        self.assertTrue(client.call("recall_memory", project="beta")["isError"])
        self.assertTrue(client.call("get_index_status", project="beta")["isError"])

    def test_oversized_frames_close_safely_and_secret_memory_is_rejected(self) -> None:
        client = StdioClient(self.config)
        try:
            response = client.raw(b"x" * 65537)
            self.assertEqual(response["error"]["message"], "Request exceeds size limit")
        finally:
            client.close()
        client = self.client()
        synthetic = "api_key=" + "example-not-a-real-key-" * 4
        rejected = client.call("save_memory", project="alpha", content=synthetic)
        self.assertTrue(rejected["isError"])
        self.assertEqual(rejected["structuredContent"]["status"], "invalid_request")
        self.assertEqual(rejected["structuredContent"]["code"], "invalid_arguments")
        self.assertNotIn(synthetic, json.dumps(rejected))

    def test_cli_errors_never_echo_input_and_help_is_independent(self) -> None:
        result = self.cli("memory", "save", "--project", "hidden-private-project", "--content", "private arbitrary content", ok=False)
        self.assertNotIn("private arbitrary content", result.stderr)
        self.assertNotIn("hidden-private-project", result.stderr)
        rejected = self.cli("memory", "save", "--project", "alpha", "--content", "private", "--verification", "private-invalid-value", ok=False)
        self.assertNotIn("private-invalid-value", rejected.stderr)
        help_result = subprocess.run([sys.executable, "-m", "quattro_core.cli", "--help"], capture_output=True, text=True,
                                     env=dict(os.environ, PYTHONPATH=str(SRC)), timeout=10)
        self.assertEqual(help_result.returncode, 0)
        for command in ("config-init", "register-source", "serve", "diagnostics", "reindex", "backup", "migrate", "memory"):
            self.assertIn(command, help_result.stdout)


if __name__ == "__main__":
    unittest.main()
