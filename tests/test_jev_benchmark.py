"""Hermetic benchmark outcome regressions; no provider calls."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'benchmark_jev', Path(__file__).parents[1] / 'scripts/benchmark_jev.py',
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class JevBenchmarkTests(unittest.TestCase):
    def test_unavailable_target_is_an_outcome_for_both_entrypoints(self):
        error = benchmark.ConfigError('no configured execution target')
        gate = mock.Mock()
        gate.begin.side_effect = error
        with mock.patch.object(benchmark, 'route_turn', side_effect=error):
            for entrypoint in (None, gate):
                elapsed, outcome = benchmark.measure_route(
                    'research', 'Research current sources', 'OFF', entrypoint,
                    Path('unused'), (),
                )
                self.assertGreaterEqual(elapsed, 0)
                self.assertEqual(outcome, 'no_eligible_target')


if __name__ == '__main__':
    unittest.main()
