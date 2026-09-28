"""Conservative lyrics normalization, matching, cache, and failure behavior."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

SRC = Path(__file__).parents[1] / "src"


def load_script():
    loader = importlib.machinery.SourceFileLoader("quattro_lyrics", str(SRC / "quattro-lyrics"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


lyrics = load_script()


class LyricsTests(unittest.TestCase):
    def record(self, **changes):
        value = {
            "id": 42,
            "trackName": "Café Song (Live)",
            "artistName": "Artist One & Artist Two",
            "albumName": "Concert",
            "duration": 180.0,
            "instrumental": False,
            "plainLyrics": "First\nSecond",
            "syncedLyrics": "[00:01.20] First\n[00:04.005][00:05.50] Second",
        }
        value.update(changes)
        return value

    def test_lrc_parser_normalizes_sorts_and_supports_multiple_timestamps(self):
        parsed = lyrics.parse_lrc("[ar:Someone]\n[00:04.005][00:05.5] Later\r\n[00:01.20] First\n[00:03.00]   ")
        self.assertEqual(parsed, [
            {"timestampMs": 1200, "text": "First"},
            {"timestampMs": 4005, "text": "Later"},
            {"timestampMs": 5500, "text": "Later"},
        ])
        self.assertEqual(lyrics.active_line_index(parsed, 0), -1)
        self.assertEqual(lyrics.active_line_index(parsed, 1200), 0)
        self.assertEqual(lyrics.active_line_index(parsed, 5499), 1)
        self.assertEqual(lyrics.active_line_index(parsed, 9000), 2)

    def test_matching_is_unicode_aware_but_keeps_versions_and_duration_strict(self):
        record = self.record()
        self.assertTrue(lyrics.record_matches(record, "Café Song (Live)", "Artist Two, Artist One", 181.9))
        self.assertFalse(lyrics.record_matches(record, "Café Song", "Artist Two, Artist One", 180))
        self.assertFalse(lyrics.record_matches(record, "Café Song (Live)", "Different Artist", 180))
        self.assertFalse(lyrics.record_matches(record, "Café Song (Live)", "Artist Two, Artist One", 182.2))

    def test_provider_data_is_normalized_and_malformed_sync_falls_back_to_plain(self):
        key = lyrics.track_identity("Title", "Artist", 10)
        synced = lyrics.normalize_record(self.record(), key)
        self.assertEqual(synced["state"], "synced")
        self.assertEqual(synced["lines"][0], {"timestampMs": 1200, "text": "First"})
        self.assertNotIn("syncedLyrics", synced)
        plain = lyrics.normalize_record(self.record(syncedLyrics="not lrc"), key)
        self.assertEqual(plain["state"], "plain")
        self.assertEqual(plain["plainText"], "First\nSecond")
        instrumental = lyrics.normalize_record(self.record(instrumental=True), key)
        self.assertEqual(instrumental["state"], "instrumental")
        self.assertEqual(instrumental["lines"], [])

    def test_conservative_selection_rejects_wrong_results_and_prefers_album_sync(self):
        plain = self.record(id=1, syncedLyrics="", albumName="Other")
        synced = self.record(id=2)
        wrong = self.record(id=3, trackName="Café Song")
        selected = lyrics.select_record([wrong, plain, synced], "Café Song (Live)", "Artist One and Artist Two", "Concert", 180)
        self.assertEqual(selected["id"], 2)
        self.assertIsNone(lyrics.select_record([wrong], "Café Song (Live)", "Artist One and Artist Two", "Concert", 180))

    def test_positive_and_negative_cache_avoid_repeat_provider_requests_and_expire(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def provider(*args):
                calls.append(args)
                return self.record()

            first = lyrics.lookup("Café Song (Live)", "Artist One & Artist Two", "Concert", 180, root=root, now=1000, provider=provider)
            second = lyrics.lookup("Café Song (Live)", "Artist One & Artist Two", "Concert", 180, root=root, now=1001, provider=provider)
            self.assertEqual(first["state"], "synced")
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(next(root.glob("*.json")).stat().st_mode & 0o777, 0o600)

            misses = []
            missing = lambda *args: misses.append(args) or []
            self.assertEqual(lyrics.lookup("Missing", "Nobody", duration=90, root=root, now=2000, provider=missing)["state"], "unavailable")
            self.assertTrue(lyrics.lookup("Missing", "Nobody", duration=90, root=root, now=2001, provider=missing)["cached"])
            self.assertEqual(len(misses), 1)
            self.assertFalse(lyrics.lookup("Missing", "Nobody", duration=90, root=root, now=2000 + lyrics.NEGATIVE_TTL + 1, provider=missing)["cached"])
            self.assertEqual(len(misses), 2)

    def test_rate_limit_is_persisted_and_suppresses_followup_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = 0

            def limited(*args):
                nonlocal calls
                calls += 1
                raise urllib.error.HTTPError("https://lrclib.net/api/get", 429, "limited", {"Retry-After": "120"}, None)

            first = lyrics.lookup("Song", "Artist", duration=100, root=root, now=500, provider=limited)
            second = lyrics.lookup("Other", "Artist", duration=100, root=root, now=501, provider=limited)
            self.assertEqual(first["state"], "error")
            self.assertEqual(first["retryAfter"], 120)
            self.assertEqual(second["state"], "error")
            self.assertGreaterEqual(second["retryAfter"], 118)
            self.assertEqual(calls, 1)

    def test_get_404_falls_back_to_documented_structured_search(self):
        urls = []

        def fetcher(url):
            urls.append(url)
            if "/api/get?" in url:
                raise urllib.error.HTTPError(url, 404, "missing", {}, None)
            return [self.record()]

        with mock.patch.object(lyrics.time, "sleep") as sleep:
            result = lyrics.provider_lookup("Title", "Artist", "Album", 100, fetcher)
        self.assertEqual(len(result), 1)
        self.assertIn("/api/get?", urls[0])
        self.assertIn("duration=100", urls[0])
        self.assertIn("/api/search?", urls[1])
        sleep.assert_called_once_with(0.25)


if __name__ == "__main__":
    unittest.main()
