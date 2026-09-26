"""Locked interactive shell regression coverage without provider or terminal side effects."""

import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from quattro_agent.interactive import final_answer, run_interactive
from quattro_agent.models import TaskState


class InteractiveTests(unittest.TestCase):
    def test_final_answer_ignores_non_final_events(self):
        raw = '\n'.join((
            json.dumps({"type": "item.completed", "item": {"type": "tool_call", "text": "ignore"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}}),
        ))
        self.assertEqual(final_answer(raw), "answer")

    def test_three_turns_share_logical_session_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            artifact = root / "output.jsonl"
            artifact.write_text(json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "remembered marker"}}))
            runtime = mock.Mock()
            runtime.create_task.side_effect = ["anchor", "turn-1", "turn-2", "turn-3"]
            runtime.run_task.return_value = 0
            runtime.store.logical_session_for_task.return_value = {"quattro_session_id": "qsession_test"}
            runtime.store.get_task.side_effect = lambda task_id, **_kwargs: (
                {"private_payload": {"coordinationSessionId": "coord"}}
                if task_id == "anchor" else {"state": TaskState.SUCCEEDED.value}
            )
            runtime.store.artifacts_for_task.return_value = [{"path": str(artifact)}]
            output = io.StringIO()
            result = run_interactive(
                runtime, agent="codex", workspace=root,
                input_stream=io.StringIO("first\nrefer to first\nrefer to prior result\nquit\n"),
                output=output,
            )
            self.assertEqual(result, 0)
            calls = runtime.create_task.call_args_list
            self.assertEqual(len(calls), 4)
            for call in calls[1:]:
                self.assertEqual(call.kwargs["logical_session_id"], "qsession_test")
                self.assertEqual(call.kwargs["mode"], "prompt")
            self.assertIn("User: first", calls[2].kwargs["prompt"])
            self.assertIn("refer to first", calls[3].kwargs["prompt"])
            self.assertEqual(runtime.checkpoint_task.call_count, 3)
            runtime.store.transition_task.assert_called_once()
            runtime.coordinator.finish.assert_called_once()
            self.assertIn("Session saved.", output.getvalue())

    def test_interrupt_cancels_current_task_and_preserves_session(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = mock.Mock()
            runtime.store.get_logical_session.return_value = {
                "working_directory": directory, "current_task_id": "anchor",
                "initial_task_id": "anchor",
            }
            runtime.create_task.return_value = "interrupted-turn"
            runtime.run_task.side_effect = KeyboardInterrupt()
            output = io.StringIO()
            result = run_interactive(
                runtime, agent="codex", workspace=pathlib.Path(directory),
                session_id="qsession_test", input_stream=io.StringIO("start\n"), output=output,
            )
            self.assertEqual(result, 0)
            runtime.request_cancel.assert_called_once_with("interrupted-turn", reason="interactive_interrupt")
            self.assertIn("Session saved.", output.getvalue())

    def test_resume_restores_checkpoint_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            runtime = mock.Mock()
            runtime.store.get_logical_session.return_value = {
                "working_directory": str(root), "current_task_id": "previous",
                "initial_task_id": "anchor",
            }
            runtime.store.current_checkpoint.return_value = {
                "content": {"completed": ["User: original | Response: marker"]}}
            runtime.create_task.return_value = "turn-2"
            runtime.run_task.return_value = 1
            runtime.store.get_task.return_value = {"state": "failed", "terminal_summary": "failed"}
            runtime.store.artifacts_for_task.return_value = []
            run_interactive(runtime, agent="codex", workspace=root, session_id="qsession_test",
                            input_stream=io.StringIO("what was it?\nexit\n"), output=io.StringIO())
            self.assertIn("marker", runtime.create_task.call_args.kwargs["prompt"])
            self.assertEqual(runtime.create_task.call_args.kwargs["logical_session_id"], "qsession_test")


if __name__ == "__main__":
    unittest.main()
