"""Hermetic transport tests; these are NOT live Discord/model acceptance."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.hermes_bridge import Bridge

OWNER = "123456789012345678"
CHANNEL = "223456789012345678"
GUILD = "323456789012345678"


class HermesBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.now = 1000
        self.calls = []
        def search(query, **kwargs):
            self.calls.append((query, kwargs))
            return {"context": {"sources": ["approved-fixture"]}, "usageEvidence": {"traceId": "fixture", "sourcesSelected": 1}}
        self.policy = {"owner_id": OWNER, "guild_ids": [GUILD], "channel_ids": [CHANNEL],
                       "owner_dms": True, "projects": {"fixture": str(self.project)}}
        self.bridge = Bridge(self.policy, self.root / "state/transport.sqlite3", search=search, clock=lambda: self.now)
        self.src = SimpleNamespace(platform="discord", user_id=OWNER, chat_id=CHANNEL, chat_type="channel",
                                   scope_id=GUILD, thread_id=None, is_bot=False)

    def test_owner_and_destination(self):
        self.assertTrue(self.bridge.authorized(self.src))
        for key, value in [("user_id", "423456789012345678"), ("chat_id", "523456789012345678"),
                           ("scope_id", "623456789012345678"), ("is_bot", True), ("platform", "webhook")]:
            original = getattr(self.src, key)
            setattr(self.src, key, value)
            self.assertFalse(self.bridge.authorized(self.src))
            setattr(self.src, key, original)

    def test_missing_owner_denies(self):
        self.bridge.policy["owner_id"] = ""
        self.assertFalse(self.bridge.authorized(self.src))

    def test_owner_dm_only(self):
        self.src.chat_type, self.src.scope_id = "dm", None
        self.assertTrue(self.bridge.authorized(self.src))
        self.bridge.policy["owner_dms"] = False
        self.assertFalse(self.bridge.authorized(self.src))

    def test_thread_requires_exact_allowlist(self):
        self.src.thread_id = "723456789012345678"
        self.assertFalse(self.bridge.authorized(self.src))
        self.bridge.policy["channel_ids"].append(self.src.thread_id)
        self.assertTrue(self.bridge.authorized(self.src))

    def test_unauthorized_cannot_retrieve_or_create_state(self):
        self.src.user_id = "823456789012345678"
        with self.assertRaises(PermissionError):
            self.bridge.retrieve(self.src, "secret project")
        self.assertEqual(self.calls, [])
        with self.bridge.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM conversations").fetchone()[0], 0)

    def test_dedup_survives_restart(self):
        self.assertTrue(self.bridge.admit(self.src, "923456789012345678"))
        self.assertFalse(self.bridge.admit(self.src, "923456789012345678"))
        reopened = Bridge(self.policy, self.bridge.ledger, clock=lambda: self.now)
        self.assertFalse(reopened.admit(self.src, "923456789012345678"))

    def test_invalid_message_id_denied(self):
        self.assertFalse(self.bridge.admit(self.src, "../spoof"))

    def test_project_scope_isolated(self):
        self.bridge.select_project(self.src, "fixture")
        self.bridge.policy["channel_ids"].append("423456789012345678")
        other = SimpleNamespace(**vars(self.src))
        other.chat_id = "423456789012345678"
        self.assertIsNone(self.bridge.project(other))
        self.assertEqual(self.bridge.project(self.src), "fixture")

    def test_paths_not_model_supplied(self):
        for alias in ["../project", str(self.root), "missing"]:
            with self.assertRaises(ValueError):
                self.bridge.select_project(self.src, alias)

    def test_retrieval_bounded_and_evidence_honest(self):
        self.bridge.select_project(self.src, "fixture")
        result = self.bridge.retrieve(self.src, "project architecture")
        self.assertEqual(self.calls[0][1], {"directory": str(self.project), "budget": 2000, "limit": 5})
        self.assertEqual(result["usageEvidence"]["delivered"], "UNKNOWN")
        self.assertEqual(result["usageEvidence"]["referenced"], "UNKNOWN")

    def test_no_project_does_not_retrieve(self):
        self.assertEqual(self.bridge.retrieve(self.src, "project")["route"], "no_project")
        self.assertEqual(self.calls, [])

    def test_greeting_no_retrieval(self):
        self.bridge.select_project(self.src, "fixture")
        self.assertEqual(self.bridge.chat_context(self.src, "hello"), "")
        self.assertEqual(self.calls, [])

    def test_prompt_generation_cannot_spawn(self):
        self.bridge.select_project(self.src, "fixture")
        self.bridge.chat_context(self.src, "Write a project implementation prompt and /goal prompt")
        with self.bridge.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM requests").fetchone()[0], 0)

    def test_proposal_and_cancel_no_execution(self):
        response = self.bridge.command(self.src, "/q run codex fixture bounded reversible task")
        identifier = response.splitlines()[0].split()[1]
        self.assertIn("never", self.bridge.command(self.src, "/q help"))
        with self.assertRaisesRegex(PermissionError, "BLOCKED"):
            self.bridge.approve(self.src, identifier)
        self.bridge.command(self.src, "/q cancel " + identifier)
        with self.assertRaises(PermissionError):
            self.bridge.approve(self.src, identifier)

    def test_expired_approval(self):
        response = self.bridge.propose(self.src, "pi", "fixture", "review module without edits")
        identifier = response.splitlines()[0].split()[1]
        self.now += 301
        with self.assertRaisesRegex(PermissionError, "expired"):
            self.bridge.approve(self.src, identifier)

    def test_cross_conversation_approval_denied(self):
        response = self.bridge.propose(self.src, "auto", "fixture", "run tests")
        identifier = response.splitlines()[0].split()[1]
        self.bridge.policy["channel_ids"].append("423456789012345678")
        self.src.chat_id = "423456789012345678"
        with self.assertRaisesRegex(PermissionError, "exact conversation"):
            self.bridge.approve(self.src, identifier)

    def test_private_ledger(self):
        self.assertEqual(self.bridge.ledger.stat().st_mode & 0o777, 0o600)

    def test_symlink_project_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        self.policy["projects"] = {"fixture": str(alias)}
        with self.assertRaises(ValueError):
            Bridge(self.policy, self.root / "other.sqlite3")

    def test_malformed_snowflakes(self):
        self.policy["owner_id"] = "*"
        with self.assertRaises(ValueError):
            Bridge(self.policy, self.root / "other.sqlite3")


if __name__ == "__main__":
    unittest.main()
