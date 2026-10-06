"""Authored checkpoint transport, local freshness and truthful evidence."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.decision_checkpoint import (CheckpointTracker, consult,
                                              envelope_schema, projection,
                                              validate_envelope)


def decision(revision=1, *, effect="inspect", capability=None):
    chosen = {"id": "inspect_current_evidence", "description": "Inspect the bounded evidence relevant to the current uncertainty.", "effect": effect}
    if capability is not None:
        chosen["capability"] = capability
    return {"schema_version": "quattro-jev-decisions-v2", "decision_id": "compare_current_evidence",
        "question": "Which next step best resolves the observed uncertainty?",
        "options": [chosen, {"id": "reason_about_current_gap", "description": "Use native reasoning when current evidence does not support a choice.", "effect": "agent"}],
        "context": {"observed_gap": "contract_uncertainty", "checked_count": 2},
        "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
        "execution_state": {"revision": revision, "phase": "evidence_comparison", "attempt": 0},
        "previous_result": "bounded_observation"}


def envelope(revision=1, *, authored=True):
    value = CheckpointTracker("synthetic-scope").observe(inspection=True, outcome="success")
    value["state_revision"] = revision
    if authored:
        value["decision"] = decision(revision)
    return value


def answer(request):
    return dict(selected_action=request["options"][0]["id"], confidence=.99,
                evidence="native_choice_probabilities", called=True, fallback_required=False)


class CheckpointTests(unittest.TestCase):
    def test_projection_preserves_authored_content_and_excludes_observation_identity(self):
        value = envelope()
        value["observations"]["unmeasured_property"] = None
        value["provenance"]["unmeasured_property"] = "unknown"
        request = projection(value)
        self.assertEqual(request, value["decision"])
        for private in ("synthetic-scope", "existing-scope", "observations", "provenance", "unmeasured_property"):
            self.assertNotIn(private, json.dumps(request))
        request["context"]["checked_count"] = 100
        self.assertEqual(value["decision"]["context"]["checked_count"], 2)
        second = envelope(2)
        second["decision"].update(decision_id="choose_verification_sequence",
            question="Which verification sequence fits the remaining evidence gap?",
            context={"remaining_checks": 3, "changed_component_count": 1})
        second["decision"]["options"][0].update(id="check_bounded_scope_first", effect="targeted_first")
        self.assertEqual(projection(second), second["decision"])
        self.assertNotEqual(projection(value), projection(second))

    def test_missing_legacy_invalid_and_revision_mismatch_make_zero_provider_calls(self):
        missing = envelope(authored=False)
        legacy = {"schema_version": "quattro-checkpoint-v1", "features": {}}
        invalid = envelope(); invalid["decision"] = {"decision_type": "progress_strategy", "available_actions": ["continue", "agent"]}
        injected = envelope(); injected["decision"]["host_capabilities"] = {"tool.invented": True}
        mismatched = envelope(); mismatched["decision"]["execution_state"]["revision"] = 2
        for value in (missing, legacy, invalid, injected, mismatched, None):
            evaluate = mock.Mock()
            result = consult(value, evaluate)
            evaluate.assert_not_called()
            self.assertEqual(result["reason"], "native_authorship_required")
            self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
            self.assertFalse(result["called"])
            self.assertFalse(result["accepted"])
        with self.assertRaises(ValueError):
            projection(missing)

    def test_schema_advertises_authored_decision_without_static_feature_or_option_menu(self):
        schema = envelope_schema()
        self.assertEqual(schema["properties"]["schema_version"]["const"], "quattro-checkpoint-v2")
        self.assertNotIn("features", schema["properties"])
        self.assertNotIn("enum", schema["properties"]["checkpoint"])
        authored = schema["properties"]["decision"]["properties"]
        self.assertNotIn("enum", authored["decision_id"])
        self.assertNotIn("enum", authored["options"]["items"]["properties"]["id"])
        self.assertFalse(schema["additionalProperties"])

    def test_local_observations_are_bounded_and_explicitly_provenanced(self):
        for mutate in (lambda v: v.update(prompt="private"),
                       lambda v: v["observations"].update(command=True),
                       lambda v: v["provenance"].update(inspection_returned="forged"),
                       lambda v: v.update(state_provenance=[]),
                       lambda v: v["observations"].update(inspected_payload={}),
                       lambda v: v["observations"].update(inspection_returned=None),
                       lambda v: v.update(scope_id="/private/scope")):
            value = envelope(); mutate(value)
            with self.assertRaises(ValueError):
                validate_envelope(value)
        tracker = CheckpointTracker()
        for index in range(300):
            tracker.observe(signature=f"{index:064x}")
        self.assertEqual(len(tracker.signatures), 256)

    def test_distinct_uncached_consultations_do_not_claim_application(self):
        requests = []
        for revision in range(40):
            result = consult(envelope(revision), lambda request: requests.append(request) or answer(request))
            self.assertTrue(result["called"])
            self.assertTrue(result["accepted"])
            self.assertEqual(result["recommendation"], "inspect")
            self.assertEqual(result["provider_selected_option"], "AUTHORED_OPTION")
            for field in ("applied", "cached", "advice_delivered", "action_admitted", "receipt_consumed", "execution_observed", "task_validated"):
                self.assertFalse(result[field])
        self.assertEqual(len(requests), 40)
        self.assertEqual(len({request["execution_state"]["revision"] for request in requests}), 40)

    def test_stale_disabled_cancelled_and_failing_checks_do_not_accept(self):
        for kwargs, reason in (({"enabled": False}, "disabled"), ({"is_current": lambda _: False}, "stale_state"),
                               ({"cancelled": lambda: True}, "cancelled")):
            evaluate = mock.Mock()
            self.assertEqual(consult(envelope(), evaluate, **kwargs)["reason"], reason)
            evaluate.assert_not_called()
        state = [True]
        def evaluate(request):
            state[0] = False
            return answer(request)
        result = consult(envelope(), evaluate, is_current=lambda _: state[0])
        self.assertEqual(result["reason"], "stale_state")
        self.assertTrue(result["called"])
        self.assertFalse(result["accepted"])
        state[0] = True
        result = consult(envelope(), evaluate, cancelled=lambda: not state[0])
        self.assertEqual(result["reason"], "cancelled")

    def test_host_capabilities_never_come_from_authored_parameters(self):
        value = envelope(); value["decision"] = decision(effect="native_tool", capability="tool.observed_read")
        value["decision"]["context"]["tool_available"] = True
        result = consult(value, answer)
        self.assertEqual(result["reason"], "hard_policy")
        self.assertFalse(result["accepted"])
        self.assertTrue(consult(value, answer, capabilities={"tool.observed_read": True})["accepted"])
        self.assertFalse(consult(value, answer, capabilities={"tool.observed_read": "true"})["accepted"])
        value["decision"] = decision(effect="rtk", capability="tool.rtk_run")
        self.assertFalse(consult(value, answer)["accepted"])
        self.assertFalse(consult(value, answer, capabilities={"tool.observed_read": True})["accepted"])

    def test_uncertainty_malformed_injection_and_unverified_evidence_fallback(self):
        request = projection(envelope())
        for response in (None, {}, {**answer(request), "selected_action": "invented"},
                {**answer(request), "selected_action": request["options"][1]["id"]},
                {**answer(request), "confidence": .89}, {**answer(request), "confidence": float("nan")},
                {**answer(request), "selected_action": []}, {**answer(request), "fallback_required": "false"},
                {**answer(request), "fallback_required": True}, {**answer(request), "called": False},
                {**answer(request), "evidence": "fabricated"}):
            result = consult(envelope(), lambda _: response)
            self.assertEqual(result["recommendation"], "defer_to_agent")
            self.assertEqual(result["fallback_class"], "agent")
            self.assertFalse(result["accepted"])
            self.assertFalse(result["action_admitted"])
        result = consult(envelope(), mock.Mock(side_effect=TimeoutError))
        self.assertFalse(result["called"])
        self.assertEqual(result["provider_attempt"], "UNKNOWN")

    def test_evaluator_cannot_mutate_the_snapshot_to_bypass_host_checks(self):
        value = envelope()
        value["decision"] = decision(effect="native_tool", capability="tool.observed_read")
        def evaluate(request):
            request["options"][0]["effect"] = "inspect"
            request["options"][0].pop("capability")
            return answer(request)
        result = consult(value, evaluate)
        self.assertEqual(result["reason"], "hard_policy")
        self.assertEqual(value["decision"]["options"][0]["effect"], "native_tool")

    def test_real_worker_session_retains_64_consultation_budget(self):
        from test_dynamic_decision_service import DynamicDecisionServiceTests
        fixture = DynamicDecisionServiceTests()
        session, processes = fixture.session()
        self.addCleanup(fixture.doCleanups)
        results = [consult(envelope(revision),
                    lambda request: session.decide(request, cacheable=False))
                   for revision in range(65)]
        self.assertTrue(all(result["accepted"] for result in results[:64]))
        self.assertFalse(results[-1]["accepted"])
        self.assertFalse(results[-1]["called"])
        self.assertEqual(session.calls, 64)
        self.assertEqual(len(processes), 1)

    def test_tracker_events_do_not_manufacture_model_decisions_or_semantic_success(self):
        tracker = CheckpointTracker()
        value = tracker.observe(inspection=True)
        self.assertEqual(value["observations"]["observed_result"], "unknown")
        self.assertNotIn("decision", value)
        self.assertIsNone(tracker.observe(writes=True, signature="a" * 64))
        self.assertIsNone(tracker.observe(signature="a" * 64))
        value = tracker.observe(signature="a" * 64)
        self.assertEqual(value["checkpoint"], "failure_no_progress")
        self.assertEqual(value["observations"]["repeat_count"], 3)
        self.assertTrue(tracker.current(value))
        tracker.observe()
        self.assertFalse(tracker.current(value))
        before = tracker.revision
        with self.assertRaises(ValueError):
            tracker.observe(signature="invalid")
        self.assertEqual(tracker.revision, before)


if __name__ == "__main__":
    unittest.main()
