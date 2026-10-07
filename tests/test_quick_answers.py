"""A bare "yes", "no" or "undo" is answered without the model.

"Yes" used to go back through the model, which had to re-send the armed call
exactly — and a model that changed one argument was asked all over again. Cheap,
reversible changes no longer ask at all: "undo" takes them back.

Run directly: python tests/test_quick_answers.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _turn(text: str):
    from helpers.turn import run_turn

    with mock.patch("helpers.bootstrap.get_ai_client", return_value=None), \
            mock.patch("modules.ai.build_agent_system_prompt", return_value=""), \
            mock.patch("helpers.conversation.Conversation.get_messages", return_value=[]):
        return run_turn(text)


class TestYesAndNo(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import confirm
        from helpers.registry import ServiceRegistry

        confirm.reset()
        self.sent = []

        def send_note(to: str, body: str = "") -> str:
            """Sends a note."""
            self.sent.append(to)
            return f"Sent to {to}."

        self.model_turns = []

        def fake_agent(**kwargs):
            from helpers.agent import AgentResult

            self.model_turns.append(kwargs["user_input"])
            if kwargs["user_input"] == "send anna a note":
                needs = confirm.check("send_note", {"to": "anna"})
                return AgentResult(text="Should I send it?", calls=[{"name": "send_note", "args": {"to": "anna"}, "result": needs}])
            return AgentResult(text="model answered", calls=[])

        for patcher in (
            mock.patch.dict(ServiceRegistry._jobs, {"send_note": send_note}),
            mock.patch.dict(ServiceRegistry._job_confirms, {"send_note": True}),
            mock.patch("helpers.agent.run_agent", fake_agent),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_yes_runs_what_was_asked_about_without_the_model(self) -> None:
        _turn("send anna a note")
        result = _turn("Yes.")
        self.assertEqual(self.sent, ["anna"])
        self.assertEqual(result.text, "Sent to anna.")
        self.assertEqual(self.model_turns, ["send anna a note"])

    def test_no_drops_it(self) -> None:
        _turn("send anna a note")
        self.assertEqual(_turn("no").text, "Okay, I won't.")
        self.assertEqual(self.sent, [])
        # And a later "yes" has nothing left to run.
        self.assertEqual(_turn("yes").text, "model answered")

    def test_yes_with_nothing_asked_goes_to_the_model(self) -> None:
        self.assertEqual(_turn("yes").text, "model answered")

    def test_only_the_turn_right_before_counts(self) -> None:
        _turn("send anna a note")
        _turn("what's the weather")
        self.assertEqual(_turn("yes").text, "model answered")
        self.assertEqual(self.sent, [])


class TestUndo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import helpers.memory_db as db

        cls.db = db
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(cls._tmpdir.name, "test.db")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.db._DB_FILE = cls._real_db_file
        cls._tmpdir.cleanup()

    def setUp(self) -> None:
        from helpers import undo

        undo.reset()
        self.db.wipe_all()

    def test_undo_takes_a_list_item_back(self) -> None:
        from helpers import undo
        from helpers.turn_context import user_request
        from modules import notes

        with user_request("add milk"):
            notes.note("add", "milk, eggs", "shopping")
        self.assertEqual(len(self.db.list_notes("shopping")), 2)
        self.assertIn("Undid", undo.undo())
        self.assertEqual(self.db.list_notes("shopping"), [])
        self.assertIn("nothing", undo.undo())

    def test_a_change_nobody_asked_for_is_not_undoable(self) -> None:
        from helpers import undo
        from modules import notes

        notes.note("add", "milk", "shopping")
        self.assertIn("nothing", undo.undo())

    def test_adding_to_a_list_no_longer_asks_after_reading_mail(self) -> None:
        """Reversible now, so the untrusted-read gate stays on what is not."""
        from helpers import confirm
        from modules import notes

        declared = notes.note._job_confirms
        self.assertFalse(confirm._applies(declared, {"action": "add", "text": "milk"}))
        self.assertTrue(confirm._applies(declared, {"action": "clear"}))

    def test_a_bare_undo_needs_no_model(self) -> None:
        from helpers.turn_context import user_request
        from modules import notes

        with user_request("add milk"):
            notes.note("add", "milk", "shopping")
        with mock.patch("helpers.agent.run_agent") as model:
            result = _turn("undo that")
        model.assert_not_called()
        self.assertIn("Undid", result.text)
        self.assertEqual(self.db.list_notes("shopping"), [])


class TestHomeUndo(unittest.TestCase):
    def test_switching_back_restores_each_previous_state(self) -> None:
        os.environ.setdefault("HOME_ASSISTANT_TOKEN", "test-token")
        from helpers import undo
        from helpers.turn_context import user_request
        from modules import home_assistant as ha

        E = ha._Entity
        index = [
            E("light.kitchen_ceiling", "Ceiling", "Kitchen", "on", ""),
            E("light.kitchen_counter", "Counter", "Kitchen", "off", ""),
        ]
        calls = []
        undo.reset()
        with mock.patch.object(ha, "_fetch_index", return_value=index), \
                mock.patch.object(ha, "_call_service", lambda d, s, ids, extra: calls.append((s, sorted(ids)))):
            with user_request("kitchen lights off"):
                ha.control_home_device(area="kitchen", domain="light", action="off")
            calls.clear()
            undo.undo()
        self.assertEqual(calls, [("turn_on", ["light.kitchen_ceiling"]), ("turn_off", ["light.kitchen_counter"])])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
