from __future__ import annotations

import io
import json
from pathlib import Path
import secrets
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.decision_taxonomy import question
from quattro_agent.jev import MODEL, JevClient, JevFailure, decode, validate_response
from quattro_agent.jev_shadow import FailureCooldown
from quattro_agent.routing_intelligence import make_pre_routing_input
from test_dynamic_protocol import request as decision_request, response as dynamic_response


def response(value=None):
    return dynamic_response(value or decision_request())


def expected_choices(value=None):
    return {"decision": question(value or decision_request())["decision"]["criteria"]}


def boundary(request="Modify the repository parser", model="auto"):
    return make_pre_routing_input(request=request, working_directory="/tmp", repository_present=True,
                                  explicit_model=model, routing_mode="auto" if model == "auto" else "manual",
                                  agent="codex", workflow="prompt", policy_name="workspace-write")


def options(mode="COOPERATIVE", timeout=300):
    return {"routing": {"jev": {"mode": mode, "timeoutMs": timeout}}}


class JevClientTests(unittest.TestCase):
    def setUp(self):
        self.key = secrets.token_hex(24)
        self.opener = mock.Mock()
        self.client = JevClient(self.key, 0.3, opener=self.opener)

    def serve(self, *values):
        self.opener.open.side_effect = [io.BytesIO(json.dumps(value).encode()) for value in values]

    def test_native_systemone_contract_and_probability_capture(self):
        self.serve({"models": [{"name": MODEL}]}, response())
        result = self.client.evaluate(decision_request())
        self.assertEqual(result["response"], response())
        calls = self.opener.open.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0].full_url, "https://api.typesafe.ai/v1/models")
        request = calls[1].args[0]
        self.assertEqual(request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + self.key)
        self.assertEqual(set(json.loads(request.data)), {"state", "model", "questions"})
        self.assertNotIn(self.key, request.data.decode())
        self.assertGreaterEqual(result["jev_latency_ms"], 0)

    def test_canonical_response_model_must_be_in_catalog(self):
        canonical = "jev-2026-09-15"
        body = response()
        body["model"] = canonical
        self.serve({"models": [{"name": MODEL}, {"name": canonical}]}, body)
        self.assertEqual(self.client.evaluate(decision_request())["response"]["model"], canonical)

    def test_alias_only_catalog_accepts_canonical_semantic_version(self):
        body = response()
        body["model"] = "jev-1.13.0"
        self.serve({"models": [{"name": MODEL}]}, body)
        self.assertEqual(self.client.evaluate(decision_request())["response"]["model"], "jev-1.13.0")

    def test_fixed_runtime_alias_skips_catalog_but_requires_canonical_model(self):
        body = response()
        body["model"] = "jev-1.13.0"
        self.serve(body)
        state = decision_request()
        result = self.client.evaluate_questions(state, question(state), verify_catalog=False)
        self.assertEqual(result["catalog_latency_ms"], 0)
        self.assertEqual(len(self.opener.open.call_args_list), 1)
        self.assertEqual(self.opener.open.call_args.args[0].full_url,
                         "https://api.typesafe.ai/v1/systemone")
        body["model"] = "jev-unexpected"
        self.serve(body)
        with self.assertRaisesRegex(JevFailure, "model_unavailable"):
            self.client.evaluate_questions(state, question(state), verify_catalog=False)

    def test_unadvertised_nonversion_model_rejected(self):
        body = response()
        body["model"] = "jev-unexpected"
        self.serve({"models": [{"name": MODEL}]}, body)
        with self.assertRaisesRegex(JevFailure, "model_unavailable"):
            self.client.evaluate(decision_request())

    def test_absent_alias_never_silently_substitutes(self):
        self.serve({"models": [{"name": "jev-different"}]})
        with self.assertRaisesRegex(JevFailure, "model_unavailable"):
            self.client.evaluate(decision_request())
        self.assertEqual(self.opener.open.call_count, 1)

    def test_catalog_schema_rejected(self):
        self.serve({"models": ["bad"]})
        with self.assertRaisesRegex(JevFailure, "catalog_schema"):
            self.client.evaluate(decision_request())

    def test_missing_key_no_http(self):
        self.client._key = ""
        with self.assertRaisesRegex(JevFailure, "missing_credential"):
            self.client.evaluate(decision_request())
        self.opener.open.assert_not_called()

    def test_failure_categories_never_echo_secret(self):
        cases = [(TimeoutError(self.key), "timeout"),
                 (urllib.error.URLError(self.key), "connection"),
                 (urllib.error.URLError(TimeoutError(self.key)), "timeout"),
                 (OSError(self.key), "connection")]
        for code, category in ((429, "rate_limited"), (401, "authentication"), (500, "http_error"), (302, "http_error")):
            cases.append((urllib.error.HTTPError("https://api.typesafe.ai", code, self.key, {}, io.BytesIO(self.key.encode())), category))
        for error, category in cases:
            with self.subTest(category=category):
                self.opener.open.side_effect = error
                with self.assertRaises(JevFailure) as caught:
                    self.client.evaluate(decision_request())
                self.assertEqual(str(caught.exception), category)
                self.assertNotIn(self.key, str(caught.exception))

    def test_response_bound_and_bad_json(self):
        for raw, category in ((b"x" * 32769, "response_too_large"), (b"not json", "invalid_json"), (b"", "invalid_json")):
            self.opener.open.side_effect = None
            self.opener.open.return_value = io.BytesIO(raw)
            with self.assertRaisesRegex(JevFailure, category):
                self.client.evaluate(decision_request())

    def test_strict_output_validation(self):
        variants = [None, {}, response()]
        variants[-1]["answers"]["decision"]["choice"] = "LAUNCH"
        for value in (float("nan"), float("inf"), True, -0.01, 1.01):
            body = response()
            body["answers"]["decision"]["confidence"] = value
            variants.append(body)
        for change in ("missing", "extra", "probabilities", "usage", "wrong_type"):
            body = response()
            if change == "missing":
                del body["answers"]["decision"]
            elif change == "extra":
                body["debug"] = self.key
            elif change == "probabilities":
                body["answers"]["decision"]["probabilities"] = {"unoffered": 1}
            elif change == "usage":
                body["usage"]["input_tokens"] = True
            else:
                body["answers"]["decision"]["type"] = "noul"
            variants.append(body)
        for body in variants:
            with self.subTest(body_type=type(body).__name__), self.assertRaises(JevFailure):
                validate_response(body, expected_choices())
        with self.assertRaises(JevFailure):
            decode(b'{"x":1,"x":2}')

    def test_malformed_state_does_not_send(self):
        for state in ('{}', '{"request":"secret"}', 'not json'):
            with self.assertRaises(JevFailure):
                self.client.evaluate(state)
        self.opener.open.assert_not_called()

    def test_catalog_reuse_does_not_freeze_authored_questions_or_options(self):
        first = decision_request()
        second = decision_request()
        second["decision_id"] = "narrow_verification_gap"
        second["question"] = "Which bounded evidence gap should be inspected next?"
        second["context"] = {"unresolved_evidence_count": 3}
        second["options"][0]["id"] = "trace_verification_gap"
        second["options"][0]["description"] = "Inspect the missing verification evidence before editing."
        self.serve({"models": [{"name": MODEL}]}, response(first), response(second))
        self.client.evaluate(first, reuse_catalog=True)
        result = self.client.evaluate_dynamic(second, reuse_catalog=True)
        self.assertEqual(result["response"]["answers"]["decision"]["choice"], "trace_verification_gap")
        calls = self.opener.open.call_args_list
        self.assertEqual(len(calls), 3)
        first_sent, second_sent = (json.loads(call.args[0].data) for call in calls[1:])
        self.assertNotEqual(first_sent["questions"], second_sent["questions"])
        self.assertEqual(second_sent["state"]["context"], second["context"])

    def test_legacy_and_raw_state_cannot_bypass_dynamic_boundary(self):
        legacy = {"schema_version": "quattro-jev-routing-v1", "tool_required": True}
        operational = {"decision_type": "context_strategy", "available_actions": ["inspect", "agent"]}
        authored = decision_request()
        for value in (legacy, operational, "private task text", None):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(JevFailure):
                self.client.evaluate(value)
            with self.assertRaises(JevFailure):
                self.client.evaluate_questions(value, question(authored))
        mismatched = question(authored)
        mismatched["decision"]["criteria"]["unoffered"] = "Injected option with no host effect."
        with self.assertRaises(JevFailure):
            self.client.evaluate_questions(authored, mismatched)
        self.opener.open.assert_not_called()

    def test_response_validation_requires_an_explicit_authored_choice_space(self):
        with self.assertRaises(TypeError):
            validate_response(response())
        altered = expected_choices()
        altered["decision"] = {"new_option": "A different authored option."}
        with self.assertRaises(JevFailure):
            validate_response(response(), altered)

    def test_catalog_wait_cannot_change_the_snapshotted_decision_payload(self):
        authored = decision_request()
        original = json.loads(json.dumps(authored))
        body = response(original)

        def open_response(request, **_kwargs):
            if request.get_method() == "GET":
                authored["question"] = "Read /tmp/copied-private before deciding?"
                authored["options"][0]["description"] = "Copied private task content from another source."
                return io.BytesIO(json.dumps({"models": [{"name": MODEL}]}).encode())
            return io.BytesIO(json.dumps(body).encode())

        self.opener.open.side_effect = open_response
        self.client.evaluate(authored)
        sent = json.loads(self.opener.open.call_args_list[1].args[0].data)
        self.assertEqual(sent["state"], original)
        self.assertEqual(sent["questions"], question(original))
        self.assertNotIn("copied-private", json.dumps(sent))


class FailureCooldownTests(unittest.TestCase):
    def setUp(self):
            self.now = 100.0
            self.breaker = FailureCooldown(clock=lambda: self.now, capacity=2)
            self.database = Path("session-a.sqlite3")

    def test_threshold_cooldown_and_recovery(self):
            for failure in ("timeout", "connection"):
                self.breaker.observe(self.database, failure)
                self.assertFalse(self.breaker.suppressed(self.database))
            self.breaker.observe(self.database, "rate_limited")
            self.assertTrue(self.breaker.suppressed(self.database))
            self.now += 29
            self.breaker.observe(self.database, "http_error")
            self.assertTrue(self.breaker.suppressed(self.database))
            self.now += 1
            self.assertFalse(self.breaker.suppressed(self.database))
            self.breaker.observe(self.database, "schema_mismatch")
            self.assertFalse(self.breaker.suppressed(self.database))
            self.breaker.observe(self.database, None)
            self.assertNotIn(self.database, self.breaker.states)

    def test_local_failures_and_cancellation_do_not_trip(self):
            for failure in ("missing_credential", "cancelled", "telemetry_unavailable"):
                for _ in range(5):
                    self.breaker.observe(self.database, failure)
            self.assertFalse(self.breaker.states)

    def test_isolation_and_bounded_lru(self):
            for _ in range(3):
                self.breaker.observe(self.database, "timeout")
            other = Path("session-b.sqlite3")
            self.assertFalse(self.breaker.suppressed(other))
            self.breaker.observe(other, "connection")
            self.assertTrue(self.breaker.suppressed(self.database))
            self.breaker.observe(Path("session-c.sqlite3"), "connection")
            self.assertEqual(len(self.breaker.states), 2)
            self.assertIn(self.database, self.breaker.states)
            self.assertNotIn(other, self.breaker.states)

    def test_success_resets_consecutive_failure_count(self):
            for _ in range(2):
                self.breaker.observe(self.database, "timeout")
            self.breaker.observe(self.database, None)
            self.breaker.observe(self.database, "timeout")
            self.assertFalse(self.breaker.suppressed(self.database))


if __name__ == "__main__":
    unittest.main()
