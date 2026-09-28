from dataclasses import FrozenInstanceError
from itertools import product
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from quattro_agent.errors import ConfigError
from quattro_agent.jev_preferences import resolve_jev_preference, restore_jev_preference


class JevPreferenceTests(unittest.TestCase):
    def test_default_enabled_without_selection(self):
        result = resolve_jev_preference()
        self.assertTrue(result.enabled)
        self.assertEqual(result.source, 'default')

    def test_exhaustive_precedence(self):
        names = ('cli', 'selection', 'resumed', 'global_default')
        for values in product((None, False, True), repeat=4):
            with self.subTest(values=values):
                result = resolve_jev_preference(**dict(zip(names, values)))
                expected = next((value for value in values if value is not None), True)
                self.assertIs(result.enabled, expected)

    def test_disabled_resume_survives_new_global_default(self):
        restored = restore_jev_preference({'schemaVersion': 1, 'enabled': False})
        self.assertFalse(resolve_jev_preference(resumed=restored, global_default=True).enabled)

    def test_explicit_override_on_resume(self):
        self.assertTrue(resolve_jev_preference(cli=True, resumed=False).enabled)
        self.assertFalse(resolve_jev_preference(cli=False, selection=True, resumed=True).enabled)

    def test_independent_sessions_do_not_share_mutable_state(self):
        first = resolve_jev_preference(selection=True)
        second = resolve_jev_preference(selection=False)
        record = first.session_record()
        record['enabled'] = False
        self.assertTrue(first.enabled)
        self.assertFalse(second.enabled)
        self.assertTrue(first.session_record()['enabled'])
        with self.assertRaises(FrozenInstanceError):
            first.enabled = False

    def test_legacy_absence_is_not_disabled(self):
        self.assertIsNone(restore_jev_preference(None))

    def test_invalid_persisted_metadata_is_not_silently_enabled(self):
        for record in ({}, {'schemaVersion': 2, 'enabled': False},
                       {'schemaVersion': True, 'enabled': True},
                       {'schemaVersion': 1, 'enabled': 'false'},
                       {'schemaVersion': 1, 'enabled': True, 'executionPlan': {}}, []):
            with self.subTest(record=record), self.assertRaises(ConfigError):
                restore_jev_preference(record)

    def test_strict_booleans_even_in_overridden_inputs(self):
        for value in ('false', 'true', 0, 1, {}, []):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                resolve_jev_preference(cli=True, global_default=value)


if __name__ == '__main__':
    unittest.main()
