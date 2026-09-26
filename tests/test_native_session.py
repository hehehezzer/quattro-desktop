"""Remote Codex must receive workspace grants at the server, not its TUI."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from quattro_agent import native_session


class NativeRemoteArgumentsTests(unittest.TestCase):
    def test_roots_move_to_server_with_workspace_policy_preserved(self):
        command = ['codex', '--add-dir', '/vault one', '--add-dir=/project-vault',
                   '-a', 'on-request', '-s', 'workspace-write', '-C', '/workspace']
        frontend, backend = native_session._codex_remote_arguments(command)
        self.assertEqual(frontend, ['codex', '-a', 'on-request', '-s', 'workspace-write', '-C', '/workspace'])
        self.assertIn('sandbox_mode="workspace-write"', backend)
        self.assertIn('approval_policy="on-request"', backend)
        value = next(arg.split('=', 1)[1] for arg in backend if arg.startswith('sandbox_workspace_write.writable_roots='))
        self.assertEqual(json.loads(value), ['/vault one', '/project-vault'])
        self.assertEqual(command[1], '--add-dir')  # Do not mutate caller-owned arguments.

    def test_read_only_resume_and_developer_policy_are_preserved(self):
        policy = 'developer_instructions="literal --add-dir text"'
        command = ['codex', '--sandbox=read-only', '--ask-for-approval', 'on-request',
                   '--config', policy, '--add-dir', '/vault', 'resume', '--all', '-C', '/repo']
        frontend, backend = native_session._codex_remote_arguments(command)
        self.assertEqual(frontend[-4:], ['resume', '--all', '-C', '/repo'])
        self.assertIn('sandbox_mode="read-only"', backend)
        self.assertIn(policy, backend)
        self.assertNotIn('--add-dir', frontend)
        self.assertNotIn('sandbox_mode="danger-full-access"', backend)

    def test_confirmed_full_access_is_mirrored_not_invented(self):
        _, backend = native_session._codex_remote_arguments(
            ['codex', '--dangerously-bypass-approvals-and-sandbox', '--add-dir', '/vault'])
        self.assertIn('sandbox_mode="danger-full-access"', backend)
        self.assertIn('approval_policy="never"', backend)
        self.assertEqual(native_session._codex_remote_arguments(['codex', '-C', '/repo'])[1], [])

    def test_quoted_unicode_roots_are_values_not_shell_fragments(self):
        root = '/vault space/"quoted"/\u2603/$HOME;not-a-command'
        _, backend = native_session._codex_remote_arguments(['codex', '--add-dir', root, '--add-dir', root])
        self.assertEqual(json.loads(backend[-1].split('=', 1)[1]), [root])

    def test_missing_values_fail_before_launch(self):
        for flag in ('--add-dir', '-s', '-a', '-c'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                native_session._codex_remote_arguments(['codex', flag])
        with self.assertRaises(ValueError):
            native_session._codex_remote_arguments(['codex', '--add-dir='])

    def test_positional_text_is_not_interpreted_as_permissions(self):
        command = ['codex', '--', '--add-dir', '/literal-prompt']
        self.assertEqual(native_session._codex_remote_arguments(command), (command, []))

    def test_actual_launcher_places_root_override_only_on_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = mock.Mock(url='http://127.0.0.1:1', token='fixture-not-a-credential')
            transport.start.return_value = transport
            bridge = mock.Mock()
            bridge.ready.wait.return_value = True
            bridge.closed.is_set.return_value = False
            child = mock.Mock()
            child.wait.return_value = 0
            child.poll.return_value = 0
            factory = mock.Mock(side_effect=AssertionError('startup must not create an agent'))
            with mock.patch.object(native_session, 'TurnGate'), \
                 mock.patch.object(native_session, 'TurnTransport', return_value=transport), \
                 mock.patch.object(native_session, 'CodexTurnBridge', return_value=bridge) as make_bridge, \
                 mock.patch.object(native_session.subprocess, 'Popen', return_value=child) as popen:
                result = native_session.launch_routed_native(
                    agent='codex', binary='codex', command=['codex', '--add-dir', '/vault',
                        '-s', 'read-only', '-a', 'on-request', '-C', str(root)], env={}, config={},
                    directory=root, session_id='fixture', account='account-1', state_root=root,
                    runtime_factory=factory)
            self.assertEqual(result, 0)
            frontend = popen.call_args.args[0]
            backend = make_bridge.call_args.args[1]
            self.assertIn('--remote', frontend)
            self.assertNotIn('--add-dir', frontend)
            self.assertFalse(any(arg.startswith('sandbox_workspace_write.writable_roots=') for arg in frontend))
            self.assertIn('sandbox_workspace_write.writable_roots=["/vault"]', backend)
            self.assertIn('sandbox_mode="read-only"', backend)
            self.assertEqual(backend[-2:], ['app-server', '--stdio'])
            factory.assert_not_called()
            transport.close.assert_called_once()
            bridge.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
