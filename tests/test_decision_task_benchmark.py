"""Task smoke reports retain host effects without authored decision content."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts/benchmark_decision_tasks.py"
SPEC = importlib.util.spec_from_file_location("decision_task_benchmark", SCRIPT)
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class DecisionTaskBenchmarkTests(unittest.TestCase):
    def test_v2_observation_excludes_authored_ids_context_and_probabilities(self):
        authored = {
            "schema_version": "quattro-jev-decisions-v2", "decision_id": "PrivateDecision",
            "question": "Which next step addresses the available evidence?",
            "options": [
                {"id": "PrivateOption", "description": "Inspect narrowly relevant evidence", "effect": "inspect"},
                {"id": "PrivateFallback", "description": "Continue native model deliberation", "effect": "agent"}],
            "context": {"PrivateParameter": "PrivateValue"},
            "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
            "execution_state": {"revision": 1, "phase": "inspection", "attempt": 0},
            "previous_result": "none"}
        result = {"selected_action": "PrivateOption", "provider_selected_action": "PrivateOption",
                  "confidence": 0.99, "fallback_required": False,
                  "probabilities": {"PrivateOption": 0.99, "PrivateFallback": 0.01},
                  "timing": {"blocking_ms": 2}, "outcome": "ADVISORY"}
        event = {"type": "item.completed", "item": {"type": "mcp_tool_call",
                 "server": "quattro_decisions", "status": "completed", "arguments": authored,
                 "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.jsonl"
            path.write_text(json.dumps(event) + "\n")
            observed = BENCHMARK.parse_output(path)[1]
            self.assertEqual(observed[0]["selected_effect"], "inspect")
            self.assertEqual(observed[0]["decision_schema"], authored["schema_version"])
            self.assertNotIn("Private", json.dumps(observed))
            for choice in ("UnknownOption", None):
                result["selected_action"] = choice
                event["item"]["result"]["content"][0]["text"] = json.dumps(result)
                path.write_text(json.dumps(event) + "\n")
                self.assertIsNone(BENCHMARK.parse_output(path)[1][0]["selected_effect"])
            event["item"]["arguments"] = {"decision_type": "PrivateLegacyCategory"}
            path.write_text(json.dumps(event) + "\n")
            self.assertEqual(BENCHMARK.parse_output(path)[1], [{"status": "completed"}])


if __name__ == "__main__":
    unittest.main()
