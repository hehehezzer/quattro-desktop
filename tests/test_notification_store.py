"""Archive privacy/retention tests use synthetic records in a private directory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = Path(__file__).parents[1] / 'src/quattro-notification-store'
class NotificationStoreTests(unittest.TestCase):
    def test_roundtrip_permissions_limits_and_no_action_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            env = dict(os.environ, HOME=folder, XDG_STATE_HOME=str(base / 'state'))
            def call(action, payload=None):
                return subprocess.run([sys.executable, str(SOURCE), action], env=env,
                    input=json.dumps(payload) + '\n' if payload is not None else None,
                    text=True, capture_output=True, timeout=3)
            now = int(time.time() * 1000)
            records = [{'key': str(n), 'nativeId': str(n), 'app': 'Fixture', 'summary': 'Notice',
                        'body': 'Body', 'time': now-n, 'urgency': 1, 'seen': False,
                        'actions': ['unsafe'], 'command': 'unsafe'} for n in range(120)]
            records.append({'key':'stale', 'time':now-86400001})
            self.assertEqual(call('write', records).returncode, 0)
            result=call('read'); self.assertEqual(result.returncode, 0)
            entries=json.loads(result.stdout)['entries']; self.assertEqual(len(entries), 100)
            self.assertEqual(entries[0]['key'], '0')
            self.assertNotIn('actions', entries[0]); self.assertNotIn('command', entries[0])
            directory=base/'state/quattro/notifications'; history=directory/'history.json'
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(history.stat().st_mode & 0o777, 0o600)
            self.assertEqual(call('write', []).returncode, 0)
            self.assertEqual(json.loads(call('read').stdout)['entries'], [])
            history.unlink(); outside=base/'sentinel'; outside.write_text('unchanged')
            history.symlink_to(outside)
            result=call('write', records); self.assertNotEqual(result.returncode,0)
            self.assertNotIn('Body',result.stdout); self.assertEqual(outside.read_text(),'unchanged')

    def test_old_corrupt_or_nonlist_payload_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            env=dict(os.environ, HOME=folder, XDG_STATE_HOME=str(Path(folder)/'state'))
            result=subprocess.run([sys.executable,str(SOURCE),'write'],env=env,input='{"body":"private"}\n',
                text=True,capture_output=True,timeout=3)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('private',result.stdout)
            self.assertIn('unavailable',result.stdout)

if __name__ == '__main__': unittest.main()
