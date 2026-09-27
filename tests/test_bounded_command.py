"""Bounded host command output, deadlines, and child lifetime."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest

SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_agent.bounded_command import run_bounded


class BoundedCommandTests(unittest.TestCase):
    def test_output_ceiling(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_bounded([sys.executable, "-c", "print('x' * 1000000)"],
                                 cwd=Path(root), timeout=3, max_output=1024)
        self.assertEqual(result["status"], "truncated")
        self.assertEqual(len(result["output"].encode()), 1024)

    def test_timeout_kills_child(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_bounded([sys.executable, "-c", "import time; time.sleep(5)"],
                                 cwd=Path(root), timeout=0.2)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(result["elapsed_ms"], 2000)

    @unittest.skipUnless(sys.platform == "linux", "Linux process-group probe")
    def test_timeout_kills_spawned_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "descendant.pid"
            code = ("import subprocess,sys,time; "
                    "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    f"open({str(marker)!r},'w').write(str(p.pid)); time.sleep(30)")
            result = run_bounded([sys.executable, "-c", code],
                                 cwd=Path(root), timeout=0.5)
            self.assertEqual(result["status"], "timeout")
            child_pid = int(marker.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                stat = Path(f"/proc/{child_pid}/stat")
                if not stat.exists() or stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.02)
            else:
                self.fail("spawned test descendant survived timeout")

    @unittest.skipUnless(sys.platform == "linux", "Linux process-group probe")
    def test_normal_completion_kills_spawned_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "descendant.pid"
            code = ("import subprocess,sys; "
                    "p=subprocess.Popen([sys.executable,'-c',"
                    "'import os,time; os.close(1); os.close(2); time.sleep(30)']); "
                    f"open({str(marker)!r},'w').write(str(p.pid))")
            result = run_bounded([sys.executable, "-c", code],
                                 cwd=Path(root), timeout=3)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["exit_code"], 0)
            child_pid = int(marker.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                stat = Path(f"/proc/{child_pid}/stat")
                if not stat.exists() or stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.02)
            else:
                self.fail("spawned descendant survived successful test")

    @unittest.skipUnless(sys.platform == "linux", "Linux parent-death probe")
    def test_abrupt_owner_death_kills_test_process(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pid"
            code = ("from pathlib import Path; import os,time; "
                    f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)")
            parent_code = ("from pathlib import Path; import sys; "
                           "from quattro_agent.bounded_command import run_bounded; "
                           f"run_bounded([sys.executable, '-c', {code!r}], "
                           f"cwd=Path({root!r}), timeout=35)")
            env = dict(os.environ, PYTHONPATH=str(SRC))
            owner = subprocess.Popen([sys.executable, "-c", parent_code], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                child_pid = int(marker.read_text())
                owner.kill()
                owner.wait(timeout=2)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    stat = Path(f"/proc/{child_pid}/stat")
                    if not stat.exists() or stat.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("bounded command survived its owner")
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=2)

    @unittest.skipUnless(sys.platform == "linux", "Linux parent-death descendant probe")
    def test_abrupt_owner_death_kills_spawned_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "descendant.pid"
            code = ("import subprocess,sys,time; "
                    "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    f"open({str(marker)!r},'w').write(str(p.pid)); time.sleep(30)")
            parent_code = ("from pathlib import Path; import sys; "
                           "from quattro_agent.bounded_command import run_bounded; "
                           f"run_bounded([sys.executable, '-c', {code!r}], "
                           f"cwd=Path({root!r}), timeout=35)")
            owner = subprocess.Popen([sys.executable, "-c", parent_code],
                                     env=dict(os.environ, PYTHONPATH=str(SRC)),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                descendant_pid = int(marker.read_text())
                owner.kill()
                owner.wait(timeout=2)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    stat = Path(f"/proc/{descendant_pid}/stat")
                    if not stat.exists() or stat.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("spawned descendant survived abrupt owner death")
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
