from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from concurrent.futures import ThreadPoolExecutor

from quattro_agent.collaboration import RepositoryCoordinator, canonical_project
from quattro_agent.errors import LeaseConflict


class CollaborationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "product"
        self.repo.mkdir()
        self.git = shutil.which("git") or "git"
        self.git_run(self.repo, "init", "-q", "-b", "main")
        self.git_run(self.repo, "config", "user.name", "Quattro Test")
        self.git_run(self.repo, "config", "user.email", "quattro@example.invalid")
        (self.repo / "shared.txt").write_text("base\n", encoding="utf-8")
        self.git_run(self.repo, "add", "shared.txt")
        self.git_run(self.repo, "commit", "-qm", "base")
        self.coordinator = RepositoryCoordinator(
            self.root / "state", self.root / "explicit-worktrees",
            global_limit=5, per_repository_limit=3, git=self.git,
            reservation_ttl_seconds=0.2,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_metadata_status_never_executes_repository_fsmonitor(self):
        from quattro_agent.recovery import repository_state as recovery_state
        from quattro_agent.retrieval import repository_state as retrieval_state
        from quattro_harness import HarnessRuntime
        from types import SimpleNamespace
        marker = self.root / "unsafe-status-ran"
        hook = self.root / "fsmonitor"
        hook.write_text("#!/bin/sh\nprintf unsafe > " + str(marker) + "\nprintf '\\0'\n")
        hook.chmod(0o700)
        self.git_run(self.repo, "config", "core.fsmonitor", str(hook))
        identity = canonical_project(self.repo,git=self.git)
        session = self.coordinator.reserve(self.repo,task_summary="synthetic read",isolate=False)
        self.coordinator.finish(str(session['sessionId']),validation="Not Run",abandoned=False)
        self.assertTrue(identity.canonical_repository.is_dir())
        self.assertIsNotNone(recovery_state(self.repo)['head'])
        self.assertIsNotNone(retrieval_state(self.repo)['commitSha'])
        runtime = SimpleNamespace(command_resolver=lambda name:self.git)
        self.assertIsNotNone(HarnessRuntime._git_status_snapshot(runtime,self.repo))
        self.assertFalse(marker.exists())

    def test_native_metadata_never_executes_fsmonitor_or_clean_filters(self):
        import os
        from quattro_agent.repository_metadata import native_repository_metadata, repository_status_allowed
        from quattro_agent.recovery import repository_state as recovery_state
        from quattro_agent.retrieval import repository_state as retrieval_state
        from quattro_agent.mandatory_context import inspect_worktree, WorktreeClassification
        from quattro_harness import HarnessRuntime
        from types import SimpleNamespace
        marker = self.root / "unsafe-clean-ran"
        monitor_marker = self.root / "unsafe-monitor-ran"
        (self.repo/'.gitattributes').write_text('shared.txt filter=synthetic\n')
        self.git_run(self.repo,'add','.gitattributes')
        self.git_run(self.repo,'commit','-qm','synthetic attributes')
        clean = self.root/'synthetic-clean'
        clean.write_text('#!/bin/sh\nprintf unsafe > '+str(marker)+'\ncat\n')
        clean.chmod(0o700)
        monitor = self.root/'synthetic-monitor'
        monitor.write_text('#!/bin/sh\nprintf unsafe > '+str(monitor_marker)+'\n')
        monitor.chmod(0o700)
        self.git_run(self.repo,'config','filter.synthetic.clean',str(clean))
        self.git_run(self.repo,'config','core.fsmonitor',str(monitor))
        tracked = self.repo/'shared.txt'
        stat = tracked.stat()
        tracked.write_text('next\n')
        os.utime(tracked,(stat.st_atime+2,stat.st_mtime+2))
        @native_repository_metadata
        def inspect_native():
            self.assertFalse(repository_status_allowed())
            identity = canonical_project(self.repo,git=self.git)
            self.assertIsNone(identity.original_dirty)
            session = self.coordinator.reserve(self.repo,task_summary='synthetic native',isolate=False)
            self.assertEqual(session['repositoryProbePolicy'],'identity-only')
            finished = self.coordinator.finish(session['sessionId'],validation='Native checks',abandoned=False)
            self.assertIsNone(finished['dirty'])
            self.assertIsNone(recovery_state(self.repo)['dirty'])
            self.assertIsNone(retrieval_state(self.repo)['dirty'])
            self.assertIs(inspect_worktree(self.repo).classification,WorktreeClassification.UNKNOWN)
            runtime = SimpleNamespace(command_resolver=lambda name:self.git)
            self.assertIsNone(HarnessRuntime._git_status_snapshot(runtime,self.repo))
            return session['sessionId']
        session_id = inspect_native()
        self.assertTrue(repository_status_allowed())
        record = self.coordinator.finish(session_id,validation='Native checks',abandoned=False)
        self.assertIsNone(self.coordinator._worktree_state(record)['dirty'])
        # Later ordinary UI/reconciliation must honor the stored native policy.
        self.coordinator.status()
        self.coordinator.reconcile()
        self.assertFalse(marker.exists())
        self.assertFalse(monitor_marker.exists())
        # Prove that the configured clean filter is executable in the fixture.
        self.git_run(self.repo,'-c','core.fsmonitor=false','status','--porcelain')
        self.assertTrue(marker.exists())

    def git_run(self, cwd: pathlib.Path, *args: str, check: bool = True):
        return subprocess.run(
            [self.git, "-C", str(cwd), *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
        )

    def test_canonical_identity_unifies_subdirectory_and_symlink(self) -> None:
        nested = self.repo / "src/module"
        nested.mkdir(parents=True)
        link = self.root / "product-link"
        link.symlink_to(self.repo, target_is_directory=True)
        identities = [canonical_project(candidate, git=self.git) for candidate in (self.repo, nested, link)]
        self.assertEqual(len({item.repository_id for item in identities}), 1)
        self.assertEqual({item.canonical_repository for item in identities}, {self.repo.resolve()})

    def test_sessions_stay_in_the_requested_directory_without_worktrees(self) -> None:
        sessions = [
            self.coordinator.reserve(self.repo, task_summary=summary, task_scope=(scope,))
            for summary, scope in (("auth work", "src/auth"), ("orders work", "src/orders"))
        ]
        self.assertEqual({pathlib.Path(row["workingDirectory"]) for row in sessions}, {self.repo})
        self.assertEqual({pathlib.Path(row["worktreePath"]) for row in sessions}, {self.repo})
        self.assertTrue(all(row["managedWorktree"] is False for row in sessions))
        self.assertTrue(all(row["isolationReason"] == "shared_working_tree" for row in sessions))
        self.assertEqual(self.git_run(self.repo, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)
        self.assertEqual(self.git_run(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_parallel_independent_scope_edits_share_the_repository(self) -> None:
        sessions = [
            self.coordinator.reserve(self.repo, task_summary=summary, task_scope=(scope,))
            for summary, scope in (("auth work", "src/auth"), ("orders work", "src/orders"))
        ]
        scripts = [
            "from pathlib import Path; Path('src/auth/token.py').parent.mkdir(parents=True, exist_ok=True); Path('src/auth/token.py').write_text('auth\\n')",
            "from pathlib import Path; Path('src/orders/order.py').parent.mkdir(parents=True, exist_ok=True); Path('src/orders/order.py').write_text('orders\\n')",
        ]
        processes = [subprocess.Popen([sys.executable, "-c", script], cwd=row["workingDirectory"]) for row, script in zip(sessions, scripts)]
        self.assertTrue(all(process.wait(timeout=5) == 0 for process in processes))
        self.assertEqual((self.repo / "src/auth/token.py").read_text(), "auth\n")
        self.assertEqual((self.repo / "src/orders/order.py").read_text(), "orders\n")

    def test_overlapping_writable_scopes_are_rejected(self) -> None:
        self.coordinator.reserve(self.repo, task_summary="authentication", task_scope=("src/auth",))
        with self.assertRaisesRegex(LeaseConflict, "overlaps"):
            self.coordinator.reserve(self.repo, task_summary="login view", task_scope=("src/auth/Login.py",))
        with self.assertRaisesRegex(LeaseConflict, "overlaps"):
            self.coordinator.reserve(self.repo, task_summary="global rewrite", task_scope=("**",))

    def test_unknown_changes_are_preserved_and_context_requires_claims(self) -> None:
        original = self.repo / "shared.txt"
        original.write_text("someone else changed this\n", encoding="utf-8")
        session = self.coordinator.reserve(self.repo, task_summary="read-only discovery")
        self.assertTrue(session["originalDirty"])
        self.assertEqual(original.read_text(), "someone else changed this\n")
        context = self.coordinator.context(session["sessionId"])
        self.assertIn("shared_working_tree", context)
        self.assertIn("Before writing, determine and claim", context)
        self.assertIn("classify every path", context)
        self.assertIn("Never reset, clean, discard", context)

    def test_shared_sessions_cannot_run_branch_integration(self) -> None:
        source = self.coordinator.reserve(self.repo, task_summary="source", task_scope=("src/source",))
        target = self.coordinator.reserve(self.repo, task_summary="target", task_scope=("src/target",))
        self.coordinator.finish(source["sessionId"], validation="Passed")
        with self.assertRaisesRegex(RuntimeError, "already integrated"):
            self.coordinator.integrate(target["sessionId"], source["sessionId"], strategy="merge")

    def test_explicit_isolation_remains_opt_in_only(self) -> None:
        session = self.coordinator.reserve(self.repo, task_summary="isolated experiment", isolate=True)
        self.assertTrue(session["managedWorktree"])
        self.assertEqual(session["isolationReason"], "explicit_managed_worktree")
        self.assertNotEqual(pathlib.Path(session["workingDirectory"]), self.repo)

    def test_limits_are_preserved_under_concurrent_reservations(self) -> None:
        coordinator = RepositoryCoordinator(
            self.root / "concurrent-state",
            self.root / "concurrent-worktrees",
            global_limit=5,
            per_repository_limit=3,
            git=self.git,
            reservation_ttl_seconds=30.0,
        )
        barrier = threading.Barrier(8)
        def reserve(index: int) -> str:
            barrier.wait()
            try:
                return coordinator.reserve(
                    self.repo,
                    task_summary=f"task {index}",
                    task_scope=(f"src/{index}",),
                )["sessionId"]
            except LeaseConflict:
                return "rejected"
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(reserve, range(8)))
        self.assertEqual(len([result for result in results if result != "rejected"]), 3)
        self.assertEqual(coordinator.status()["global"], {"active": 3, "limit": 5})



class RecoveryUnknownStateTests(unittest.TestCase):
    def test_unknown_dirty_state_does_not_report_paths_removed(self):
        from quattro_agent.recovery import divergence
        recorded = {"exists": True, "branch": "main", "head": "same", "dirty": True, "changedPaths": ["a"]}
        current = dict(recorded, dirty=None, changedPaths=[])
        self.assertEqual(divergence(recorded, current), [])
        self.assertTrue(divergence(recorded, dict(current, dirty=False)))


if __name__ == "__main__":
    unittest.main()
