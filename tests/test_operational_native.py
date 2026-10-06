import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import copy

from quattro_agent import operational_native as operation
from quattro_agent.native_intelligence import NativeContext
from quattro_agent import shared_intelligence
import quattro_intelligence_mcp as mcp


def authored_checkpoint(*, capability=None):
    choice = {"id": "inspect_current_gap", "description": "Inspect the bounded evidence for the current gap.",
              "effect": "native_tool" if capability else "inspect"}
    if capability:
        choice["capability"] = capability
    decision = {"schema_version": "quattro-jev-decisions-v2", "decision_id": "resolve_current_gap",
                "question": "Which next step resolves the current evidence gap?",
                "options": [choice, {"id": "native_reasoning", "description": "Reason further when the evidence is insufficient.", "effect": "agent"}],
                "context": {"checked_count": 2},
                "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
                "execution_state": {"revision": 1, "phase": "current_evidence", "attempt": 0},
                "previous_result": "bounded_observation"}
    return {"schema_version": "quattro-checkpoint-v2", "checkpoint": "review_current_gap",
            "scope_id": "local-scope", "policy_revision": "local-policy", "state_revision": 1,
            "state_provenance": "host_observed", "observations": {"checks_returned": 2, "uncertain_property": None},
            "provenance": {"checks_returned": "host_observed", "uncertain_property": "unknown"}, "decision": decision}


def checkpoint_answer(request, **_host_arguments):
    return {"selected_action": request["options"][0]["id"], "confidence": .99,
            "called": True, "evidence": "native_choice_probabilities", "fallback_required": False}


class NativeOperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "native.json"
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": True}))
        env = mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(self.config),
            "QUATTRO_NATIVE_TELEMETRY_DB": str(Path(self.tmp.name) / "metadata.sqlite3")})
        env.start(); self.addCleanup(env.stop)
        operation._sessions.clear()

    def test_activation_defaults_off(self):
        self.config.write_text('{"enabled":true}')
        with mock.patch.object(shared_intelligence, "native_jev_advice") as evaluator:
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True}})
        evaluator.assert_not_called()
        self.assertEqual(result["reason"], "disabled")

    def test_codex_explicit_guard_returns_without_authorizing(self):
        with mock.patch.object(shared_intelligence, "native_jev_advice", return_value={"selected_action": "continue", "confidence": .99, "called": True}):
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True, "writes": True}}, context=NativeContext(host="codex", session_id="test"))
        self.assertEqual(result["recommendation"], "proceed")
        self.assertFalse(result["applied"])
        tool = next(t for t in mcp.TOOLS if t["name"] == "operational_guard")
        self.assertFalse(tool["inputSchema"]["properties"]["features"]["additionalProperties"])

    def test_rag_guard_preserves_permitted_search_without_template(self):
        with mock.patch.object(shared_intelligence, "native_jev_advice", return_value={"selected_action": "inspect", "confidence": .99, "called": True}), mock.patch.object(shared_intelligence, "search_knowledge", return_value={"context": None}) as search:
            shared_intelligence.call("search_knowledge", {"query": "synthetic", "limit": 8, "budget": 4000})
        self.assertEqual(search.call_args.kwargs["limit"], 8)
        self.assertEqual(search.call_args.kwargs["budget"], 4000)

    def test_rag_denied_does_not_search(self):
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": True, "retrievalEnabled": False}))
        with mock.patch.object(shared_intelligence, "search_knowledge") as search, mock.patch.object(shared_intelligence, "native_jev_advice") as advice:
            result = shared_intelligence.call("search_knowledge", {"query": "synthetic"})
        search.assert_not_called(); advice.assert_not_called()
        self.assertIsNone(result["context"])

    def test_rag_advice_preserves_stricter_caller_budget(self):
        with mock.patch.object(shared_intelligence, "native_jev_advice", return_value={"selected_action": "inspect", "confidence": .99, "called": True}), mock.patch.object(shared_intelligence, "search_knowledge", return_value={"context": None}) as search:
            shared_intelligence.call("search_knowledge", {"query": "repository architecture", "budget": 100, "limit": 1})
        self.assertEqual(search.call_args.kwargs['budget'], 100)
        self.assertEqual(search.call_args.kwargs['limit'], 1)

    def test_trivial_query_never_becomes_retrieval_after_refinement(self):
        with mock.patch.object(shared_intelligence, 'native_jev_advice') as advice, mock.patch.object(shared_intelligence, 'RetrievalStore', side_effect=AssertionError('unexpected retrieval')):
            result = shared_intelligence.call('search_knowledge', {'query': 'what is 2 times 3'})
        advice.assert_not_called()
        self.assertEqual(result['retrievedTokens'], 0)

    def test_session_separation_and_provider_payload_no_fingerprint(self):
        with mock.patch.object(shared_intelligence, "native_jev_advice", return_value={"selected_action": "change_strategy", "confidence": .99, "called": True}) as evaluate:
            for host in ("pi", "codex"):
                for _ in range(3):
                    operation.operational_call({"operation": "feedback", "features": {}, "fingerprint": "f" * 64, "outcome": "failure"}, context=NativeContext(host=host, session_id="same"))
        evaluate.assert_not_called()
        self.assertNotIn("f" * 64, str(evaluate.call_args_list))

    def test_codex_mcp_guard_actual_tool_boundary(self):
        with mock.patch.object(mcp, "DecisionSession") as session, mock.patch.object(shared_intelligence, "native_jev_advice", return_value={"selected_action": "continue", "confidence": .99, "called": True}):
            runtime = mcp.NativeMcpRuntime()
            try:
                result = runtime.handle_call(1, {"name": "operational_guard", "arguments": {
                    "operation": "preflight", "features": {"host_allowed": True, "writes": True}}})
            finally:
                runtime.close()
        self.assertEqual(result["structuredContent"]["recommendation"], "proceed")
        self.assertFalse(result["structuredContent"]["applied"])

    def test_checkpoint_missing_legacy_invalid_authorship_has_no_provider_activity(self):
        missing = authored_checkpoint(); missing.pop("decision")
        invalid = authored_checkpoint(); invalid["decision"] = {"decision_type": "progress_strategy"}
        mismatch = authored_checkpoint(); mismatch["decision"]["execution_state"]["revision"] = 2
        legacy = {"schema_version": "quattro-checkpoint-v1", "features": {"host_allowed": True}}
        for envelope in (missing, invalid, mismatch, legacy, None):
            with self.subTest(envelope=envelope), mock.patch.object(operation, "native_jev_advice") as provider:
                result = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope})
            provider.assert_not_called()
            self.assertEqual(result["reason"], "native_authorship_required")
            self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
            self.assertFalse(result["accepted"])
            self.assertFalse(result["called"])

    def test_checkpoint_passes_only_authored_content_and_downgrades_external_provenance(self):
        envelope = authored_checkpoint()
        original = copy.deepcopy(envelope)
        context = NativeContext(host="pi", session_id="current-session", project="current-project")
        session = object()
        with mock.patch.object(operation, "native_jev_advice", side_effect=checkpoint_answer) as provider, \
                mock.patch.object(operation, "consult", wraps=operation.consult) as consultation:
            result = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope},
                                                context=context, decision_session=session)
        self.assertEqual(provider.call_args.args[0], envelope["decision"])
        self.assertIs(provider.call_args.kwargs["context"], context)
        self.assertIs(provider.call_args.kwargs["decision_session"], session)
        self.assertFalse(provider.call_args.kwargs["cacheable"])
        local = consultation.call_args.args[0]
        self.assertEqual(local["state_provenance"], "agent_asserted")
        self.assertEqual(local["provenance"], {"checks_returned": "agent_asserted", "uncertain_property": "unknown"})
        self.assertEqual(envelope, original)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["applied"])
        self.assertFalse(result["action_admitted"])
        self.assertFalse(result["execution_observed"])
        self.assertEqual(result["provider_selected_option"], "AUTHORED_OPTION")
        self.assertNotIn(envelope["decision"]["question"], str(result))
        self.assertNotIn("local-scope", str(result))

    def test_checkpoint_capabilities_come_only_from_trusted_host_argument(self):
        envelope = authored_checkpoint(capability="tool.observed_read")
        envelope["decision"]["context"]["tool_available"] = True
        with mock.patch.object(operation, "native_jev_advice", side_effect=checkpoint_answer):
            denied = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope})
            admitted = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope},
                                                   capabilities={"tool.observed_read": True})
        self.assertFalse(denied["accepted"])
        self.assertEqual(denied["reason"], "hard_policy")
        self.assertTrue(admitted["accepted"])
        with self.assertRaises(ValueError):
            operation.operational_call({"operation": "checkpoint", "checkpoint": envelope,
                                        "capabilities": {"tool.observed_read": True}})

    def test_checkpoint_native_evidence_and_independent_confidence_floor_remain(self):
        envelope = authored_checkpoint()
        valid = checkpoint_answer(envelope["decision"])
        for response in ({**valid, "confidence": .89}, {**valid, "called": False},
                         {**valid, "evidence": "fabricated"}, {**valid, "confidence": float("nan")},
                         {**valid, "selected_action": "invented"}):
            with self.subTest(response=response), mock.patch.object(operation, "native_jev_advice", return_value=response):
                result = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope})
            self.assertFalse(result["accepted"])
            self.assertFalse(result["applied"])
            self.assertEqual(result["acceptance_threshold"], .90)

    def test_top_level_checkpoint_authorship_is_explicit_and_duplicate_or_cross_fields_reject(self):
        envelope = authored_checkpoint(); decision = envelope.pop("decision")
        with mock.patch.object(operation, "native_jev_advice", side_effect=checkpoint_answer) as provider:
            result = operation.operational_call({"operation": "checkpoint", "checkpoint": envelope, "decision": decision})
        self.assertTrue(result["accepted"])
        self.assertEqual(provider.call_args.args[0], decision)
        for arguments in ({"operation": "checkpoint", "checkpoint": authored_checkpoint(), "decision": decision},
                          {"operation": "checkpoint", "checkpoint": authored_checkpoint(), "features": {}},
                          {"operation": "task", "decision": decision}):
            with mock.patch.object(operation, "native_jev_advice") as provider, self.assertRaises(ValueError):
                operation.operational_call(arguments)
            provider.assert_not_called()

    def test_anonymous_native_requests_do_not_share_loop_history(self):
        with mock.patch.object(operation, "native_jev_advice") as provider:
            for _ in range(8):
                result = operation.operational_call({"operation": "feedback", "features": {},
                                                     "fingerprint": "b" * 64, "outcome": "failure"})
                self.assertEqual(result["reason"], "below_threshold")
        self.assertEqual(len(operation._sessions), 0)
        provider.assert_not_called()

    def test_native_activation_symlink_denies_without_provider(self):
        link = Path(self.tmp.name) / "symlink.json"
        link.symlink_to(self.config)
        with mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(link)}), \
                mock.patch.object(operation, "native_jev_advice") as provider:
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True}})
        provider.assert_not_called()
        self.assertEqual(result["reason"], "host_denied")
        self.assertEqual(result["recommendation"], "stop")

    def test_unsafe_config_file_or_parent_link_blocks_opaque_before_reads_or_advisor(self):
        file_link = Path(self.tmp.name) / "file-link.json"
        file_link.symlink_to(self.config)
        real_directory = Path(self.tmp.name) / "real-config"
        real_directory.mkdir()
        (real_directory / "native.json").write_text('{"enabled":false,"operationalEnabled":false}')
        directory_link = Path(self.tmp.name) / "directory-link"
        directory_link.symlink_to(real_directory, target_is_directory=True)
        for path in (file_link, directory_link / "native.json"):
            with self.subTest(path=path), \
                    mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(path)}), \
                    mock.patch.object(Path, "read_text", side_effect=AssertionError("unsafe config read")) as read, \
                    mock.patch.object(operation, "load_native_settings", side_effect=AssertionError("unsafe settings lookup")) as settings, \
                    mock.patch.object(operation, "OperationalAdvisor", side_effect=AssertionError("unsafe advisor construction")) as advisor, \
                    mock.patch.object(operation, "native_jev_advice") as provider:
                result = shared_intelligence.call("operational_guard", {
                    "operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
            read.assert_not_called(); settings.assert_not_called(); advisor.assert_not_called(); provider.assert_not_called()
            self.assertEqual(result["reason"], "host_denied")
            self.assertEqual(result["recommendation"], "stop")
            self.assertTrue(result["applied"])
            self.assertFalse(result["called"])
            self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
        self.assertEqual(len(operation._sessions), 0)

    def test_advisory_preferences_cannot_disable_host_preflight_or_no_progress_guards(self):
        for settings_enabled, session_enabled in ((False, True), (True, False), (False, False)):
            with self.subTest(settings=settings_enabled, session=session_enabled):
                self.config.write_text(json.dumps({"enabled": settings_enabled, "operationalEnabled": True}))
                context = NativeContext(host="pi", session_id=f"preferences-{settings_enabled}-{session_enabled}",
                                        session_enabled=session_enabled)
                with mock.patch.object(operation, "native_jev_advice") as provider:
                    for risks, expected in (({"host_allowed": True, "opaque": True}, "opaque_operation"),
                                            ({"host_allowed": True, "sensitive": True}, "owner_required"),
                                            ({"host_allowed": False}, "host_denied")):
                        result = operation.operational_call({"operation": "preflight", "features": risks}, context=context)
                        self.assertEqual(result["reason"], expected)
                        self.assertTrue(result["applied"])
                        self.assertFalse(result["called"])
                    results = [operation.operational_call({"operation": "feedback", "features": {},
                                "fingerprint": "c" * 64, "outcome": "failure"}, context=context) for _ in range(4)]
                    self.assertEqual(results[2]["recommendation"], "change_plan")
                    self.assertEqual(results[3]["reason"], "identical_loop")
                    self.assertEqual(results[3]["recommendation"], "ask_owner")
                    self.assertTrue(results[3]["applied"])
                    checkpoint = operation.operational_call({"operation": "checkpoint", "checkpoint": authored_checkpoint()},
                                                            context=context)
                    self.assertEqual(checkpoint["reason"], "disabled")
                    self.assertFalse(checkpoint["requested"])
                    self.assertFalse(checkpoint["called"])
                provider.assert_not_called()

    def test_advisory_toggle_cannot_reset_existing_no_progress_state(self):
        active = NativeContext(host="pi", session_id="same-guard-session")
        inactive = NativeContext(host="pi", session_id="same-guard-session", session_enabled=False)
        arguments = {"operation": "feedback", "features": {}, "fingerprint": "d" * 64, "outcome": "unchanged"}
        with mock.patch.object(operation, "native_jev_advice") as provider:
            first = operation.operational_call(arguments, context=active)
            second = operation.operational_call(arguments, context=inactive)
            third = operation.operational_call(arguments, context=active)
            fourth = operation.operational_call(arguments, context=inactive)
        self.assertEqual(first["reason"], "below_threshold")
        self.assertEqual(second["reason"], "below_threshold")
        self.assertEqual(third["recommendation"], "change_plan")
        self.assertEqual(fourth["reason"], "identical_loop")
        provider.assert_not_called()

    def test_explicit_host_guard_disable_remains_independent(self):
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": False}))
        with mock.patch.object(operation, "native_jev_advice") as provider:
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
        self.assertEqual(result["reason"], "disabled")
        self.assertFalse(result["applied"])
        provider.assert_not_called()

    def test_missing_config_preserves_existing_host_guard_default(self):
        self.config.unlink()
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("missing config read")) as read, \
                mock.patch.object(operation, "native_jev_advice") as provider:
            result = shared_intelligence.call("operational_guard", {
                "operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
        read.assert_not_called(); provider.assert_not_called()
        self.assertEqual(result["reason"], "disabled")
        self.assertFalse(result["applied"])

    def test_existing_nonregular_config_cannot_disable_opaque_guard(self):
        directory = Path(self.tmp.name) / "configuration-directory"
        directory.mkdir()
        paths = [directory]
        if hasattr(os, "mkfifo"):
            fifo = Path(self.tmp.name) / "configuration-fifo"
            os.mkfifo(fifo)
            paths.append(fifo)
        for path in paths:
            with self.subTest(path=path), \
                    mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(path)}), \
                    mock.patch.object(Path, "read_text", side_effect=AssertionError("nonregular config read")) as read, \
                    mock.patch.object(operation, "load_native_settings", side_effect=AssertionError("unsafe settings lookup")) as settings, \
                    mock.patch.object(operation, "OperationalAdvisor") as advisor, \
                    mock.patch.object(operation, "native_jev_advice") as provider:
                result = shared_intelligence.call("operational_guard", {
                    "operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
            read.assert_not_called(); settings.assert_not_called(); advisor.assert_not_called(); provider.assert_not_called()
            self.assertEqual(result["reason"], "host_denied")
            self.assertEqual(result["recommendation"], "stop")
            self.assertTrue(result["applied"])
            self.assertFalse(result["requested"])
        self.assertEqual(len(operation._sessions), 0)

    def test_nonboolean_host_flag_or_malformed_config_cannot_disable_opaque_guard(self):
        values = [json.dumps({"enabled": False, "operationalEnabled": value})
                  for value in ("false", 0, 1, None, [], {})]
        values.extend(("[]", "null", "{invalid"))
        for value in values:
            self.config.write_text(value)
            with self.subTest(value=value), \
                    mock.patch.object(operation, "load_native_settings", side_effect=AssertionError("unsafe settings lookup")) as settings, \
                    mock.patch.object(operation, "OperationalAdvisor") as advisor, \
                    mock.patch.object(operation, "native_jev_advice") as provider:
                result = shared_intelligence.call("operational_guard", {
                    "operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
            settings.assert_not_called(); advisor.assert_not_called(); provider.assert_not_called()
            self.assertEqual(result["reason"], "host_denied")
            self.assertEqual(result["recommendation"], "stop")
            self.assertTrue(result["applied"])
            self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
        self.assertEqual(len(operation._sessions), 0)

    def test_unsafe_xdg_config_origin_does_not_become_trusted_after_resolution(self):
        actual = Path(self.tmp.name) / "actual-xdg"
        (actual / "quattro").mkdir(parents=True)
        (actual / "quattro/native-intelligence.json").write_text('{"enabled":false,"operationalEnabled":false}')
        alias = Path(self.tmp.name) / "alias-xdg"
        alias.symlink_to(actual, target_is_directory=True)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(alias)}):
            os.environ.pop("QUATTRO_NATIVE_INTELLIGENCE_CONFIG", None)
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("linked origin read")) as read, \
                    mock.patch.object(operation, "OperationalAdvisor") as advisor, \
                    mock.patch.object(operation, "native_jev_advice") as provider:
                result = shared_intelligence.call("operational_guard", {
                    "operation": "preflight", "features": {"host_allowed": True, "opaque": True}})
        read.assert_not_called(); advisor.assert_not_called(); provider.assert_not_called()
        self.assertEqual(result["reason"], "host_denied")
        self.assertEqual(result["recommendation"], "stop")
