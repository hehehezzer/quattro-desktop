"""Bounded native authoring transport; no provider or native credentials."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent import decision_mcp, shared_intelligence


class DynamicTransportTests(unittest.TestCase):
    def test_rpc_wrapper_has_room_beyond_inner_envelope_bound(self):
        message = {"jsonrpc": "2.0", "id": "synthetic" * 1100,
                   "method": "tools/list"}
        line = json.dumps(message) + "\n"
        self.assertGreater(len(line), 8192)
        self.assertLess(len(line), 16384)
        with (mock.patch.object(sys, "argv", ["decision-mcp"]),
              mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(line.encode()))),
              mock.patch.object(sys, "stdout", io.StringIO()) as output,
              mock.patch.object(decision_mcp, "DecisionSession") as session):
            decision_mcp.main()
            response = json.loads(output.getvalue())
        self.assertEqual(response["id"], message["id"])
        session.return_value.decide.assert_not_called()
        session.return_value.close.assert_called_once()

    def test_private_rpc_rejects_duplicate_keys_without_decision(self):
        line = '{"id":1,"id":2,"method":"tools/call"}\n'
        with (mock.patch.object(sys, "argv", ["decision-mcp"]),
              mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(line.encode()))),
              mock.patch.object(sys, "stdout", io.StringIO()) as output,
              mock.patch.object(decision_mcp, "DecisionSession") as session):
            decision_mcp.main()
            response = json.loads(output.getvalue())
        self.assertIn("error", response)
        session.return_value.decide.assert_not_called()

    def test_shared_server_duplicate_or_oversized_frames_never_dispatch(self):
        for line in ('{"name":"decision_capabilities","name":"rtk_run"}\n',
                     "x" * (128 * 1024 + 1) + '\n{"name":"rtk_run"}\n'):
            with (self.subTest(size=len(line)),
                  mock.patch.object(sys, "stdin", io.StringIO(line)),
                  mock.patch.object(sys, "stdout", io.StringIO()) as output,
                  mock.patch.object(shared_intelligence, "load_native_settings", side_effect=RuntimeError),
                  mock.patch.object(shared_intelligence, "call") as call):
                self.assertEqual(shared_intelligence.server_main(), 0)
                self.assertIn("error", json.loads(output.getvalue()))
            call.assert_not_called()

    def test_direct_native_rpc_duplicate_keys_and_bound(self):
        path = Path(__file__).parents[1] / "src/quattro_intelligence_mcp.py"
        spec = importlib.util.spec_from_file_location("native_dynamic_transport", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for line in ('{"id":1,"id":2,"method":"tools/call"}\n',
                     "x" * 65537 + '\n{"method":"tools/call"}\n'):
            with (self.subTest(size=len(line)),
                  mock.patch.object(sys, "stdin", io.StringIO(line)),
                  mock.patch.object(sys, "stdout", io.StringIO()),
                  mock.patch.object(module, "NativeMcpRuntime") as runtime,
                  mock.patch.object(module, "handle") as handle):
                self.assertEqual(module.main(), 0)
                handle.assert_not_called()
                runtime.return_value.close.assert_called_once()
