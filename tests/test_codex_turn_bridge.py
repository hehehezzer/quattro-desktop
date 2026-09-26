"""Hermetic native-protocol boundary checks; no providers or credentials."""
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.codex_turn_bridge import CodexTurnBridge


BACKEND = '''import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if r.get("method")=="turn/start":
  print(json.dumps({"id":r["id"],"result":{"observed":r["params"]}}),flush=True)
  print(json.dumps({"method":"turn/completed","params":{"threadId":r["params"]["threadId"],"turn":{"id":"backend","status":"completed","items":[]}}}),flush=True)
 elif "id" in r:
  print(json.dumps({"id":r["id"],"result":{"method":r.get("method")}}),flush=True)
'''


class Gate:
    def __init__(self, decision="DIRECT", sensitive=False):
        self.decision = decision
        self.sensitive = sensitive
        self.finished = []
        self.calls = []

    def begin(self, thread_id, prompt, frontend, params):
        self.calls.append((thread_id, prompt, frontend))
        return SimpleNamespace(decision=self.decision, sensitive=self.sensitive, turn_id="direct-turn",
                               plan=SimpleNamespace(plan_id="plan-1", reasoning_effort="low",
                                                    target=SimpleNamespace(route="exact/route")))

    def direct(self, turn):
        return "Direct answer"

    def finish(self, turn, **kwargs):
        self.finished.append(kwargs)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gate = Gate()
        self.bridge = CodexTurnBridge(Path(self.tmp.name) / "bridge.sock",
                                      [sys.executable, "-u", "-c", BACKEND], {}, self.gate)
        self.errors = []
        def run():
            try:
                self.bridge.run()
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=run)
        self.worker.start()
        self.assertTrue(self.bridge.ready.wait(5))
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(str(self.bridge.socket_path))
        self.stream = self.sock.makefile("rwb", buffering=0)
        self.stream.write(b"GET /rpc HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: MDEyMzQ1Njc4OWFiY2RlZg==\r\n\r\n")
        headers = b""
        while not headers.endswith(b"\r\n\r\n"):
            headers += self.stream.read(1)
        self.assertIn(b"101 Switching Protocols", headers)

    def tearDown(self):
        self.stream.close()
        self.sock.close()
        self.worker.join(7)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.errors, [])
        self.tmp.cleanup()

    def send(self, method, params=None, request_id=1):
        raw = json.dumps({"id":request_id,"method":method,"params":params or {}}).encode()
        header = b"\x81" + (bytes([128 | len(raw)]) if len(raw) < 126 else b"\xfe" + struct.pack("!H", len(raw)))
        self.stream.write(header + b"mask" + bytes(b ^ b"mask"[i % 4] for i, b in enumerate(raw)))

    def receive(self):
        header = self.stream.read(2)
        size = header[1] & 127
        if size == 126:
            size = struct.unpack("!H", self.stream.read(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self.stream.read(8))[0]
        data = b""
        while len(data) < size:
            data += self.stream.read(size - len(data))
        return json.loads(data)

    def test_direct_has_native_events_without_backend_generation(self):
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Explain recursion"}]})
        messages = []
        while True:
            message = self.receive()
            messages.append(message)
            if message.get("method") == "turn/completed":
                break
        self.assertEqual(messages[0]["result"]["turn"]["id"], "direct-turn")
        self.assertEqual([m.get("method") for m in messages[1:]], [
            "turn/started", "item/started", "item/agentMessage/delta", "item/completed", "turn/completed"])
        self.assertEqual(messages[-1]["params"]["turn"]["status"], "completed")
        self.assertEqual(self.gate.calls, [("thread-1", "Explain recursion", "codex")])

    def test_delegate_locks_model_and_collaboration_settings(self):
        self.gate.decision = "DELEGATE"
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Fix bug"}],
                                 "model":"unapproved", "effort":"ultra",
                                 "collaborationMode":{"mode":"default","settings":{"model":"other","reasoning_effort":"ultra"}}})
        actual = self.receive()["result"]["observed"]
        self.assertEqual(actual["model"], "exact/route")
        self.assertEqual(actual["effort"], "low")
        self.assertEqual(actual["responsesapiClientMetadata"]["quattro_plan_id"], "plan-1")
        self.assertEqual(actual["collaborationMode"]["settings"]["model"], "exact/route")
        self.assertEqual(self.receive()["method"], "turn/completed")

    def test_steering_cannot_bypass_fresh_plan(self):
        self.send("turn/steer", {"threadId":"thread-1","input":[{"type":"text","text":"Other task"}]})
        self.assertIn("error", self.receive())
        self.assertEqual(self.gate.calls, [])

    def test_other_protocol_requests_pass_through(self):
        self.send("thread/resume", {"threadId":"thread-1"})
        self.assertEqual(self.receive()["result"]["method"], "thread/resume")

    def test_sensitive_direct_skips_history_rpc(self):
        self.gate.sensitive = True
        def forbidden(*args):
            raise AssertionError("sensitive history must not persist")
        self.bridge._rpc = forbidden
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Synthetic sensitive request"}]})
        while True:
            message = self.receive()
            if message.get("method") == "turn/completed":
                self.assertEqual(message["params"]["turn"]["status"], "completed")
                break

    def test_unsupported_execution_paths_are_closed(self):
        for method in ("thread/queue/add", "thread/compact/start", "review/start",
                       "thread/realtime/start", "thread/shellCommand", "turn/settings/update"):
            self.send(method, {"threadId": "thread-1"})
            self.assertIn("error", self.receive())
        self.assertEqual(self.gate.calls, [])

    def test_attachments_are_not_silently_ignored(self):
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"localImage","path":"/synthetic.png"}]})
        self.assertIn("error", self.receive())
        self.assertEqual(self.gate.calls, [])

    def test_gate_failure_does_not_reach_backend(self):
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic provider diagnostic")
        self.gate.begin = fail
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Explain"}]})
        result = self.receive()
        self.assertIn("error", result)
        self.assertNotIn("synthetic provider diagnostic", json.dumps(result))

    def test_same_thread_concurrency_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        original = self.gate.direct
        def direct(turn):
            entered.set()
            release.wait(4)
            return original(turn)
        self.gate.direct = direct
        params = {"threadId":"thread-1","input":[{"type":"text","text":"Explain"}]}
        self.send("turn/start", params)
        self.assertTrue(entered.wait(4))
        self.receive()
        self.receive()
        self.send("turn/start", params, 2)
        self.assertIn("error", self.receive())
        release.set()
        while self.receive().get("method") != "turn/completed":
            pass

    def test_private_history_is_bounded_and_merged_on_resume(self):
        self.bridge.history_root = Path(self.tmp.name) / "history"
        thread_id = "0199b724-06b7-7000-8000-000000000002"
        turn_id = "0199b724-06b7-7000-8000-000000000001"
        wire = {"id":turn_id,"status":"completed","startedAt":10,"completedAt":11,
                "items":[{"type":"agentMessage","id":"answer","text":"Public answer","phase":"final_answer"}]}
        self.bridge._save_history(thread_id, wire, "Public question")
        path = self.bridge.history_root / (thread_id + ".json")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        result = {"thread":{"id":thread_id,"turns":[]}}
        self.bridge._merge_history("thread/resume", {"threadId":thread_id}, result)
        self.assertEqual(result["thread"]["turns"][0]["items"][1]["text"], "Public answer")
        self.send("thread/items/list", {"threadId":thread_id,"turnId":turn_id})
        self.assertEqual(len(self.receive()["result"]["data"]), 2)

    def test_private_history_rejects_path_and_symlink(self):
        self.bridge.history_root = Path(self.tmp.name) / "history"
        self.assertIsNone(self.bridge._history_path("../../outside"))
        self.bridge.history_root.symlink_to(Path(self.tmp.name))
        with self.assertRaises(ValueError):
            self.bridge._history_path("0199b724-06b7-7000-8000-000000000002")

    def test_direct_history_pagination_does_not_duplicate(self):
        self.bridge.history_root = Path(self.tmp.name) / "history"
        thread_id = "0199b724-06b7-7000-8000-000000000002"
        for ident, timestamp in [("0199b724-06b7-7000-8000-000000000001", 25),
                                 ("0199b724-06b7-7000-8000-000000000003", 5)]:
            self.bridge._save_history(thread_id, {"id":ident,"status":"completed","startedAt":timestamp,
                "completedAt":timestamp,"items":[{"type":"agentMessage","id":ident,"text":"Answer"}]}, "Question")
        first = {"data":[{"id":"native","startedAt":20}],"nextCursor":"next"}
        self.bridge._merge_history("thread/turns/list", {"threadId":thread_id}, first)
        self.assertEqual([r["startedAt"] for r in first["data"]], [25,20])
        last = {"data":[{"id":"native-old","startedAt":10}],"nextCursor":None}
        self.bridge._merge_history("thread/turns/list", {"threadId":thread_id,"cursor":"next"}, last)
        self.assertEqual([r["startedAt"] for r in last["data"]], [10,5])

    def test_cancel_direct_prevents_answer_delivery(self):
        entered = threading.Event()
        release = threading.Event()
        def direct(turn):
            entered.set()
            release.wait(4)
            return "Must not display"
        self.gate.direct = direct
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Explain"}]})
        self.assertTrue(entered.wait(4))
        self.assertIn("result", self.receive())
        self.assertEqual(self.receive()["method"], "turn/started")
        self.send("turn/interrupt", {"threadId":"thread-1", "turnId":"direct-turn"}, 2)
        self.assertEqual(self.receive(), {"id":2,"result":{}})
        release.set()
        self.assertEqual(self.receive()["params"]["turn"]["status"], "interrupted")

    def test_real_gate_cancellation_exception_completes_as_interrupted(self):
        from quattro_agent.turn_gate import TurnGate

        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original_begin, original_finish = self.gate.begin, self.gate.finish

        def begin(*args, **kwargs):
            turn = original_begin(*args, **kwargs)
            turn.cancel_event = threading.Event()
            turn.budget = None
            turn.socket = None
            turn.connection = None
            return turn

        def direct(turn):
            entered.set()
            release.wait(4)
            # Exercise the production exception raised after cancel(), rather
            # than a fake direct function returning normally on interruption.
            TurnGate.remaining(self.gate, turn)
            raise AssertionError("cancelled turn must not produce an answer")

        def finish(turn, **kwargs):
            original_finish(turn, **kwargs)
            finished.set()

        self.gate.begin, self.gate.direct, self.gate.finish = begin, direct, finish
        self.gate.cancel = lambda turn: TurnGate.cancel(self.gate, turn)
        self.send("turn/start", {"threadId":"thread-1","input":[{"type":"text","text":"Explain"}]})
        self.assertTrue(entered.wait(4))
        self.assertIn("result", self.receive())
        self.assertEqual(self.receive()["method"], "turn/started")
        self.send("turn/interrupt", {"threadId":"thread-1","turnId":"direct-turn"}, 2)
        self.assertEqual(self.receive(), {"id":2,"result":{}})
        release.set()
        completed = self.receive()
        self.assertEqual(completed["method"], "turn/completed")
        self.assertEqual(completed["params"]["turn"]["status"], "interrupted")
        self.assertIsNone(completed["params"]["turn"]["error"])
        self.assertTrue(finished.wait(2))
        self.assertEqual(self.gate.finished[-1], {
            "status":"interrupted", "tools_used":False, "agent_lifecycle":False,
        })


if __name__ == "__main__":
    unittest.main()
