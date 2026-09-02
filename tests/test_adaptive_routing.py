from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.adaptive_routing import (
    OmniRouteAdaptiveClient,
    build_adaptive_decision,
    encode_routing_header,
    model_candidates_from_snapshot,
)
from quattro_agent.routing_intelligence import PreferenceMode, profile_task


CAPABILITIES = {
    "schema_version": 1,
    "capabilities": {
        "candidate_snapshot": True,
        "routing_requirements": True,
        "preferred_candidates": True,
        "capability_routing": True,
        "practical_context": True,
        "cost_metadata": True,
        "quota_state": True,
        "routing_diagnostics": True,
        "routing_header_transport": True,
    },
}


def candidate(model: str, *, price: float | None, context: int = 128_000, health: str = "available"):
    return {
        "provider_id": "codex",
        "model_id": model,
        "route": f"codex/{model}",
        "capabilities": {
            "reasoning": True,
            "vision": False,
            "tools": True,
            "execution": {
                "repositoryAccess": True,
                "codeAnalysis": True,
                "codeEditing": True,
                "codeExecution": True,
                "shell": True,
                "git": True,
                "longContext": True,
                "sandbox": "workspace_write",
            },
        },
        "practical_context_limit": context,
        "modalities": {"input": ["text"], "output": ["text"]},
        "pricing": {
            "state": "known" if price is not None else "unknown",
            "input_cost": price,
            "output_cost": price,
            "cached_input_cost": None,
            "currency": "USD",
            "unit": "million_tokens",
        },
        "health_state": health,
        "quota_state": "available",
        "cooldown_state": False,
        "rejection_reasons": [],
    }


class Handler(BaseHTTPRequestHandler):
    calls = {"capabilities": 0, "candidates": 0}
    enhanced = True

    def do_GET(self):
        if self.path == "/api/v1/capabilities":
            self.calls["capabilities"] += 1
            if not self.enhanced:
                self.send_error(404)
                return
            payload = CAPABILITIES
        elif self.path.startswith("/api/v1/routing/candidates?"):
            self.calls["candidates"] += 1
            payload = {
                "schema_version": 1,
                "metadata_version": "test-candidates-1",
                "channel": "auto/coding:cheap",
                "candidates": [candidate("cheap", price=0.5), candidate("strong", price=5.0)],
            }
        else:
            self.send_error(404)
            return
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        return


class AdaptiveRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/api/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        Handler.calls = {"capabilities": 0, "candidates": 0}
        Handler.enhanced = True
        OmniRouteAdaptiveClient.clear_caches()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_negotiation_and_candidate_snapshots_are_bounded_cached(self):
        client = OmniRouteAdaptiveClient(self.base)
        first, first_hit = client.negotiate()
        second, second_hit = client.negotiate()
        self.assertTrue(first.adaptive)
        self.assertTrue(first.header_transport)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(Handler.calls["capabilities"], 1)
        client.candidates("coding:cheap")
        _snapshot, hit = client.candidates("coding:cheap")
        self.assertTrue(hit)
        self.assertEqual(Handler.calls["candidates"], 1)

    def test_standard_endpoint_absence_is_compatible(self):
        Handler.enhanced = False
        negotiation, _ = OmniRouteAdaptiveClient(self.base).negotiate()
        self.assertTrue(negotiation.connected)
        self.assertEqual(negotiation.compatibility, "standard")
        self.assertFalse(negotiation.adaptive)

    def test_real_schema_maps_unknown_price_as_unknown_not_free(self):
        profile = profile_task("fix a typo in README.md")
        snapshot = {
            "candidates": [candidate("unknown-price", price=None)],
        }
        mapped = model_candidates_from_snapshot(snapshot, profile)
        self.assertIsNone(mapped[0].input_cost_per_million)
        self.assertIsNone(mapped[0].output_cost_per_million)

    def test_malformed_candidate_metadata_fails_closed(self):
        profile = profile_task("fix a typo in README.md")
        hostile = candidate("bad", price=1.0)
        hostile["model_id"] = "bad\nheader"
        hostile["route"] = "codex/bad\nheader"
        with self.assertRaisesRegex(ValueError, "identity"):
            model_candidates_from_snapshot({"candidates": [hostile]}, profile)
        boolean_price = candidate("bool-price", price=1.0)
        boolean_price["pricing"]["input_cost"] = True
        with self.assertRaisesRegex(ValueError, "pricing"):
            model_candidates_from_snapshot({"candidates": [boolean_price]}, profile)

    def test_enhanced_decision_orders_cheapest_capable_and_emits_sanitized_envelope(self):
        profile = profile_task("fix a typo in README.md")
        decision = build_adaptive_decision(
            client=OmniRouteAdaptiveClient(self.base),
            profile=profile,
            route="auto/coding:cheap",
            benchmark_path=self.root / "benchmarks.json",
            outcomes_path=self.root / "outcomes.json",
            preference=PreferenceMode.BALANCED,
            task_profile_id="task-test-1",
        )
        self.assertEqual(decision.negotiation.compatibility, "enhanced")
        self.assertEqual(decision.preferred_candidates[0], "codex/cheap")
        self.assertEqual(decision.envelope["task_profile_id"], "task-test-1")
        encoded = encode_routing_header(decision.envelope)
        self.assertNotIn("fix a typo", encoded)
        self.assertNotIn(str(self.root), encoded)


if __name__ == "__main__":
    unittest.main()
