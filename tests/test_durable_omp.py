from __future__ import annotations

import contextlib
from dataclasses import replace
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from quattro_agent.adapters import AgentMode, OMPAdapter, RunSpec, adapter_for
from quattro_agent.omp_context_worker import main, run_context_turn
from quattro_agent.scoped_omp_runtime import HostBinding, ScopedOMPError
from quattro_agent.config import validate_ai_config
from quattro_agent.errors import LeaseConflict
from quattro_agent.policy import policy_profile
from quattro_agent.recovery import checkpoint_payload
from quattro_agent.scheduler import LocalScheduler
from quattro_agent.store import TaskStore
from test_harness_core import valid_config


class DurableOMPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = TaskStore(self.root / "current" / "tasks.sqlite3")
        self.policy = policy_profile("audit-read-only", project_root=self.project)

    def task(self, agent, *, parent=None):
        return self.store.create_task(workflow="test", agent=agent, project_path=self.project,
                                      display_title="Test", policy=self.policy, parent_task_id=parent)

    def legacy_fixture(self):
        """Build genuine legacy constraints using credential-free synthetic rows."""
        target = self.root / "legacy" / "tasks.sqlite3"
        target.parent.mkdir()
        with contextlib.closing(sqlite3.connect(self.store.path)) as source:
            dump = "\n".join(source.iterdump()).replace(
                "CHECK(agent IN ('codex','pi','omp'))", "CHECK(agent IN ('codex','pi'))"
            ).replace("INSERT INTO \"schema_meta\" VALUES('schema_version','4');",
                      "INSERT INTO \"schema_meta\" VALUES('schema_version','3');")
        with contextlib.closing(sqlite3.connect(target)) as destination:
            destination.executescript(dump)
        return target

    @staticmethod
    def snapshot(path):
        with contextlib.closing(sqlite3.connect(path)) as connection:
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name <> 'schema_meta'"
            )]
            return {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                    for table in tables}

    def test_migration_retains_pi_codex_history_and_all_dependent_rows(self):
        parent = self.task("codex")
        child = self.task("pi", parent=parent)
        for task, agent in ((parent, "codex"), (child, "pi")):
            run = self.store.create_run(task, native_session_ref=f"native-{agent}")
            self.store.create_step(task, "check", position=0, run_id=run)
            self.store.add_artifact(task, kind="report", path=self.project / "report.txt",
                                    display_name="Report", run_id=run)
            self.store.create_logical_session(
                task_id=task, repository_path=self.project, working_directory=self.project,
                agent=agent, account_id="account-1", provider_id="synthetic",
                initial_checkpoint=checkpoint_payload(
                    objective="synthetic", requirements=(), repository_path=str(self.project),
                    working_directory=str(self.project), next_action="validate", repository_snapshot={},
                ),
            )
        legacy = self.legacy_fixture()
        before = self.snapshot(legacy)
        migrated = TaskStore(legacy)
        self.assertEqual(before, self.snapshot(legacy))
        with contextlib.closing(sqlite3.connect(legacy)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0], "4")
            self.assertEqual(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='tasks_parent'"
            ).fetchone()[0], "tasks_parent")
        task = migrated.create_task(workflow="test", agent="omp", project_path=self.project,
                                    display_title="OMP", policy=self.policy)
        self.assertEqual(migrated.get_task(task)["agent"], "omp")
        migrated.create_run(task)
        self.assertEqual(self.snapshot(legacy), self.snapshot(TaskStore(legacy).path))

    def test_foreign_key_failure_rolls_back_constraint_and_schema_changes(self):
        task = self.task("pi")
        legacy = self.legacy_fixture()
        with contextlib.closing(sqlite3.connect(legacy)) as connection:
            connection.execute("UPDATE tasks SET parent_task_id='missing' WHERE task_id=?", (task,))
            connection.commit()
        before = self.snapshot(legacy)
        with self.assertRaisesRegex(RuntimeError, "foreign-key"):
            TaskStore(legacy)
        self.assertEqual(before, self.snapshot(legacy))
        with contextlib.closing(sqlite3.connect(legacy)) as connection:
            self.assertEqual(connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0], "3")
            self.assertIn("'codex','pi'", connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='tasks'"
            ).fetchone()[0])
            self.assertEqual(connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '%_omp_migration'"
            ).fetchall(), [])

    def test_omp_capacity_and_native_session_writer_lock(self):
        scheduler = LocalScheduler(self.store)
        first = self.task("omp")
        second = self.task("omp")
        scheduler.try_acquire(task_id=first, run_id=self.store.create_run(first), agent="omp",
                              account_id=None, project_path=self.project, native_session_ref="exact")
        with self.assertRaises(LeaseConflict):
            scheduler.try_acquire(task_id=second, run_id=self.store.create_run(second), agent="omp",
                                  account_id=None, project_path=self.project, native_session_ref="exact")
        self.assertNotEqual(scheduler.session_resource("exact"),
                            scheduler.session_resource("exact", agent="omp"))

    def spec(self):
        return RunSpec(task_id="task_test", run_id="run_test", project_path=self.project,
                       mode=AgentMode.PROMPT, policy=self.policy, private_input="Review synthetic context",
                       omp_package_root=self.root / "package", omp_agent_dir=self.root / "native-omp",
                       omp_session_dir=self.root / "runtime", omp_runtime_manifest=self.root / "runtime.json",
                       omp_runtime_manifest_sha256="a" * 64)

    def test_adapter_uses_closed_driver_private_stdin_and_fixed_profile(self):
        plan = adapter_for("omp").build_launch("/usr/bin/bun", self.spec())
        self.assertIsInstance(adapter_for("omp"), OMPAdapter)
        self.assertTrue(any(arg.endswith("/omp_context_worker.py") for arg in plan.argv))
        self.assertIn("-I", plan.argv)
        self.assertNotIn(self.spec().private_input, plan.argv)
        self.assertEqual(plan.stdin_text, self.spec().private_input)
        self.assertFalse(OMPAdapter().capabilities.supports_resume)
        self.assertFalse(OMPAdapter().capabilities.supports_native_sandbox)
        self.assertNotIn("--approval-mode", plan.argv)

    def test_adapter_rejects_writes_resume_foreign_route_and_missing_sdk(self):
        spec = self.spec()
        for changed in (
            replace(spec, policy=policy_profile("workspace-write", project_root=self.project)),
            replace(spec, mode=AgentMode.RESUME),
            replace(spec, native_session_ref="previous"),
            replace(spec, model_override="other/model"),
            replace(spec, omp_package_root=None),
            replace(spec, omp_runtime_manifest_sha256=None),
        ):
            with self.subTest(spec=changed):
                with self.assertRaises(ValueError):
                    OMPAdapter().build_launch("/usr/bin/bun", changed)

    def test_context_worker_registers_no_tools_and_closes_after_turn(self):
        runtime = mock.Mock()
        runtime.start.return_value = HostBinding("task_test", "run_test", "native-test")
        runtime.prompt.return_value = {"text": "synthetic result"}
        factory = mock.Mock(return_value=runtime)
        with mock.patch.dict("os.environ", {"UNSAFE_TEST_SECRET": "excluded"}, clear=True):
            result = run_context_turn(command=("/usr/bin/bun",), directory=self.project,
                                      agent_dir=self.root / "native", task="task_test", run="run_test",
                                      prompt="synthetic context", timeout=30, runtime_factory=factory)
        self.assertEqual(result["text"], "synthetic result")
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["tools"], [])
        self.assertFalse(kwargs["own_process_group"])
        self.assertNotIn("UNSAFE_TEST_SECRET", kwargs["environment"])
        self.assertFalse(Path(kwargs["environment"]["HOME"]).exists())
        self.assertEqual(kwargs["environment"]["PI_CODING_AGENT_DIR"], str(self.root / "native"))
        with self.assertRaises(ScopedOMPError):
            kwargs["execute"](None, "bash", {}, "call")
        runtime.close.assert_called_once()

    def test_context_worker_failure_closes_runtime(self):
        runtime = mock.Mock()
        runtime.start.side_effect = ScopedOMPError("unavailable")
        with self.assertRaises(ScopedOMPError):
            run_context_turn(command=("/usr/bin/bun",), directory=self.project,
                             agent_dir=self.root / "native", task="task_test", run="run_test",
                             prompt="synthetic", timeout=30, runtime_factory=lambda *a, **k: runtime)
        runtime.close.assert_called_once()

    def test_worker_rejects_oversized_stdin_before_runtime_start(self):
        args = ["--bun", "/usr/bin/bun", "--package-root", str(self.root / "package"),
                "--directory", str(self.project), "--agent-dir", str(self.root / "native"),
                "--session-dir", str(self.root / "runtime"), "--task", "task_test", "--run", "run_test",
                "--timeout", "30", "--runtime-manifest", str(self.root / "runtime.json"),
                "--runtime-manifest-sha256", "a" * 64]
        stdin = mock.Mock(buffer=io.BytesIO(b"x" * 131073))
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("quattro_agent.omp_context_worker.run_context_turn") as run, \
                mock.patch("quattro_agent.omp_deployment.verify_omp_runtime"):
            self.assertEqual(main(args), 125)
            run.assert_not_called()

    def test_config_accepts_omp_without_rewriting_legacy_pi(self):
        value = valid_config(self.root)
        for agent in ("omp", "pi", "codex"):
            value["defaultAgent"] = agent
            self.assertEqual(validate_ai_config(value, home=self.root)["defaultAgent"], agent)


if __name__ == "__main__":
    unittest.main()
