"""Synthetic checkpoint contracts; never a live provider benchmark."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.decision_checkpoint import CheckpointTracker, consult, projection, validate_envelope
from quattro_agent import operational_native
from quattro_agent.native_intelligence import NativeContext
import quattro_intelligence_mcp as mcp


def envelope(revision=1, checkpoint="after_inspection"):
    value = CheckpointTracker("synthetic-scope").observe(inspection=True, outcome="success")
    value.update(state_revision=revision, checkpoint=checkpoint)
    return value


def answer(request):
    return dict(selected_action=request["available_actions"][0], confidence=.99,
                evidence="native_choice_probabilities", called=True, fallback_required=False)


class CheckpointTests(unittest.TestCase):
    def test_projection_strips_local_identity_and_unknowns(self):
        value = envelope()
        value["features"]["context_missing"] = None
        value["provenance"]["context_missing"] = "unknown"
        request = projection(value)
        self.assertNotIn("synthetic-scope", json.dumps(request))
        self.assertNotIn("provenance", request)
        self.assertNotIn("context_missing", request["relevant_context"])
        self.assertFalse(any(request["hard_constraints"].values()))
        for key, bad in (("prompt", "private"), ("permission", True)):
            with self.assertRaises(ValueError):
                validate_envelope(dict(value, **{key: bad}))
        for origin in ("unknown", "forged"):
            bad = copy.deepcopy(value)
            bad["provenance"]["repository_required"] = origin
            with self.assertRaises(ValueError):
                validate_envelope(bad)

    def test_no_cross_checkpoint_cache_and_no_cap(self):
        requests = []
        for revision in range(100):
            result = consult(envelope(revision), lambda r: requests.append(r) or answer(r))
            self.assertTrue(result["called"])
            self.assertTrue(result["accepted"])
            self.assertFalse(result["applied"])
            self.assertFalse(result["cached"])
        self.assertEqual(len(requests), 100)
        self.assertEqual(len({r["execution_state"]["revision"] for r in requests}), 100)

    def test_stale_answer_and_cancellation_are_not_accepted(self):
        state = [True]
        def evaluate(request):
            state[0] = False
            return answer(request)
        result = consult(envelope(), evaluate, is_current=lambda _: state[0])
        self.assertEqual(result["reason"], "stale_state")
        self.assertTrue(result["called"])
        self.assertFalse(result["accepted"])
        evaluator = mock.Mock()
        consult(envelope(), evaluator, is_current=lambda _: False)
        evaluator.assert_not_called()

    def test_uncertainty_never_requests_owner_or_changes_admission(self):
        for response in (None, {}, {"selected_action": "agent", "confidence": .99},
                         {"selected_action": "continue", "confidence": .2},
                         {"selected_action": [], "confidence": .99, "evidence": {}},
                         {"selected_action": "continue", "confidence": float("nan")}):
            result = consult(envelope(), lambda _: response)
            self.assertEqual(result["recommendation"], "defer_to_agent")
            self.assertEqual(result["fallback_class"], "agent")
            self.assertFalse(result["applied"])
            self.assertFalse(result["action_admitted"])
        result = consult(envelope(), mock.Mock(side_effect=TimeoutError))
        self.assertFalse(result["called"])
        self.assertEqual(result["provider_attempt"], "UNKNOWN")

    def test_tracker_observes_phase_and_repeated_result_without_semantic_claim(self):
        tracker = CheckpointTracker()
        value = tracker.observe(inspection=True)
        self.assertEqual(value["previous_result"], "none")
        self.assertEqual(value["phase"], "inspection")
        self.assertIsNone(tracker.observe(writes=True, signature="a" * 64))
        self.assertIsNone(tracker.observe(signature="a" * 64))
        value = tracker.observe(signature="a" * 64)
        self.assertEqual(value["checkpoint"], "failure_no_progress")
        self.assertEqual(value["phase"], "implementation")
        self.assertNotIn("changes_present", value["features"])

    def test_mixed_native_counters_share_real_monotonic_session(self):
        from test_decision_plane import DecisionPlaneTests
        from quattro_agent.native_intelligence import native_jev_advice
        fixture = DecisionPlaneTests()
        session, _ = fixture.session()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "native.json"
            config.write_text(json.dumps({"enabled": True, "operationalEnabled": True}))
            with mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(config),
                    "QUATTRO_NATIVE_TELEMETRY_DB": str(Path(tmp) / "trace.sqlite3")}):
                context = NativeContext(host="pi", session_id="mixed-counters")
                for revision in range(10, 110):
                    checkpoint = operational_native.operational_call({"operation": "checkpoint", "checkpoint": envelope(revision)},
                        context=context, decision_session=session)
                    self.assertTrue(checkpoint["accepted"])
                    preflight = operational_native.operational_call({"operation": "preflight", "features": {
                        "host_allowed": True, "writes": True}}, context=context, decision_session=session)
                    self.assertTrue(preflight["accepted"])
                    self.assertEqual(preflight["recommendation"], "proceed")
                    # Lifecycle/model-call counters can also restart at zero.
                    result = native_jev_advice(projection(envelope(0)), context=context,
                        decision_session=session, cacheable=False)
                    self.assertFalse(result["fallback_required"])
                self.assertGreater(session.revision, 200)

    def test_native_codex_and_pi_helper_100_distinct_consultations_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "native.json"
            config.write_text(json.dumps({"enabled": True, "operationalEnabled": True}))
            with mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(config),
                    "QUATTRO_NATIVE_TELEMETRY_DB": str(Path(tmp) / "trace.sqlite3")}), \
                    mock.patch.object(operational_native, "native_jev_advice", side_effect=lambda r, **kw: answer(r)) as evaluate:
                runtime = mcp.NativeMcpRuntime()
                self.addCleanup(runtime.close)
                for revision in range(100):
                    result = runtime.handle_call(revision, {"name": "operational_guard", "arguments": {
                        "operation": "checkpoint", "features": {}, "checkpoint": envelope(revision)}})
                    self.assertTrue(result["structuredContent"]["accepted"])
                    self.assertEqual(result["structuredContent"]["state_provenance"], "agent_asserted")
                for revision in range(100):
                    result = operational_native.operational_call({"operation": "checkpoint", "checkpoint": envelope(revision)},
                        context=NativeContext(host="pi", session_id="synthetic-pi"))
                    self.assertTrue(result["accepted"])
                self.assertEqual(evaluate.call_count, 200)
                self.assertTrue(all(call.kwargs["cacheable"] is False for call in evaluate.call_args_list))


if __name__ == "__main__":
    unittest.main()
