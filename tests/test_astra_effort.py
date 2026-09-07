from __future__ import annotations

import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

import test_harness_integration as integration
from quattro_agent.policy import PolicyProfile
from quattro_harness import HarnessRuntime


class AstraEffortTests(unittest.TestCase):
    def setUp(self):
        integration.HarnessRuntimeIntegrationTests.setUp(self)
        self.account_home = self.root / "astra-account"
        self.account_home.mkdir()
        self.runtime.account = lambda _config, _account_id=None: {
            "id": "account-1", "codexHome": str(self.account_home),
        }

    def tearDown(self):
        self.temp.cleanup()

    def select(self, model, effort):
        content = f'model = "{model}"\n'
        if effort is not None:
            content += f"model_reasoning_effort = {json.dumps(effort)}\n"
        content += 'plan_mode_reasoning_effort = "medium"\n'
        (self.account_home / "config.toml").write_text(content, encoding="utf-8")

    def test_dispatch_limits_both_accounts_across_tiers_and_escalation(self):
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="", mode="interactive",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        run_id = self.runtime.store.create_run(task_id)
        for account in ("account-1", "account-2"):
            model = f"{account}/gpt-6-astra"
            for tier, exceptional in (("FAST", 0), ("STANDARD", 0), ("REASONING", 0), ("REASONING", 1)):
                for selected in ("low", "high", "medium", "xhigh", "max", "ultra", None, ["low"]):
                    with self.subTest(account=account, tier=tier, exceptional=exceptional, selected=selected):
                        self.select(model, selected)
                        task["private_payload"]["routing"] = {
                            "tier": tier, "exceptional_escalations": exceptional,
                        }
                        expected = (
                            selected if isinstance(selected, str) and selected in {"low", "high"}
                            else "low" if selected is None and tier == "FAST" else "high"
                        )
                        argv, _, _ = self.runtime._agent_plan(
                            task, run_id, PolicyProfile.from_dict(task["policy"]),
                        )
                        self.assertIn(f'model_reasoning_effort="{expected}"', argv)
                        self.assertIn(f'plan_mode_reasoning_effort="{expected}"', argv)
                        metadata = self.runtime.store.display_task(task_id)["metadata"]
                        self.assertEqual(metadata["reasoningEffort"], expected)
                        self.assertEqual(metadata["modelRoute"], model)
                        events = self.runtime.store.display_events(task_id, limit=500)
                        dispatched = [event for event in events if event["type"] == "routing.dispatched"]
                        self.assertEqual(dispatched[-1]["payload"]["reasoningEffort"], expected)

    def test_direct_request_and_returned_effort_match_selected_astra_choice(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"output_text":"hello"}'
        response.headers = {}
        for account in ("account-1", "account-2"):
            for selected, expected in (("low", "low"), ("high", "high"), ("medium", "high"), (None, "low")):
                with self.subTest(account=account, selected=selected):
                    model = f"{account}/gpt-6-astra"
                    self.select(model, selected)
                    with mock.patch("quattro_harness.urllib.request.urlopen", return_value=response) as request:
                        result = self.runtime.direct_response(project=self.project, prompt="reply with hello")
                    body = json.loads(request.call_args.args[0].data)
                    self.assertEqual(body["model"], model)
                    self.assertEqual(body["reasoning"]["effort"], expected)
                    self.assertEqual(result["routing"]["reasoning_effort"], expected)

    def test_other_models_keep_tier_effort_and_exceptional_escalation(self):
        config = self.runtime.config()
        for model in ("auto", "account-1/gpt-5.6-sol", "account-2/gpt-5.6-sol", "other/gpt-6-astra"):
            self.select(model, "low")
            for tier, exceptional, expected in (("FAST", 0, "low"), ("STANDARD", 0, "medium"), ("REASONING", 0, "high"), ("REASONING", 1, "ultra")):
                with self.subTest(model=model, tier=tier, exceptional=exceptional):
                    self.assertEqual(HarnessRuntime._dispatch_reasoning_effort(
                        config, {"tier": tier, "exceptional_escalations": exceptional},
                        model, self.account_home,
                    ), expected)

    def test_other_model_plan_mode_is_not_overridden(self):
        self.select("account-2/gpt-5.6-sol", "low")
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="", mode="interactive",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        argv, _, _ = self.runtime._agent_plan(
            task, self.runtime.store.create_run(task_id), PolicyProfile.from_dict(task["policy"]),
        )
        self.assertFalse(any(argument.startswith("plan_mode_reasoning_effort=") for argument in argv))


if __name__ == "__main__":
    unittest.main()
