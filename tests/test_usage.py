from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_agent.cli as agent


class UsageFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 26, 0, 0, tzinfo=dt.timezone.utc)
        self.config = {"usageRefresh": {"enabled": True, "intervalMinutes": 15}}

    def test_recent_usage_is_fresh(self):
        refreshed = self.now - dt.timedelta(minutes=30)
        self.assertFalse(agent.usage_is_overdue(self.config, refreshed.isoformat(), self.now))

    def test_usage_is_stale_after_two_intervals_and_tolerance(self):
        refreshed = self.now - dt.timedelta(minutes=36)
        self.assertTrue(agent.usage_is_overdue(self.config, refreshed.isoformat(), self.now))

    def test_missing_or_invalid_timestamp_is_stale(self):
        self.assertTrue(agent.usage_is_overdue(self.config, None, self.now))
        self.assertTrue(agent.usage_is_overdue(self.config, "not-a-time", self.now))

    def test_disabled_refresh_does_not_age_usage(self):
        config = {"usageRefresh": {"enabled": False, "intervalMinutes": 15}}
        self.assertFalse(agent.usage_is_overdue(config, None, self.now))


class ZedIntegrationTests(unittest.TestCase):
    def test_zed_binary_accepts_supported_cli_names(self):
        with mock.patch.object(
            agent, "command_path",
            side_effect=lambda name: "/usr/bin/zeditor" if name == "zeditor" else None,
        ):
            self.assertEqual(agent.zed_binary(), "/usr/bin/zeditor")

    def test_safe_zed_location_preserves_line_and_column_inside_repository(self):
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            target = root / "module.py"
            target.write_text("value = 1\n", encoding="utf-8")
            self.assertEqual(
                agent.safe_zed_location("module.py:1:1", root),
                f"{target}:1:1",
            )

    def test_zed_location_rejects_outside_repository(self):
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            with self.assertRaises(SystemExit):
                agent.safe_zed_location("/etc/hosts:1", root)

    def test_zed_rejects_non_git_directory_and_secret_bearing_text(self):
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            with self.assertRaises(SystemExit):
                agent.safe_zed_project(root)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            secret = root / "notes.txt"
            secret.write_text("access_token=opaque-secret-value-12345\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                agent.safe_zed_location("notes.txt", root)


class SessionOpenTests(unittest.TestCase):
    def test_terminal_discovery_requires_exact_task_worker_and_foot_executable(self):
        with tempfile.TemporaryDirectory() as value:
            proc = pathlib.Path(value)
            foot = proc / "foot"
            foot.write_text("#!/bin/sh\n", encoding="utf-8")
            foot.chmod(0o755)
            process = proc / "321"
            process.mkdir()
            (process / "exe").symlink_to(foot)
            (process / "cmdline").write_bytes(
                b"/usr/bin/foot\0--app-id\0quattro-ai\0_task-worker\0task_exact\0"
            )
            self.assertEqual(
                agent.session_terminal_pid({"taskId": "task_exact", "sessionId": "task_exact"}, proc),
                321,
            )
            self.assertIsNone(
                agent.session_terminal_pid({"taskId": "task_other", "sessionId": "task_other"}, proc)
            )

    def test_open_session_focuses_only_matching_mapped_quattro_terminal(self):
        session = {
            "sessionId": "task_exact", "taskId": "task_exact",
            "quattroSessionId": "qsession_exact",
        }
        calls: list[list[str]] = []

        def run(command, **_kwargs):
            calls.append(command)
            if command[1:3] == ["clients", "-j"]:
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=json.dumps([{
                        "class": "quattro-ai", "mapped": True,
                        "pid": 321, "address": "0xabc123",
                    }]),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

        with (
            mock.patch.object(agent, "sessions_status", return_value=[session]),
            mock.patch.object(agent, "session_terminal_pid", return_value=321),
            mock.patch.object(agent, "require", return_value="/usr/bin/hyprctl"),
            mock.patch.object(agent.subprocess, "run", side_effect=run),
        ):
            result = agent.open_session("qsession_exact")

        self.assertEqual(result["state"], "focused")
        self.assertEqual(result["terminalPid"], 321)
        self.assertEqual(calls[1], [
            "/usr/bin/hyprctl", "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ])


class UsageRefreshTests(unittest.TestCase):
    def test_native_login_survives_custom_provider_account_read(self):
        self.assertEqual(agent.normalized_account_login(None, True), (True, None))

    def test_rpc_account_identity_remains_authoritative(self):
        self.assertEqual(
            agent.normalized_account_login({"type": "chatgpt"}, False),
            (True, "chatgpt"),
        )

    def test_window_labels_follow_api_duration(self):
        five_hour = agent.normalize_window({"usedPercent": 12, "resetsAt": 1, "windowDurationMins": 300})
        weekly = agent.normalize_window({"usedPercent": 34, "resetsAt": 2, "windowDurationMins": 10080})
        self.assertEqual(five_hour["label"], "5h")
        self.assertEqual(weekly["label"], "W")

    def test_weekly_only_window_is_not_mislabeled_as_five_hour(self):
        window = agent.normalize_window({"usedPercent": 0, "resetsAt": 1, "windowDurationMins": 10080})
        self.assertEqual(window["label"], "W")

    def test_refresh_all_visits_each_enabled_account(self):
        config = {"accounts": [
            {"id": "account-1", "enabled": True},
            {"id": "account-2", "enabled": True},
            {"id": "account-disabled", "enabled": False},
        ]}
        with mock.patch.object(agent, "load_config", return_value=config), \
             mock.patch.object(agent, "refresh_usage", return_value=0) as refresh:
            self.assertEqual(agent.refresh_all_usage(), 0)
        self.assertEqual(refresh.call_args_list, [mock.call("account-1"), mock.call("account-2")])

    def test_refresh_all_reports_partial_failure_after_trying_both(self):
        config = {"accounts": [
            {"id": "account-1", "enabled": True},
            {"id": "account-2", "enabled": True},
        ]}
        with mock.patch.object(agent, "load_config", return_value=config), \
             mock.patch.object(agent, "refresh_usage", side_effect=[1, 0]) as refresh:
            self.assertEqual(agent.refresh_all_usage(), 1)
        self.assertEqual(refresh.call_count, 2)


class CodexPermissionTests(unittest.TestCase):
    def test_full_access_requires_explicit_config(self):
        self.assertEqual(agent.codex_permission_args({}), ["-a", "on-request"])
        self.assertEqual(
            agent.codex_permission_args({"defaultPolicyProfile": "full-access-explicit"}),
            ["--dangerously-bypass-approvals-and-sandbox"],
        )

    def test_full_access_is_boolean_only(self):
        self.assertEqual(agent.codex_permission_args({"codexFullAccess": True}), ["-a", "on-request"])



class LauncherParserTests(unittest.TestCase):
    def test_child_workers_use_the_package_bootstrap_wrapper(self):
        self.assertEqual(agent.SCRIPT_PATH.name, "quattro-agent")
        self.assertTrue(agent.SCRIPT_PATH.parent.name in {"src", "bin"})

    def test_bare_command_has_implicit_launch_arguments(self):
        args = agent.build_parser().parse_args([])
        self.assertIsNone(args.command)
        self.assertIsNone(args.agent)
        self.assertIsNone(args.directory)

    def test_bare_command_launches_the_configured_default_agent(self):
        with (
            mock.patch.object(agent.sys, "argv", ["quattro-agent"]),
            mock.patch.object(agent, "ensure_state_dirs"),
            mock.patch.object(agent, "load_config", return_value={"defaultAgent": "codex"}),
            mock.patch.object(agent, "launch_terminal", return_value="task-123") as launch,
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(agent.main(), 0)

        launch.assert_called_once_with(
            "codex", None, profile_name=None, confirm_full_access=False,
        )
        output.assert_called_once_with("task-123")

    def test_explicit_launch_arguments_still_parse(self):
        args = agent.build_parser().parse_args(["launch", "pi", "/tmp"])
        self.assertEqual(args.command, "launch")
        self.assertEqual(args.agent, "pi")
        self.assertEqual(args.directory, "/tmp")

    def test_terminal_launch_uses_foot_working_directory_option(self):
        directory = pathlib.Path("/tmp")
        runtime = mock.Mock()
        runtime.submit.return_value = ("task-123", None)
        with mock.patch.object(agent, "safe_directory", return_value=directory), \
             mock.patch.object(agent, "harness", return_value=runtime):
            task_id = agent.launch_terminal("codex", str(directory))

        self.assertEqual(task_id, "task-123")
        runtime.submit.assert_called_once_with(
            agent="codex", project=directory, prompt="", mode="interactive",
            profile_name=None, account_id=None, native_session_ref=None,
            confirm_full_access=False,
            terminal=True,
            write_scopes=(),
        )


class SessionDiscoveryTests(unittest.TestCase):
    def test_scan_logs_every_session_and_resolves_latest_across_accounts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"
            project.mkdir()
            accounts = []
            expected = []
            for index, account_id in enumerate(("account-1", "account-2"), start=1):
                home = root / account_id
                sessions = home / "sessions/2026/08/29"
                sessions.mkdir(parents=True)
                session_id = f"00000000-0000-0000-0000-00000000000{index}"
                path = sessions / f"rollout-{index}.jsonl"
                path.write_text(json.dumps({
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "session_id": "parent-session",
                        "cwd": str(project),
                    },
                }) + "\nprivate later record\n", encoding="utf-8")
                os.utime(path, (index, index))
                accounts.append({
                    "id": account_id, "alias": account_id.title(),
                    "codexHome": str(home), "enabled": True,
                })
                expected.append(session_id)
            config = {"accounts": accounts}

            with mock.patch.object(agent, "codex_thread_titles", return_value={}):
                rows = agent.scan_codex_sessions(config)
            self.assertEqual([row["sessionId"] for row in rows], list(reversed(expected)))
            with mock.patch.object(agent, "codex_thread_titles", return_value={}):
                target = agent.resolve_codex_resume_target(config, project)
            assert target is not None
            self.assertEqual(target["sessionId"], expected[-1])
            self.assertEqual(target["accountId"], "account-2")

    def test_scan_uses_codex_thread_name_and_persists_display_safe_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"
            project.mkdir()
            home = root / "account-1"
            sessions = home / "sessions/2026/08/31"
            sessions.mkdir(parents=True)
            session_id = "00000000-0000-0000-0000-000000000099"
            (sessions / "rollout.jsonl").write_text(json.dumps({
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": str(project),
                    "timestamp": "2026-08-31T06:27:02Z",
                },
            }) + "\nprivate later record\n", encoding="utf-8")
            registry = root / "registry.json"
            config = {"accounts": [{
                "id": "account-1", "alias": "Account 1",
                "codexHome": str(home), "enabled": True,
            }]}
            with (
                mock.patch.object(agent, "CODEX_SESSION_REGISTRY", registry),
                mock.patch.object(
                    agent, "codex_thread_titles",
                    return_value={session_id: "Secure lock and readable session names"},
                ),
            ):
                rows = agent.scan_codex_sessions(config)
            self.assertEqual(rows[0]["title"], "Secure lock and readable session names")
            stored = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(
                stored["sessions"][session_id]["displayTitle"],
                "Secure lock and readable session names",
            )
            self.assertEqual(
                stored["sessions"][session_id]["projectPath"], str(project)
            )
            self.assertEqual(
                stored["sessions"][session_id]["createdAt"],
                "2026-08-31T06:27:02Z",
            )

    def test_refresh_recent_writes_complete_session_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            state = root / "state"
            sessions = [{
                "sessionId": "session-1", "accountId": "account-2",
                "accountAlias": "Account 2", "path": "/tmp", "name": "tmp",
                "lastActivity": "2026-08-29T00:00:00+00:00",
                "exists": True, "resumable": True,
            }]
            with mock.patch.object(agent, "STATE_ROOT", state), \
                 mock.patch.object(agent, "load_config", return_value={"accounts": []}), \
                 mock.patch.object(agent, "scan_codex_sessions", return_value=sessions):
                self.assertEqual(agent.refresh_recent(), 0)
            ledger = json.loads((state / "recent/sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["sessions"], sessions)
            recent = json.loads((state / "recent/projects.json").read_text(encoding="utf-8"))
            self.assertEqual(recent["projects"][0]["accountId"], "account-2")



if __name__ == "__main__":
    unittest.main()
