from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quattro_agent.mandatory_context import (  # noqa: E402
    QUATTRO_DESKTOP_CLEAN_POLICY_ID,
    REPOSITORY_WORKFLOW_POLICY_ID,
    WORKSPACE_POLICY_ID,
    WorktreeClassification,
    build_mandatory_context,
    destination_from_request,
    inspect_worktree,
    resolve_project_destination,
)
from quattro_agent.retrieval import ContextAssembler, SearchResult  # noqa: E402


class MandatoryContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path("/srv/example-projects")
        self.config = {"workspace": {"projectRoot": str(self.root)}}

    def test_clone_defaults_to_canonical_project_root(self) -> None:
        result = destination_from_request(
            "Clone https://github.com/example/widget.git",
            project_root=self.root,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.destination, "/srv/example-projects/widget")
        self.assertEqual(result.source, "mandatory policy/config")

    def test_explicit_clone_destination_wins(self) -> None:
        result = destination_from_request(
            "Clone example/widget to /tmp/test",
            project_root=self.root,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.destination, "/tmp/test")
        self.assertEqual(result.source, "explicit user instruction")

    def test_mandatory_policy_does_not_depend_on_rag_hit(self) -> None:
        retrieved = ContextAssembler().assemble(
            request="Clone example/widget", structured_state={}, results=[],
            budget_tokens=300, instruction_tokens=250,
        )
        mandatory = build_mandatory_context(self.config, request="Clone example/widget")
        self.assertEqual(retrieved["retrievedKnowledge"], [])
        self.assertIn("/srv/example-projects", mandatory.text)
        self.assertIn(WORKSPACE_POLICY_ID, mandatory.activated_policies)

    def test_conflicting_historical_rag_cannot_override_mandatory_policy(self) -> None:
        conflict = SearchResult(
            id="old", source_type="decision", path="old-session.md", symbol=None,
            content="Clone projects under /srv/example-work", score=1.0,
            lexical_score=1.0, semantic_score=0.0, rerank_score=1.0,
            metadata={},
        )
        retrieved = ContextAssembler().assemble(
            request="Clone example/widget", structured_state={}, results=[conflict],
        )
        mandatory = build_mandatory_context(self.config, request="Clone example/widget")
        self.assertTrue(retrieved["retrievedKnowledge"][0]["untrusted"])
        self.assertEqual(mandatory.destination.destination, "/srv/example-projects/widget")
        self.assertIn("trusted; not RAG", mandatory.text)

    def test_delegated_clone_gets_relevant_constraint(self) -> None:
        mandatory = build_mandatory_context(
            self.config, request="Clone example/widget", delegated=True,
        )
        self.assertTrue(mandatory.propagated_to_subagent)
        self.assertIn("Default all repository clones", mandatory.text)
        self.assertEqual(
            mandatory.diagnostics()["activatedPolicies"],
            [
                WORKSPACE_POLICY_ID,
                REPOSITORY_WORKFLOW_POLICY_ID,
                QUATTRO_DESKTOP_CLEAN_POLICY_ID,
            ],
        )

    def test_repository_mutation_policies_are_always_loaded(self) -> None:
        mandatory = build_mandatory_context(
            self.config,
            request="Fix a typo",
            cwd=pathlib.Path("/srv/quattro-desktop"),
        )
        self.assertIn(REPOSITORY_WORKFLOW_POLICY_ID, mandatory.activated_policies)
        self.assertIn("dedicated non-main branch", mandatory.text)
        self.assertIn("create a PR targeting main", mandatory.text)
        self.assertIn("explicit user override for a specific task", mandatory.text)
        self.assertIn("established repository workflow", mandatory.text)
        self.assertIn("required checks and reviews pass", mandatory.text)
        self.assertIn(QUATTRO_DESKTOP_CLEAN_POLICY_ID, mandatory.activated_policies)
        self.assertIn("/srv/quattro-desktop", mandatory.text)
        self.assertIn("dirty worktree is not automatically a blocker", mandatory.text)
        self.assertIn("RECOVERED_INTERRUPTED_WORK", mandatory.text)
        self.assertIn("Unresolved merge/rebase/cherry-pick", mandatory.text)

    def test_retrieval_budget_cannot_remove_mandatory_context(self) -> None:
        mandatory = build_mandatory_context(self.config, request="Clone example/widget")
        before = mandatory.text
        ContextAssembler().assemble(
            request="Clone example/widget", structured_state={}, results=[],
            budget_tokens=256, instruction_tokens=10_000,
        )
        self.assertEqual(mandatory.text, before)
        self.assertIn("/srv/example-projects/widget", mandatory.text)

    def test_explicit_existing_project_outside_default_root_is_allowed(self) -> None:
        result = resolve_project_destination(
            project_root=self.root,
            repository="example/widget",
            explicit_destination="/srv/example-work/existing-widget",
            operation="create",
        )
        self.assertEqual(result.destination, "/srv/example-work/existing-widget")
        self.assertTrue(result.explicit)


class WorktreeRecoveryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git = shutil.which("git") or "git"
        self.git_run("init", "-q", "-b", "main")
        self.git_run("config", "user.name", "Quattro Test")
        self.git_run("config", "user.email", "quattro@example.invalid")
        (self.repo / "src").mkdir()
        (self.repo / "src/app.py").write_text("base\n", encoding="utf-8")
        (self.repo / "user.txt").write_text("base\n", encoding="utf-8")
        self.git_run("add", ".")
        self.git_run("commit", "-qm", "base")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git_run(self, *args: str) -> None:
        subprocess.run([self.git, "-C", str(self.repo), *args], check=True, stdout=subprocess.PIPE)

    def test_clean_repository_continues_normally(self) -> None:
        result = inspect_worktree(self.repo)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.CLEAN)

    def test_current_task_changes_are_not_automatically_blocked(self) -> None:
        (self.repo / "src/app.py").write_text("task change\n", encoding="utf-8")
        result = inspect_worktree(self.repo, current_task_paths=("src",))
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.CURRENT_TASK)

    def test_interrupted_quattro_work_is_recoverable(self) -> None:
        (self.repo / "src/app.py").write_text("recovered task change\n", encoding="utf-8")
        result = inspect_worktree(self.repo, recovered_interrupted_paths=("src/app.py",))
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.RECOVERED_INTERRUPTED_WORK)

    def test_unrelated_user_work_is_preserved_and_excluded(self) -> None:
        (self.repo / "user.txt").write_text("user change\n", encoding="utf-8")
        result = inspect_worktree(self.repo, unrelated_user_paths=("user.txt",))
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.UNRELATED_USER_WORK)
        self.assertEqual((self.repo / "user.txt").read_text(encoding="utf-8"), "user change\n")

    def test_unknown_changes_never_imply_destructive_cleanup(self) -> None:
        (self.repo / "unattributed.txt").write_text("keep me\n", encoding="utf-8")
        result = inspect_worktree(self.repo)
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.UNKNOWN)
        self.assertTrue((self.repo / "unattributed.txt").exists())

    def test_dirty_main_requires_feature_branch_or_isolation(self) -> None:
        (self.repo / "src/app.py").write_text("task change\n", encoding="utf-8")
        result = inspect_worktree(self.repo, current_task_paths=("src",))
        assert result is not None
        self.assertEqual(result.branch, "main")
        mandatory = build_mandatory_context(
            {"workspace": {"projectRoot": self.temp.name}}, cwd=self.repo,
            current_task_paths=("src",),
        )
        self.assertIn("Dirty main requires a feature branch or isolated worktree", mandatory.text)

    def test_merge_rebase_or_cherry_pick_state_remains_a_hard_block(self) -> None:
        (self.repo / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        result = inspect_worktree(self.repo)
        assert result is not None
        self.assertEqual(result.classification, WorktreeClassification.UNSAFE_GIT_STATE)
        self.assertIn("unresolved", result.hard_block_reason or "")


if __name__ == "__main__":
    unittest.main()
