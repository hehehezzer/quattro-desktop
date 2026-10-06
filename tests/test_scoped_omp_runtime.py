"""Hermetic host authority and bounded OMP protocol regression tests."""
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.scoped_omp_runtime import HostBinding, ScopedOMPError, ScopedOMPRuntime, VerifiedSkillCatalog, prepare_private_home, sdk_command


SERVER = r'''
import json, sys
mode = sys.argv[1]
state = {"sessionId":"native-1","model":{"provider":"openai-codex","id":"gpt-6.1-sol"},"thinkingLevel":"medium"}
def send(value):
 print(json.dumps(value), flush=True)
for line in sys.stdin:
 value=json.loads(line); kind=value["type"]
 if kind == "get_state":
  data=state
 elif kind == "set_host_tools":
  data={"toolNames":[tool["name"] for tool in value["tools"]]}
 elif kind == "get_available_commands":
  data={"commands":[{"name":"skill:example","source":"skill"}]}
 elif kind == "host_tool_result":
  if mode == "duplicate":
   send({"type":"host_tool_call","id":"host-1","toolName":"scoped_repo_read","toolCallId":"call-1","arguments":{"path":"file"}})
  if mode == "changed": state["thinkingLevel"]="high"
  send({"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}})
  send({"type":"prompt_result","id":ticket,"status":"completed","sessionSettled":True})
  continue
 elif kind == "prompt":
  ticket=value["id"]
  send({"type":"response","id":ticket,"command":kind,"success":True,"data":{}})
  if mode == "overflow":
   sys.stdout.write("x"*262145); sys.stdout.flush(); continue
  if mode == "wrong_id":
   send({"type":"prompt_result","id":"foreign","status":"completed","sessionSettled":True}); continue
  send({"type":"host_tool_call","id":"host-1","toolName":"scoped_repo_read","toolCallId":"call-1","arguments":{"path":"file"}})
  continue
 else: raise RuntimeError()
 send({"type":"response","id":value["id"],"command":kind,"success":True,"data":data})
'''


@unittest.skipUnless(os.name == "posix", "closed OMP RPC pipe supervision requires Unix")
class ScopedOMPRuntimeTests(unittest.TestCase):
    def catalog(self, root):
        stage = root / "catalog"
        skill = stage / "example"
        skill.mkdir(parents=True)
        original = b"---\nname: original\ndescription: test skill\n---\nOriginal skill instructions\n"
        loader = b"---\nname: example\ndescription: test skill\n---\nOriginal skill instructions\n"
        (skill / "SKILL.md").write_bytes(loader)
        (skill / "SKILL.original.md").write_bytes(original)
        (skill / "reference.txt").write_text("reference data\n")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"version": 1, "roots": {}, "skills": [{"omp_name": "example", "staged": str(skill),
            "files": {"SKILL.md": hashlib.sha256(original).hexdigest(), "reference.txt": hashlib.sha256(b"reference data\n").hexdigest()},
            "staged_loader_sha256": hashlib.sha256(loader).hexdigest()}]}))
        return VerifiedSkillCatalog(manifest, stage, expected_digest=hashlib.sha256(manifest.read_bytes()).hexdigest())

    def runtime(self, root, *, mode="ok", execute=None, tools=True):
        script = root / "server.py"
        script.write_text(SERVER)
        definitions = [{"name": "scoped_repo_read", "label": "Read", "description": "Host read",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                       "required": ["path"], "additionalProperties": False}}] if tools else []
        return ScopedOMPRuntime((sys.executable, str(script), mode), cwd=str(root),
            environment={"HOME": str(root), "PATH": "/usr/bin:/bin"},
            binding=HostBinding("task-1", "host-session-1"), tools=definitions,
            execute=execute or (lambda *args: {"content": [{"type": "text", "text": "read result"}]}), timeout=2)

    def test_host_authority_receives_exact_binding_and_arguments(self):
        calls = []
        def execute(*args):
            calls.append(args)
            return {"content": [{"type": "text", "text": "host result"}]}
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(Path(tmp), execute=execute)
            try:
                bound = runtime.start()
                self.assertEqual(bound, HostBinding("task-1", "host-session-1", "native-1"))
                self.assertEqual(runtime.prompt("Read file")["text"], "done")
                self.assertEqual(calls, [(bound, "scoped_repo_read", {"path": "file"}, "call-1")])
            finally:
                runtime.close()

    def test_protocol_violation_closes_worker_without_second_operation(self):
        for mode in ("duplicate", "changed", "wrong_id", "overflow"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                calls = []
                runtime = self.runtime(Path(tmp), mode=mode, execute=lambda *args: calls.append(args) or {"content": []})
                runtime.start()
                process = runtime._process
                with self.assertRaisesRegex(ScopedOMPError, "closed OMP turn failed"):
                    runtime.prompt("Read file")
                self.assertIsNotNone(process.poll())
                self.assertLessEqual(len(calls), 1)

    def test_unregistered_tool_cannot_reach_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            runtime = self.runtime(Path(tmp), tools=False, execute=lambda *args: calls.append(args))
            runtime.start()
            with self.assertRaises(ScopedOMPError):
                runtime.prompt("Read file")
            self.assertEqual(calls, [])

    def test_denied_host_error_is_redacted(self):
        def denied(*args):
            raise PermissionError("private provider detail")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(Path(tmp), execute=denied)
            try:
                runtime.start()
                self.assertEqual(runtime.prompt("Read file")["status"], "completed")
            finally:
                runtime.close()

    def test_input_cannot_reconfigure_native_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(Path(tmp))
            try:
                runtime.start()
                for value in ("/model different", "!touch file", "^other", "a\0b", "x"*262144):
                    with self.assertRaises(ScopedOMPError):
                        runtime.prompt(value)
            finally:
                runtime.close()

    def test_explicit_environment_and_literal_sdk_paths(self):
        with self.assertRaises(ValueError):
            ScopedOMPRuntime((sys.executable,), cwd="/tmp", environment={"API_KEY": "unused"},
                             binding=HostBinding("task", "session"), tools=[], execute=lambda *args: None)
        argv = sdk_command("/opt/bun", "/opt/sdk", cwd="/tmp/project", agent_dir="/tmp/native", session_dir="/tmp/sessions")
        self.assertEqual(argv[-4:], ("/opt/sdk", "/tmp/project", "/tmp/native", "/tmp/sessions"))
        self.assertNotIn("--no-tools", argv)

    def test_logs_sentinel_blocks_dumps_without_touching_existing_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = prepare_private_home(Path(tmp) / "new-home")
            sentinel = home / ".omp" / "logs"
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                prepare_private_home(home)
            with self.assertRaises(NotADirectoryError):
                (sentinel / "http-400-requests" / "request.json").write_text("synthetic fixture")

    def test_pinned_skill_read_and_exact_command_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = self.catalog(root)
            self.assertEqual(catalog.names, ("example",))
            self.assertTrue(catalog.tool_definition()["readsSkillUris"])
            result = catalog.read({"uri": "skill://example/reference.txt"})
            self.assertEqual(result["content"][0]["text"], "reference data\n")
            self.assertNotIn(str(root), json.dumps(result))
            command = sdk_command("/opt/bun", "/opt/sdk", cwd=str(root), agent_dir="/tmp/native", session_dir="/tmp/sessions", skills_catalog=catalog)
            self.assertEqual(command[-3:], (str(catalog.manifest), str(catalog.root), catalog.expected_digest))
            runtime = self.runtime(root)
            runtime.skills_catalog = catalog
            try:
                runtime.start()
                self.assertEqual(runtime.prompt("/skill:example use reference")["text"], "done")
                for prompt in ("/skill:unknown", "/model example", "/skill:example/escape"):
                    with self.assertRaises(ScopedOMPError):
                        runtime.prompt(prompt)
            finally:
                runtime.close()

    def test_skill_inventory_rejects_escape_and_every_file_drift(self):
        for filename in ("SKILL.md", "SKILL.original.md", "reference.txt", "new.txt"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = self.catalog(root)
                for uri in ("skill://example/../SKILL.md", "skill://example/%2e%2e/secret", "file:///tmp/test", "skill://unknown"):
                    with self.assertRaises(ValueError):
                        catalog.read({"uri": uri})
                (catalog.root / "example" / filename).write_text("changed")
                with self.assertRaises(ValueError):
                    catalog.read({"uri": "skill://example"})

    def test_skill_symlinks_and_manifest_drift_are_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = self.catalog(root)
            path = catalog.root / "example/reference.txt"
            path.unlink()
            path.symlink_to(root / "foreign")
            with self.assertRaises(ValueError):
                catalog.verify()
        with tempfile.TemporaryDirectory() as tmp:
            catalog = self.catalog(Path(tmp))
            catalog.manifest.write_text("{}")
            with self.assertRaises(ValueError):
                catalog.verify()


if __name__ == "__main__":
    unittest.main()
