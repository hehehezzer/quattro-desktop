"""Legacy diagnostics cannot manufacture provider decisions."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class RetiredBenchmarkTests(unittest.TestCase):
    def test_historical_benchmark_is_explicitly_retired(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).parents[1] / "scripts/benchmark_jev.py")],
            env={}, capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["status"], "retired")
        self.assertIs(evidence["provider_attempted"], False)


if __name__ == "__main__":
    unittest.main()
