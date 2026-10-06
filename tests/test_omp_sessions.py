from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    import fcntl
except ImportError:
    fcntl = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.herdr_runtime import HerdrError, HerdrRuntime, HerdrSession
from quattro_agent.omp_sessions import OMPSessionError, OMPSessionRegistry


@unittest.skipUnless(fcntl is not None, "Herdr registry requires Unix locking")
class OMPSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "project"
        self.directory.mkdir()
        self.socket_path = self.root / "named.sock"
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        self.addCleanup(self.server.close)
        self.path = self.root / "private" / "sessions.json"
        self.registry = OMPSessionRegistry(self.path)
        self.runtime = HerdrRuntime(self.socket_path)
        self.handle = HerdrSession("w1", "w1:p2")

    def begin(self):
        return self.registry.begin(socket=self.socket_path, directory=self.directory)

    def active(self):
        logical = self.begin()
        self.registry.created(logical, self.handle)
        return logical

    def observation(self, logical, native="native-1", **overrides):
        kwargs = dict(socket=self.socket_path, directory=self.directory, handle=self.handle,
                      native_session_id=native)
        kwargs.update(overrides)
        self.registry.observe_native(logical, **kwargs)

    def test_pending_identity_and_atomic_private_metadata_only(self):
        logical = self.begin()
        pending = self.registry.get(logical)
        self.assertEqual(pending["lifecycle"], "launch_pending")
        self.assertEqual(pending["identityState"], "pending")
        self.assertIsNone(pending["nativeSessionId"])
        self.assertFalse(pending["coordinationSupported"])
        self.assertFalse(pending["nativeRestartResumeSupported"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.registry.created(logical, self.handle)
        self.assertEqual(self.registry.get(logical)["pane"], "w1:p2")
        fields = json.loads(self.path.read_text())["sessions"][logical]
        self.assertTrue({"argv", "environment", "prompt", "response"}.isdisjoint(fields))
        self.assertEqual(list(self.path.parent.glob(".omp-sessions-*")), [])

    def test_wrong_tuple_is_rejected_before_runtime_read(self):
        logical = self.active()
        for handle, directory in ((HerdrSession("w2", "w2:p2"), self.directory),
                                  (HerdrSession("w1", "w1:p9"), self.directory),
                                  (self.handle, self.root)):
            with self.subTest(handle=handle, directory=directory), patch.object(self.runtime, "status") as read:
                with self.assertRaises(OMPSessionError):
                    self.registry.status(self.runtime, logical, directory=directory, handle=handle)
                read.assert_not_called()
        with self.assertRaises(OMPSessionError):
            self.observation(logical, handle=HerdrSession("w2", "w2:p2"))

    def test_observation_is_not_replaceable_and_attachment_requires_live_state(self):
        logical = self.active()
        observed = dict(workspace_id="w1", pane_id="w1:p2", agent_status="idle")
        with patch.object(self.runtime, "status", return_value=observed):
            with self.assertRaisesRegex(OMPSessionError, "unverified"):
                self.registry.verify_attachment(self.runtime, logical, directory=self.directory,
                                                handle=self.handle, native_session_id="native-1")
            self.observation(logical)
            selected = self.registry.verify_attachment(self.runtime, logical, directory=self.directory,
                                                      handle=self.handle, native_session_id="native-1")
            self.assertEqual(selected["attachment"], "existing_pane_only")
            self.assertFalse(selected["approvalGranted"])
            with self.assertRaises(OMPSessionError):
                self.registry.verify_attachment(self.runtime, logical, directory=self.directory,
                                                handle=self.handle, native_session_id="native-2")
        with self.assertRaises(OMPSessionError):
            self.observation(logical, native="native-2")
        for state in ("unknown", "done", "future-state"):
            with patch.object(self.runtime, "status", return_value=dict(observed, agent_status=state)):
                with self.assertRaises(OMPSessionError):
                    self.registry.verify_attachment(self.runtime, logical, directory=self.directory,
                                                    handle=self.handle, native_session_id="native-1")

    def test_launch_uncertainty_cannot_adopt_or_replay(self):
        logical = self.begin()
        self.registry.mark_launch_uncertain(logical)
        with self.assertRaises(OMPSessionError):
            self.registry.created(logical, self.handle)
        with self.assertRaises(OMPSessionError):
            self.registry.mark_launch_uncertain(logical)
        self.assertIsNone(self.registry.get(logical)["pane"])

    def test_one_herdr_tuple_cannot_be_rebound_to_a_new_logical_session(self):
        first = self.active()
        second = self.begin()
        with self.assertRaisesRegex(OMPSessionError, "already belongs"):
            self.registry.created(second, self.handle)
        self.assertEqual(self.registry.get(first)["lifecycle"], "active")
        self.assertEqual(self.registry.get(second)["lifecycle"], "launch_pending")

    def test_concurrent_writers_preserve_all_launch_intents(self):
        errors, identifiers = [], []
        def launch():
            try:
                identifiers.append(self.begin())
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=launch) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(set(identifiers)), 8)
        self.assertEqual(set(json.loads(self.path.read_text())["sessions"]), set(identifiers))

    def test_status_race_with_close_does_not_authorize_attachment(self):
        logical = self.active()
        self.observation(logical)
        def closing(_handle):
            self.registry.begin_close(logical, socket=self.socket_path, directory=self.directory, handle=self.handle)
            return dict(workspace_id="w1", pane_id="w1:p2", agent_status="idle")
        with patch.object(self.runtime, "status", side_effect=closing):
            with self.assertRaisesRegex(OMPSessionError, "changed during"):
                self.registry.verify_attachment(self.runtime, logical, directory=self.directory,
                                                handle=self.handle, native_session_id="native-1")

    def test_close_bookkeeping_never_takes_over_runtime_ownership(self):
        logical = self.active()
        self.registry.begin_close(logical, socket=self.socket_path, directory=self.directory, handle=self.handle)
        with patch.object(self.runtime, "_request") as request:
            with self.assertRaisesRegex(HerdrError, "unowned"):
                self.runtime.close(self.handle)
            request.assert_not_called()
        self.registry.finish_close(logical, confirmed=False)
        self.assertEqual(self.registry.get(logical)["lifecycle"], "close_uncertain")
        with self.assertRaises(OMPSessionError):
            self.registry.begin_close(logical, socket=self.socket_path, directory=self.directory, handle=self.handle)
        with self.assertRaises(OMPSessionError):
            self.registry.finish_close(logical, confirmed=True)

    def test_confirmed_close_keeps_historical_metadata(self):
        logical = self.active()
        self.registry.begin_close(logical, socket=self.socket_path, directory=self.directory, handle=self.handle)
        self.registry.finish_close(logical, confirmed=True)
        self.assertEqual(self.registry.get(logical)["lifecycle"], "closed")
        with patch.object(self.runtime, "status") as read:
            with self.assertRaises(OMPSessionError):
                self.registry.status(self.runtime, logical, directory=self.directory, handle=self.handle)
            read.assert_not_called()

    def test_socket_permissions_owner_and_inode_are_bound(self):
        logical = self.active()
        self.socket_path.chmod(0o666)
        with self.assertRaises(OMPSessionError):
            self.observation(logical)
        self.socket_path.chmod(0o600)
        # Replacement uses another actual socket inode while the original stays open.
        self.socket_path.unlink()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(replacement.close)
        replacement.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        with self.assertRaisesRegex(OMPSessionError, "identity changed"):
            self.observation(logical)
        with patch("quattro_agent.omp_sessions.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(OMPSessionError):
                self.begin()

    def test_workspace_replacement_is_not_a_resume(self):
        logical = self.active()
        self.directory.rename(self.root / "original-project")
        self.directory.mkdir()
        with self.assertRaisesRegex(OMPSessionError, "identity changed"):
            self.observation(logical)

    def test_invalid_paths_and_symlinks_never_read_target(self):
        for path in (Path("relative"), self.root / ".." / "escape", Path("/tmp/invalid\nname")):
            with self.assertRaises(OMPSessionError):
                OMPSessionRegistry(path)
        self.path.parent.mkdir(mode=0o700)
        victim = self.root / "untouched"
        victim.write_text("must-not-read-or-write")
        self.path.symlink_to(victim)
        with self.assertRaises(OMPSessionError):
            self.begin()
        self.assertEqual(victim.read_text(), "must-not-read-or-write")
        self.path.unlink()
        self.path.with_name(self.path.name + ".lock").unlink()
        self.path.with_name(self.path.name + ".lock").symlink_to(victim)
        with self.assertRaises(OMPSessionError):
            self.begin()
        self.assertEqual(victim.read_text(), "must-not-read-or-write")

    def test_corrupt_or_nonprivate_preimage_is_preserved(self):
        self.begin()
        for data in ('{', '{"schemaVersion":1,"schemaVersion":1,"sessions":{}}',
                     '{"schemaVersion":1,"sessions":{},"prompt":"must-not"}',
                     '{"schemaVersion":1,"sessions":{"qomp_bad":{}}}'):
            self.path.write_text(data)
            with self.assertRaises(OMPSessionError):
                self.begin()
            self.assertEqual(self.path.read_text(), data)
        self.path.chmod(0o644)
        with self.assertRaises(OMPSessionError):
            self.begin()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

    def test_fifo_and_hardlinked_preimages_fail_before_read(self):
        self.path.parent.mkdir(mode=0o700)
        os.mkfifo(self.path, mode=0o600)
        with self.assertRaisesRegex(OMPSessionError, "regular"):
            self.begin()
        self.path.unlink()
        target = self.root / "private-file"
        target.write_text("must-not-read-or-replace")
        target.chmod(0o600)
        os.link(target, self.path)
        with self.assertRaisesRegex(OMPSessionError, "regular"):
            self.begin()
        self.assertEqual(target.read_text(), "must-not-read-or-replace")

    def test_out_of_lock_preimage_change_is_not_overwritten(self):
        logical = self.begin()
        original = self.registry._write
        def changed(rows, preimage):
            self.path.write_text("external-change")
            return original(rows, preimage)
        with patch.object(self.registry, "_write", side_effect=changed):
            with self.assertRaisesRegex(OMPSessionError, "outside its lock"):
                self.registry.created(logical, self.handle)
        self.assertEqual(self.path.read_text(), "external-change")

    def test_lock_wait_is_bounded_and_stale_records_are_not_reset(self):
        self.begin()
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with self.assertRaisesRegex(OMPSessionError, "lock unavailable"):
                OMPSessionRegistry(self.path, lock_timeout=0.02).get("qomp_unknown")

    def test_runtime_error_and_mismatched_response_do_not_mutate_registry(self):
        logical = self.active()
        before = self.path.read_bytes()
        for result in (HerdrError("unavailable"), dict(workspace_id="w2", pane_id="w1:p2", agent_status="idle")):
            with patch.object(self.runtime, "status", **({"side_effect": result} if isinstance(result, Exception)
                                                         else {"return_value": result})):
                with self.assertRaises((HerdrError, OMPSessionError)):
                    self.registry.status(self.runtime, logical, directory=self.directory, handle=self.handle)
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
