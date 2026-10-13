from __future__ import annotations

import copy
import datetime as dt
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_native_usage as usage


NOW = 1_800_000_000


def quota(limit_id="secondary", minutes=10080, fraction=0.193, reset=NOW + 3600):
    return {
        "id": f"openai-codex:{limit_id}",
        "amount": {"usedFraction": fraction},
        "window": {"durationMs": minutes * 60000, "resetsAt": reset * 1000},
    }


def payload(limits=None, fetched=NOW):
    return {"reports": [{
        "provider": "openai-codex", "fetchedAt": fetched * 1000,
        "metadata": {"planType": "plus"},
        "limits": [quota()] if limits is None else limits,
    }]}


class NativeUsageNormalizationTests(unittest.TestCase):
    def setUp(self):
        clock = mock.patch.object(usage.time, "time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def test_filters_account_wide_windows_and_converts_units(self):
        five_hour = quota("primary", 300, 0.1274, NOW + 1200)
        five_hour["amount"].update({"used": 99, "limit": 100})
        weekly = quota()
        weekly["amount"] = {"used": 7, "limit": 40}
        data = payload([
            weekly,
            quota("model:gpt-example", 60, 0.99),
            {"id": "other-provider:primary"},
            five_hour,
        ], fetched=NOW - 30)
        data["reports"].append({"provider": "other-provider", "limits": []})

        result = usage.normalize(data)

        self.assertEqual(result["primary"], {
            "usedPercent": 12.7, "resetAt": NOW + 1200,
            "windowMinutes": 300, "label": "5h",
        })
        self.assertEqual(result["secondary"], {
            "usedPercent": 17.5, "resetAt": NOW + 3600,
            "windowMinutes": 10080, "label": "W",
        })
        self.assertEqual(result["fetchedAt"], (NOW - 30) * 1000)
        self.assertEqual(result["lastSuccessfulRefresh"],
                         dt.datetime.fromtimestamp(NOW - 30, dt.timezone.utc).isoformat())
        self.assertEqual(result["plan"], "plus")

    def test_absent_five_hour_window_stays_absent(self):
        result = usage.normalize(payload())
        self.assertEqual(result["primary"], {
            "usedPercent": 19.3, "resetAt": NOW + 3600,
            "windowMinutes": 10080, "label": "W",
        })
        self.assertIsNone(result["secondary"])

    def test_invalid_quota_values_do_not_become_zero_or_clamped_limits(self):
        invalid = [quota("primary", fraction=value)
                   for value in (-0.1, 1.1, True, float("nan"), "0.5")]
        invalid.extend([quota("primary", minutes=0), quota("primary", minutes=-300)])
        no_capacity = quota("primary")
        no_capacity["amount"] = {"used": 7, "limit": 0}
        invalid.append(no_capacity)
        result = usage.normalize(payload(invalid + [quota()]))
        self.assertEqual(result["primary"]["usedPercent"], 19.3)
        self.assertEqual(result["primary"]["label"], "W")
        self.assertIsNone(result["secondary"])
        with self.assertRaises(ValueError):
            usage.normalize(payload(invalid))

    def test_multiple_native_accounts_are_ambiguous_in_either_order(self):
        first = payload()["reports"][0]
        second = payload([quota(fraction=0.85)])["reports"][0]
        for reports in ([first, second], [second, first], []):
            with self.subTest(reports=len(reports)):
                with self.assertRaises(ValueError):
                    usage.normalize({"reports": reports})


class NativeUsageCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = pathlib.Path(directory.name) / "usage" / "native-omp.json"
        cache_patch = mock.patch.object(usage, "CACHE", self.cache)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        clock = mock.patch.object(usage.time, "time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        executable = mock.patch.object(usage.shutil, "which", return_value=sys.executable)
        executable.start()
        self.addCleanup(executable.stop)

    def refresh(self, data=None, error=None):
        # Only the external collector is replaced; normalization, cache I/O and
        # display freshness all exercise the real helper with isolated storage.
        result = subprocess.CompletedProcess(
            ["omp"], 0, stdout=json.dumps(data).encode(), stderr=b"",
        )
        output = io.StringIO()
        with mock.patch.object(usage.subprocess, "run", return_value=result, side_effect=error), \
             redirect_stdout(output):
            usage.main()
        return json.loads(output.getvalue())

    def test_success_replaces_saved_quota_with_private_normalized_state(self):
        self.refresh(payload([quota(fraction=0.1)]))
        result = self.refresh(payload([quota(fraction=0.42)]))
        self.assertEqual(result["primary"]["usedPercent"], 42)
        self.assertEqual(result["status"], "live")
        self.assertFalse(result["stale"])
        stored = usage.saved()
        self.assertEqual(stored["primary"], result["primary"])
        self.assertEqual(stored["fetchedAt"], NOW * 1000)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.cache.parent.iterdir()), [self.cache])

    def test_failed_or_timed_out_refresh_preserves_last_good_cache(self):
        baseline = self.refresh(payload())
        saved_bytes = self.cache.read_bytes()
        ambiguous = payload()
        ambiguous["reports"].append(copy.deepcopy(ambiguous["reports"][0]))
        cases = [
            (None, subprocess.CalledProcessError(1, ["omp"])),
            (None, subprocess.TimeoutExpired(["omp"], 35)),
            ({"reports": []}, None),
            (ambiguous, None),
        ]
        for data, error in cases:
            with self.subTest(error=type(error).__name__):
                result = self.refresh(data, error)
                self.assertEqual(self.cache.read_bytes(), saved_bytes)
                self.assertEqual(result["primary"], baseline["primary"])
                self.assertEqual(result["fetchedAt"], baseline["fetchedAt"])
                self.assertEqual(result["lastSuccessfulRefresh"], baseline["lastSuccessfulRefresh"])
                self.assertEqual(result["status"], "stale")
                self.assertTrue(result["stale"])

    def test_failure_without_saved_limits_is_unavailable(self):
        result = self.refresh(error=subprocess.TimeoutExpired(["omp"], 35))
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["stale"])
        self.assertNotIn("primary", result)
        self.assertFalse(self.cache.exists())

    def test_age_transitions_at_refresh_threshold_without_collector_failure(self):
        for age, status in ((899, "live"), (900, "live"), (901, "stale")):
            with self.subTest(age=age):
                result = self.refresh(payload(fetched=NOW - age))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["stale"], status == "stale")
                self.assertEqual(result["primary"]["usedPercent"], 19.3)

    def test_passed_reset_marks_either_window_stale_despite_recent_fetch(self):
        for limit_id in ("primary", "secondary"):
            for offset, status in ((1, "live"), (-1, "stale")):
                with self.subTest(limit_id=limit_id, offset=offset):
                    limits = [quota("primary", 300), quota("secondary", 10080)]
                    target = 0 if limit_id == "primary" else 1
                    limits[target]["window"]["resetsAt"] = (NOW + offset) * 1000
                    result = self.refresh(payload(limits))
                    self.assertEqual(result["status"], status)
                    self.assertEqual(result["stale"], status == "stale")
                    self.assertEqual(result["fetchedAt"], NOW * 1000)


@unittest.skipUnless(os.name == "posix", "Desktop source launchers require POSIX")
class NativeUsageLauncherTests(unittest.TestCase):
    def test_source_launcher_can_use_interpreter_in_separate_path_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory)
            launcher_dir = home / ".local/bin"
            interpreter_dir = home / ".bun/bin"
            launcher_dir.mkdir(parents=True)
            interpreter_dir.mkdir(parents=True)
            launcher = launcher_dir / "omp"
            launcher.write_text('#!/bin/sh\nexec bun "$@"\n', encoding="utf-8")
            launcher.chmod(0o755)
            interpreter = interpreter_dir / "bun"
            interpreter.write_text(
                "#!" + sys.executable + "\nprint(" + repr(json.dumps(
                    payload([quota(fraction=0.64)])
                )) + ")\n", encoding="utf-8",
            )
            interpreter.chmod(0o755)
            output = io.StringIO()
            with (
                mock.patch.object(usage, "HOME", home),
                mock.patch.object(usage, "CACHE", home / "native-omp.json"),
                mock.patch.object(usage.time, "time", return_value=NOW),
                mock.patch.dict(os.environ, {"PATH": str(interpreter_dir) + os.pathsep + os.defpath}),
                redirect_stdout(output),
            ):
                usage.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "live")
            self.assertEqual(result["primary"]["usedPercent"], 64)
            self.assertEqual(result["primary"]["resetAt"], NOW + 3600)
            self.assertIsNone(result["secondary"])
            self.assertEqual(json.loads((home / "native-omp.json").read_text())["primary"],
                             result["primary"])


if __name__ == "__main__":
    unittest.main()
