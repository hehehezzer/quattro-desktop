"""Legacy diagnostics cannot manufacture provider decisions."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class RetiredBenchmarkTests(unittest.TestCase):
    def test_historical_benchmark_is_explicitly_retired(self):
        for name in ("benchmark_jev.py", "benchmark_decision_plane.py"):
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, "-I", "-B", str(Path(__file__).parents[1] / "scripts" / name)],
                    env={}, capture_output=True, text=True, timeout=5, check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, "")
                evidence = json.loads(result.stdout)
                self.assertEqual(evidence["status"], "retired")
                self.assertIs(evidence["provider_attempted"], False)

    def test_remaining_diagnostic_entrypoints_import_without_legacy_taxonomy(self):
        for name in ("benchmark_decision_plane.py", "benchmark_decision_tasks.py",
                     "probe_runtime_milestones.py"):
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, "-I", "-B", str(Path(__file__).parents[1] / "scripts" / name), "--help"],
                    env={}, capture_output=True, text=True, timeout=5, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
