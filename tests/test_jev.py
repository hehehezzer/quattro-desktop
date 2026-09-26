from __future__ import annotations

from contextlib import closing
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.jev import (
    CHOICES, MODEL, JevClient, JevFailure, decode, serialize_state, validate_response,
)
from quattro_agent.jev_shadow import ShadowRun, lifecycle, start_shadow
from quattro_agent.routing_signals import classify_with_signals, fuse, learned_signal
from quattro_agent.routing import RoutingTier, classify_pre_routing
from quattro_agent.routing_intelligence import make_pre_routing_input, task_profile_from_dict
from quattro_agent.model_registry import load_model_registry, default_policy_path, select_execution_target

SRC = Path(__file__).parents[1] / "src"


def response(execution="DELEGATE", capability="STRONG", complexity="HIGH"):
    selected = {"execution": execution, "capability": capability, "complexity": complexity, "task_type": "CODING"}
    return {"model": MODEL, "answers": {
        name: {"type": "choice", "choice": selected[name], "confidence": 0.98,
               "probabilities": {choice: 0.98 if choice == selected[name] else 0.02 / (len(choices) - 1)
                                 for choice in choices}}
        for name, choices in CHOICES.items()
    }, "usage": {"input_tokens": 123, "output_tokens": 16}}


def boundary(request="Modify the repository parser", model="auto"):
    return make_pre_routing_input(request=request, working_directory="/tmp", repository_present=True,
                                  explicit_model=model, routing_mode="auto" if model == "auto" else "manual",
                                  agent="codex", workflow="prompt", policy_name="workspace-write")


def options(mode="COOPERATIVE", timeout=300):
    return {"routing": {"jev": {"mode": mode, "timeoutMs": timeout}}}


class FakeProcess:
    result = {"response": response(), "failure_category": None, "jev_latency_ms": 12.0,
              "catalog_latency_ms": 5.0, "worker_latency_ms": 18.0}

    def __init__(self, *args, **kwargs):
        self.returncode = None
        self.stdin = None
        self.stdout = None

    def communicate(self, *args, **kwargs):
        self.returncode = 0
        return json.dumps(self.result).encode(), b""

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self):
        return self.returncode


class JevClientTests(unittest.TestCase):
    def setUp(self):
        self.key = secrets.token_hex(24)
        self.opener = mock.Mock()
        self.client = JevClient(self.key, 0.3, opener=self.opener)

    def serve(self, *values):
        self.opener.open.side_effect = [io.BytesIO(json.dumps(value).encode()) for value in values]

    def test_native_systemone_contract_and_probability_capture(self):
        self.serve({"models": [{"name": MODEL}]}, response())
        result = self.client.evaluate(serialize_state("Implement the parser"))
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
        self.assertEqual(self.client.evaluate(serialize_state("hello"))["response"]["model"], canonical)

    def test_absent_alias_never_silently_substitutes(self):
        self.serve({"models": [{"name": "jev-different"}]})
        with self.assertRaisesRegex(JevFailure, "model_unavailable"):
            self.client.evaluate(serialize_state("hello"))
        self.assertEqual(self.opener.open.call_count, 1)

    def test_catalog_schema_rejected(self):
        self.serve({"models": ["bad"]})
        with self.assertRaisesRegex(JevFailure, "catalog_schema"):
            self.client.evaluate(serialize_state("hello"))

    def test_missing_key_no_http(self):
        self.client._key = ""
        with self.assertRaisesRegex(JevFailure, "missing_credential"):
            self.client.evaluate(serialize_state("hello"))
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
                    self.client.evaluate(serialize_state("hello"))
                self.assertEqual(str(caught.exception), category)
                self.assertNotIn(self.key, str(caught.exception))

    def test_response_bound_and_bad_json(self):
        for raw, category in ((b"x" * 32769, "response_too_large"), (b"not json", "invalid_json"), (b"", "invalid_json")):
            self.opener.open.side_effect = None
            self.opener.open.return_value = io.BytesIO(raw)
            with self.assertRaisesRegex(JevFailure, category):
                self.client.evaluate(serialize_state("hello"))

    def test_strict_output_validation(self):
        variants = [None, {}, response()]
        variants[-1]["answers"]["execution"]["choice"] = "LAUNCH"
        for value in (float("nan"), float("inf"), True, -0.01, 1.01):
            body = response()
            body["answers"]["execution"]["confidence"] = value
            variants.append(body)
        for change in ("missing", "extra", "probabilities", "usage", "wrong_type"):
            body = response()
            if change == "missing":
                del body["answers"]["capability"]
            elif change == "extra":
                body["debug"] = self.key
            elif change == "probabilities":
                body["answers"]["complexity"]["probabilities"] = {"HIGH": 1}
            elif change == "usage":
                body["usage"]["input_tokens"] = True
            else:
                body["answers"]["execution"]["type"] = "noul"
            variants.append(body)
        for body in variants:
            with self.subTest(body_type=type(body).__name__), self.assertRaises(JevFailure):
                validate_response(body)
        with self.assertRaises(JevFailure):
            decode(b'{"x":1,"x":2}')

    def test_malformed_state_does_not_send(self):
        for state in ('{}', '{"request":"secret"}', 'not json'):
            with self.assertRaises(JevFailure):
                self.client.evaluate(state)
        self.opener.open.assert_not_called()

    def test_serialization_is_deterministic_minimized_and_leakage_free(self):
        text = "Modify repository and run tests. " + self.key + " full conversation source-code privatefile"
        state = serialize_state(text)
        self.assertEqual(state, serialize_state(text))
        self.assertLess(len(state), 700)
        for forbidden in (self.key, "privatefile", "source-code", "conversation", "selected_model", "production_decision", "outcome", "request_text"):
            self.assertNotIn(forbidden, state)
        self.assertIs(json.loads(state)["modification_required"], True)
        self.assertEqual(state, json.dumps(json.loads(state), sort_keys=True, separators=(",", ":")))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "private" / "jev.sqlite3"
        self.key = secrets.token_hex(24)
        self.environment = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": self.key})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def run_instance(self, popen=FakeProcess, timeout=300, decision="DIRECT"):
        return ShadowRun(database=self.database, request="hello", decision=decision,
                         record_id="record-test", source_task_id="task-test",
                         authoritative_tier="FAST", timeout_ms=timeout, popen=popen)

    def record(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return json.loads(connection.execute("SELECT evidence FROM jev_shadow").fetchone()[0])

    def test_disagreement_and_telemetry_provenance(self):
        run = self.run_instance()
        run.start()
        self.assertTrue(run.done.wait(2))
        run.close()
        row = self.record()
        self.assertFalse(row["agreement"])
        self.assertEqual(row["authoritative_quattro_decision"], "DIRECT")
        self.assertEqual(row["jev_shadow_decision"], "DELEGATE")
        self.assertEqual(row["answers"]["execution"]["confidence"], 0.98)
        self.assertEqual(row["jev_latency_ms"], 12)
        self.assertEqual(row["input_usage"], 123)
        self.assertIsNone(row["cost"])
        self.assertEqual(row["provenance"], "jev_shadow_observation")
        self.assertNotIn(self.key, self.database.read_bytes().decode(errors="ignore"))
        self.assertFalse(run.thread.is_alive())
        if os.name == "posix":
            self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_agreement(self):
        run = self.run_instance(decision="DELEGATE")
        run.start()
        self.assertTrue(run.done.wait(2))
        run.close()
        self.assertTrue(self.record()["agreement"])

    def test_missing_key_is_observable_no_process(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            process = mock.Mock()
            run = self.run_instance(popen=process)
            run.start()
            self.assertTrue(run.done.wait(2))
            run.close()
            process.assert_not_called()
        self.assertEqual(self.record()["failure_category"], "missing_credential")

    def sleeper(self, *args, **kwargs):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

    def test_real_child_deadline_and_reaping(self):
        run = self.run_instance(popen=self.sleeper, timeout=100)
        run.start()
        self.assertTrue(run.done.wait(2))
        run.close()
        self.assertEqual(self.record()["failure_category"], "timeout")
        self.assertEqual(self.record()["timeout_count"], 1)
        self.assertIsNotNone(run.process.poll())
        self.assertFalse(run.thread.is_alive())

    def test_standalone_worker_missing_key_is_bounded_and_private(self):
        payload = json.dumps({"key": "", "state": serialize_state("hello"), "timeout_seconds": .1})
        result = subprocess.run(
            [sys.executable, str(SRC / "quattro_agent/jev_worker.py")], input=payload,
            text=True, capture_output=True, timeout=2, env={},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["failure_category"], "missing_credential")
        self.assertEqual(result.stderr, "")
        self.assertNotIn(self.key, result.stdout)

    def test_close_cancels_without_waiting_for_provider(self):
        run = self.run_instance(popen=self.sleeper, timeout=3000)
        run.start()
        deadline = time.monotonic() + 2
        while run.process is None and time.monotonic() < deadline:
            time.sleep(0.001)
        started = time.perf_counter()
        run.close()
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(self.record()["failure_category"], "cancelled")
        self.assertIsNotNone(run.process.poll())

    def test_off_zero_calls_and_zero_store(self):
        @lifecycle
        def route():
            start_shadow(config=options("OFF"), database=self.database, request="hello", decision="DIRECT")
            return "authoritative"
        with mock.patch.object(ShadowRun, "start") as start:
            self.assertEqual(route(), "authoritative")
        start.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_scope_reaps_on_authoritative_exception(self):
        created = []
        original = ShadowRun.__init__
        def init(run, **kwargs):
            original(run, **kwargs, popen=self.sleeper)
            created.append(run)
        @lifecycle
        def route():
            start_shadow(config=options("SHADOW"), database=self.database, request="hello", decision="DIRECT")
            raise RuntimeError("authoritative error")
        with mock.patch.object(ShadowRun, "__init__", init):
            with self.assertRaisesRegex(RuntimeError, "authoritative error"):
                route()
        self.assertFalse(created[0].thread.is_alive())
        if created[0].process:
            self.assertIsNotNone(created[0].process.poll())

    def test_all_provider_failures_are_evidence_not_task_failures(self):
        for category in ("timeout", "connection", "http_error", "invalid_json", "schema_mismatch", "unknown_choice", "rate_limited"):
            class Failed(FakeProcess):
                result = {"failure_category": category}
            run = self.run_instance(popen=Failed)
            run.start()
            self.assertTrue(run.done.wait(2))
            run.close()
            self.assertEqual(run.record["failure_category"], category)
            self.assertIsNone(run.record["jev_shadow_decision"])

    def test_unwritable_telemetry_never_calls_provider(self):
        with mock.patch("quattro_agent.jev_shadow.persist", return_value=False):
            factory = mock.Mock()
            run = self.run_instance(popen=factory)
            run.start()
            self.assertTrue(run.done.wait(2))
            run.close()
        factory.assert_not_called()
        self.assertFalse(run.persistence_ok)


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "intelligence.sqlite3"
        self.boundary = boundary()
        self.baseline = classify_pre_routing(pre_routing_input=self.boundary, config={})
        self.features = json.loads(serialize_state(self.boundary.request))

    def tearDown(self):
        self.temp.cleanup()

    def fuse(self, jev=None, learned=None, execution="DELEGATE", manual=False):
        return fuse(self.baseline, execution=execution, manual=manual, features=self.features,
                    jev=jev, learned=learned or {}, config={})

    def test_cooperative_consumes_signal_without_changing_capabilities(self):
        final, reason = self.fuse(response(), {"prediction": "DELEGATE", "confidence": 0.95})
        self.assertEqual(reason, "capability_floor_raised")
        self.assertNotEqual(final.tier, self.baseline.tier)
        self.assertEqual(final.task_profile["required_capabilities"], self.baseline.task_profile["required_capabilities"])
        self.assertGreaterEqual(final.task_profile["minimum_quality"], self.baseline.task_profile["minimum_quality"])

    def test_only_jev_available(self):
        _, reason = self.fuse(response(), {"error": "model_unavailable"})
        self.assertEqual(reason, "capability_floor_raised")

    def test_only_learned_or_neither_falls_back(self):
        for learned in ({}, {"prediction": "DELEGATE", "confidence": 0.99}):
            final, reason = self.fuse(None, learned)
            self.assertEqual(final, self.baseline)
            self.assertEqual(reason, "jev_unavailable")

    def test_learned_veto_and_manual_override(self):
        for learned, manual, reason in (({"prediction": "DIRECT", "confidence": 0.9}, False, "learned_direct_veto"),
                                        ({}, True, "explicit_target_preserved")):
            final, actual = self.fuse(response(), learned, manual=manual)
            self.assertEqual(final, self.baseline)
            self.assertEqual(actual, reason)

    def test_deterministic_floor_cannot_be_lowered(self):
        final, _ = self.fuse(response(capability="CHEAP"))
        self.assertEqual(final, self.baseline)

    def test_simple_prompt_stays_direct_fast_without_special_casing(self):
        from quattro_agent.delegation import classify_task_request
        for request in ("hello", "What is a Python list?", "Explain recursion", "Thanks"):
            with self.subTest(request=request):
                gate = classify_task_request(request)
                base = classify_pre_routing(pre_routing_input=boundary(request), config={})
                final, _ = fuse(base, execution=gate.decision, manual=False,
                                features=json.loads(serialize_state(request)), jev=response(), learned={}, config={})
                self.assertEqual(gate.decision, "DIRECT")
                self.assertEqual(final, base)
                self.assertEqual(final.tier, RoutingTier.FAST)

    def test_registry_filters_availability_capability_and_cost_after_fusion(self):
        final, _ = self.fuse(response())
        profile = task_profile_from_dict(final.task_profile)
        targets = load_model_registry(default_policy_path(), SRC / "quattro/omniroute-model-catalog.json")
        target = select_execution_target(profile, targets, preferred_account="account-1",
                                         available_accounts=frozenset({"account-2"}))
        self.assertEqual(target.account, "account-2")
        eligible = [t for t in targets if t.account == "account-2" and profile.tier.value in t.tiers
                    and set(profile.required_capabilities) <= t.capabilities]
        selected = next(t for t in targets if t.route == target.route)
        self.assertEqual(selected.cost_rank, min(t.cost_rank for t in eligible))
        from dataclasses import replace
        from quattro_agent.errors import ConfigError
        with self.assertRaises(ConfigError):
            select_execution_target(profile, [replace(selected, capabilities=frozenset())], preferred_account="account-2")
        with self.assertRaises(ConfigError):
            select_execution_target(profile, targets, preferred_account="account-1", available_accounts=frozenset())

    def test_unavailable_uplift_target_veto_keeps_baseline(self):
        original = ShadowRun.__init__
        def init(run, **kwargs):
            original(run, **kwargs, popen=FakeProcess)
        @lifecycle
        def route():
            return classify_with_signals(
                pre_routing_input=self.boundary, config=options(), database=self.database,
                execution="DELEGATE", can_select=lambda _: False,
            )
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
             mock.patch.object(ShadowRun, "__init__", init):
            self.assertEqual(route(), self.baseline)
        with closing(sqlite3.connect(self.database.with_name("jev-shadow.sqlite3"))) as connection:
            row = json.loads(connection.execute("SELECT evidence FROM jev_shadow").fetchone()[0])
        self.assertEqual(row["fusion_reason"], "runtime_capability_veto")

    def test_local_learned_failure_is_optional(self):
        self.database.touch()
        with mock.patch("quattro_agent.routing_signals.IntelligenceStore", side_effect=OSError("not available")):
            self.assertEqual(learned_signal(self.database, "hello"), {"error": "inference_failed"})

    def test_shadow_no_effect_cooperative_effect_and_parallel_local_work(self):
        original_init = ShadowRun.__init__
        event = threading.Event()
        class Slow(FakeProcess):
            def communicate(self, *args, **kwargs):
                event.set()
                time.sleep(0.025)
                return super().communicate(*args, **kwargs)
        def init(run, **kwargs):
            original_init(run, **kwargs, popen=Slow)
        def local(*args):
            self.assertTrue(event.wait(1))  # Network worker already running during local inference.
            time.sleep(0.005)
            return {"prediction": "DELEGATE", "confidence": 0.95}
        @lifecycle
        def route(mode):
            return classify_with_signals(pre_routing_input=self.boundary, config=options(mode),
                                         database=self.database, execution="DELEGATE", can_select=lambda _: True)
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
             mock.patch.object(ShadowRun, "__init__", init), \
             mock.patch("quattro_agent.routing_signals.learned_signal", side_effect=local):
            shadow = route("SHADOW")
            self.assertEqual(shadow, self.baseline)
            cooperative = route("COOPERATIVE")
            self.assertNotEqual(cooperative.tier, self.baseline.tier)
        with closing(sqlite3.connect(self.database.with_name("jev-shadow.sqlite3"))) as connection:
            rows = [json.loads(row[0]) for row in connection.execute("SELECT evidence FROM jev_shadow")]
        for row in rows:
            self.assertIn("quattro_learned_ms", row)
            self.assertIn("fusion_ms", row)
            self.assertIn("routing_total_ms", row)
            self.assertIn("policy_constraints", row)
        self.assertFalse(any(t.name == "jev-shadow" for t in threading.enumerate()))


class HarnessSignalTests(unittest.TestCase):
    def setUp(self):
        import test_harness_integration as fixtures
        self.fixture = fixtures.HarnessRuntimeIntegrationTests()
        self.fixture.setUp()
        self.runtime = self.fixture.runtime

    def tearDown(self):
        self.fixture.tearDown()

    def configure(self, mode):
        config = self.runtime.config()
        config["routing"]["jev"] = {"mode": mode, "timeoutMs": 100}
        self.runtime.persist_config(config)

    def test_default_and_strict_config(self):
        from quattro_agent.config import validate_ai_config
        from quattro_agent.errors import ConfigError
        config = self.runtime.config()
        self.assertEqual(config["routing"]["jev"]["mode"], "OFF")
        for mode in ("OFF", "SHADOW", "COOPERATIVE"):
            config["routing"]["jev"]["mode"] = mode
            self.assertEqual(validate_ai_config(config)["routing"]["jev"]["mode"], mode)
        for bad in ("AUTHORITATIVE", "invalid"):
            config["routing"]["jev"]["mode"] = bad
            with self.assertRaises(ConfigError):
                validate_ai_config(config)
        config["routing"]["jev"] = {"mode": "SHADOW", "timeoutMs": 10000}
        with self.assertRaises(ConfigError):
            validate_ai_config(config)

    def test_direct_authority_and_locked_target_survive_every_mode_and_failure(self):
        original_init = ShadowRun.__init__
        for mode, category in (("OFF", None), ("SHADOW", None), ("COOPERATIVE", None),
                               ("COOPERATIVE", "timeout"), ("COOPERATIVE", "connection"),
                               ("COOPERATIVE", "http_error"), ("COOPERATIVE", "invalid_json")):
            self.configure(mode)
            class Process(FakeProcess):
                result = {"failure_category": category} if category else FakeProcess.result
            def init(run, **kwargs):
                original_init(run, **kwargs, popen=Process)
            successful = ({"output_text": "hello", "usage": {"input_tokens": 5, "output_tokens": 1}},
                          {"provider": "cx", "account": "account-1", "model": "gpt-5.6-luna",
                           "route": "account-1/gpt-5.6-luna", "cost": None})
            with self.subTest(mode=mode, failure=category), \
                 mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
                 mock.patch.object(ShadowRun, "__init__", init), \
                 mock.patch.object(self.runtime, "_send_omniroute_response", return_value=successful) as send, \
                 mock.patch.object(self.runtime, "_locked_target_receipt",
                                   side_effect=self.fixture._direct_locked_receipt("account-1/gpt-5.6-luna")):
                result = self.runtime.direct_response(project=self.fixture.project, prompt="hello")
                self.assertEqual(result["model"], "account-1/gpt-5.6-luna")
                self.assertEqual(send.call_count, 1)
                self.assertEqual(self.runtime.store.list_display_tasks(), [])
        # Conclusive DIRECT is no longer shadow-eligible in any mode.
        self.assertFalse(self.runtime.intelligence_database.with_name("jev-shadow.sqlite3").exists())
        self.assertFalse(any(t.name == "jev-shadow" for t in threading.enumerate()))

    def test_durable_worker_target_and_outcome_association(self):
        self.configure("COOPERATIVE")
        original_init = ShadowRun.__init__
        def init(run, **kwargs):
            original_init(run, **kwargs, popen=FakeProcess)
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
             mock.patch.object(ShadowRun, "__init__", init):
            task_id = self.runtime.create_task(
                agent="codex", project=self.fixture.project, mode="prompt",
                prompt="Debug the repository regression and reproduce the root cause", profile_name="workspace-write",
            )
        task = self.runtime.store.get_task(task_id, include_private=True)
        self.assertEqual(task["agent"], "codex")
        self.assertTrue(task["private_payload"]["executionPlan"]["routingLocked"])
        with closing(sqlite3.connect(self.runtime.intelligence_database.with_name("jev-shadow.sqlite3"))) as connection:
            row = json.loads(connection.execute("SELECT evidence FROM jev_shadow").fetchone()[0])
        self.assertEqual(row["source_task_id"], task_id)
        self.assertEqual(row["record_id"], task["private_payload"]["intelligenceRecordId"])
        self.assertEqual(row["final_decision"]["worker"], "codex")
        self.assertEqual(row["final_decision"]["model"], task["private_payload"]["executionTarget"]["model"])


class NativeTurnSignalTests(unittest.TestCase):
    def setUp(self):
        import test_turn_gate as fixtures
        self.fixture = fixtures.TurnGateTests()
        self.fixture.setUp()
        self.gate = self.fixture.gate

    def tearDown(self):
        self.fixture.doCleanups()

    def test_rebased_latency_cases_preserve_direct_budget_and_no_tools(self):
        for mode in ("OFF", "SHADOW", "COOPERATIVE"):
            self.gate.config = options(mode)
            for frontend in ("codex", "pi"):
                for text in ("What is an API gateway?", "Explain how to run tests", "Explain this Python traceback"):
                    with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
                        turn = self.gate.begin("thread", text, frontend)
                        self.assertEqual(turn.decision, "DIRECT")
                        self.assertEqual(turn.plan.target.tier, "FAST")
                        self.assertEqual(turn.plan.required_tools, ())
                        self.assertEqual(turn.budget, 20)
                        self.gate.finish(turn)
            self.assertFalse(any(t.name == "jev-shadow" for t in threading.enumerate()))

    def test_sensitive_turn_skips_jev_entirely(self):
        self.gate.config = options("COOPERATIVE")
        with mock.patch.object(ShadowRun, "start") as start:
            turn = self.gate.begin("thread", "What's my OmniRoute dashboard password?", "codex")
            self.gate.finish(turn)
        start.assert_not_called()

    def test_native_cooperative_fuses_before_lock_and_shadow_owned_until_finish(self):
        original_init = ShadowRun.__init__
        def init(run, **kwargs):
            original_init(run, **kwargs, popen=FakeProcess)
        for mode, expected in (("SHADOW", "STANDARD"), ("COOPERATIVE", "REASONING")):
            self.gate.config = options(mode)
            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
                 mock.patch.object(ShadowRun, "__init__", init):
                turn = self.gate.begin("thread", "Debug the repository regression and reproduce the root cause", "codex")
                self.assertEqual(turn.plan.target.tier, expected)
                self.assertTrue(turn.plan.routing_locked)
                self.assertEqual(len(turn.shadow_runs), 1)
                self.assertTrue(turn.shadow_runs[0].done.wait(2))
                self.gate.finish(turn)
                self.gate.cancel(turn)  # Double cleanup must not release capacity twice.
                self.assertFalse(turn.shadow_runs[0].thread.is_alive())
                row = turn.shadow_runs[0].record
                self.assertEqual(row["turn_id"], turn.turn_id)
                self.assertEqual(row["final_decision"]["execution"], "DELEGATE")
                self.assertEqual(row["final_decision"]["model"], turn.plan.target.model)

    def test_native_cancel_all_reaps_real_inflight_child(self):
        original_init = ShadowRun.__init__
        def popen(_args, **kwargs):
            return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        def init(run, **kwargs):
            original_init(run, **kwargs, popen=popen)
        self.gate.config = options("SHADOW", timeout=3000)
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
             mock.patch.object(ShadowRun, "__init__", init):
            turn = self.gate.begin("thread", "Debug the repository regression and reproduce the root cause", "pi")
            run = turn.shadow_runs[0]
            deadline = time.monotonic() + 2
            while run.process is None and time.monotonic() < deadline:
                time.sleep(.001)
            self.gate.cancel_all()
            self.assertFalse(run.thread.is_alive())
            if run.process:
                self.assertIsNotNone(run.process.poll())
            self.gate.finish(turn)


if __name__ == "__main__":
    unittest.main()
