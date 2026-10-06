"""Configuration guard checks; no OAuth or Discord validity is asserted."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hermes_discord_guard.py"
spec = importlib.util.spec_from_file_location("hermes_discord_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class HermesGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = {"model": {"provider": "openai-codex"},
                       "auth": {"adopt_external_logins": False}, "fallback_models": [],
                       "platform_toolsets": {"discord": []}, "memory": {"memory_enabled": False},
                       "agent": {"disabled_toolsets": ["hermes-discord", "hermes-cli"]},
                       "discord": {"allow_from": "123456789012345678"},
                       "plugins": {"enabled": ["quattro-discord"]}}
        self.policy = {"owner_id": "123456789012345678"}
        self.write()
        for name, content in [(".env", "DISCORD_BOT_TOKEN=synthetic-test-placeholder\n"), ("auth.json", "{}")]:
            path = self.home / name
            path.write_text(content)
            path.chmod(0o600)

    def write(self):
        for name, content in [("config.yaml", json.dumps(self.config)),
                              ("quattro-policy.json", json.dumps(self.policy))]:
            path = self.home / name
            path.write_text(content)
            path.chmod(0o600)

    def test_config_checks_not_live_auth(self):
        self.assertEqual(guard.check(self.home), [])

    def test_missing_oauth_blocks(self):
        (self.home / "auth.json").unlink()
        self.assertIn("missing private profile auth.json", guard.check(self.home))

    def test_missing_owner_blocks(self):
        self.policy["owner_id"] = ""
        self.write()
        self.assertIn("numeric owner ID not configured", guard.check(self.home))

    def test_provider_and_fallback_refused(self):
        self.config["model"]["provider"] = "openai"
        self.config["fallback_models"] = [{"provider": "openrouter"}]
        self.write()
        self.assertGreaterEqual(len(guard.check(self.home)), 2)

    def test_external_adoption_refused(self):
        self.config["auth"]["adopt_external_logins"] = True
        self.write()
        self.assertIn("external credential adoption must be disabled", guard.check(self.home))

    def test_ambient_profile_key_refused(self):
        (self.home / ".env").write_text("DISCORD_BOT_TOKEN=synthetic-test-placeholder\nOPENAI_API_KEY=synthetic-test-placeholder\n")
        self.assertIn("profile .env must contain only the dedicated bot token", guard.check(self.home))

    def test_unapproved_auxiliary_refused(self):
        self.config["auxiliary"] = {"vision": {"provider": "openrouter"}}
        self.write()
        self.assertIn("unapproved auxiliary provider refused", guard.check(self.home))

    def test_custom_endpoint_refused(self):
        self.config["model"]["base_url"] = "https://example.invalid"
        self.write()
        self.assertIn("custom model endpoint/credential refused", guard.check(self.home))

    def test_tool_mutation_refused(self):
        self.config["platform_toolsets"]["discord"] = ["terminal"]
        self.write()
        self.assertIn("conversation execution/external tools must remain disabled", guard.check(self.home))

    def test_role_grants_refused(self):
        self.config["discord"]["allowed_roles"] = "123456789012345678"
        self.write()
        self.assertIn("role/all-user/bot grants refused", guard.check(self.home))

    def test_plugin_disabled_refused(self):
        self.config["plugins"]["enabled"] = []
        self.write()
        self.assertIn("mandatory owner boundary plugin is disabled", guard.check(self.home))

    def test_insecure_auth_permissions_refused(self):
        (self.home / "auth.json").chmod(0o644)
        self.assertIn("auth.json permissions must be 0600", guard.check(self.home))


if __name__ == "__main__":
    unittest.main()
