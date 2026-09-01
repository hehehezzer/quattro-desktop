from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quattro_agent.mandatory_context import (  # noqa: E402
    WORKSPACE_POLICY_ID,
    build_mandatory_context,
    destination_from_request,
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
            mandatory.diagnostics()["activatedPolicies"], [WORKSPACE_POLICY_ID]
        )

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


if __name__ == "__main__":
    unittest.main()
