import unittest

from quattro_agent.delegation import classify_task_request


class DelegationClassifierTests(unittest.TestCase):
    def test_explanation_is_direct(self):
        result = classify_task_request("Explain Docker volumes")
        self.assertEqual(result.to_dict(), {
            "decision": "DIRECT",
            "reason": "request_can_be_answered_without_execution",
            "confidence": 0.93,
            "requiredAgent": None,
        })

    def test_dotted_api_questions_remain_direct(self):
        for prompt in (
            "Explain subprocess.run", "What does os.open do?",
            "How does db.commit work?", "Explain pathlib.Path.open in Python",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_task_request(prompt).decision, "DIRECT")

    def test_sentence_and_semicolon_execution_clauses_delegate(self):
        for prompt in (
            "Explain the issue. Run tests", "Explain the issue;run tests",
            "Explain the issue; commit changes", "Explain the issue. Open a PR",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_task_request(prompt).decision, "DELEGATE")

    def test_repository_fix_delegates_to_codex(self):
        result = classify_task_request("Fix this React bug in my repo")
        self.assertEqual(result.decision, "DELEGATE")
        self.assertEqual(result.required_agent, "codex")

    def test_analysis_stays_direct(self):
        self.assertEqual(classify_task_request("Analyze logs and suggest fix").decision, "DIRECT")

    def test_analysis_and_apply_delegates(self):
        result = classify_task_request("Analyze logs and apply fixes")
        self.assertEqual(result.decision, "DELEGATE")

    def test_invalid_agent_falls_back_safely(self):
        self.assertEqual(classify_task_request("Run the tests", preferred_agent="other").required_agent, "codex")


if __name__ == "__main__":
    unittest.main()
