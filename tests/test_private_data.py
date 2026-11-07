"""With "Keep my email and calendar from the AI" on, mail and events reach the
user and never the model. A leak here fails silently — the answer still looks
right — so each path that hands text to the model is pinned.

Run directly: python tests/test_private_data.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_MAIL = "From: Anna\n  Subject: The secret plan"
_SECRET = "secret plan"


def _switch(on: bool):
    return mock.patch("helpers.private_data.on", return_value=on)


def find_emails() -> str:
    """Finds email."""
    from helpers.untrusted import wrap

    return "Emails:\n" + wrap(_MAIL, "email")


def weather() -> str:
    """Weather."""
    return "Sunny."


class TestAgentWithholds(unittest.TestCase):
    def _run(self, jobs, calls, replies=("Done.",)):
        from helpers import agent
        from helpers.registry import ServiceRegistry

        sent = []
        steps = iter([("", calls)] + [(reply, []) for reply in replies])

        def step(**kwargs):
            sent.append(str(kwargs["messages"]))
            text, tool_calls = next(steps)
            if text:
                kwargs["on_text"](text)
            return text, tool_calls

        streamed = []
        with mock.patch("helpers.model.stream_agent_step", side_effect=step), \
                mock.patch.dict(ServiceRegistry._job_modules, {"find_emails": "gmail", "weather": "weather"}):
            result = agent.run_agent(
                client=None, user_input="read my mail", available_jobs=jobs,
                system_instructions="", on_text=streamed.append,
            )
        return result, sent, "".join(streamed)

    def test_mail_alone_goes_to_the_user_and_ends_the_turn(self) -> None:
        with _switch(True):
            result, sent, streamed = self._run(
                {"find_emails": find_emails}, [{"id": "1", "name": "find_emails", "args": {}}],
            )
        self.assertEqual(len(sent), 1)  # no second model step
        self.assertEqual(result.text, "Emails:\n" + _MAIL)
        self.assertEqual(streamed, result.text)
        self.assertTrue(result.calls[0]["private"])

    def test_beside_other_results_the_model_gets_a_note_and_answers_the_rest(self) -> None:
        with _switch(True):
            result, sent, streamed = self._run(
                {"find_emails": find_emails, "weather": weather},
                [{"id": "1", "name": "find_emails", "args": {}}, {"id": "2", "name": "weather", "args": {}}],
                replies=("It's sunny.",),
            )
        self.assertEqual(len(sent), 2)
        self.assertNotIn(_SECRET, sent[1])
        self.assertIn("Sunny.", sent[1])
        self.assertEqual(result.text, "Emails:\n" + _MAIL + "\n\nIt's sunny.")
        self.assertEqual(streamed, result.text)

    def test_switched_off_the_model_reads_it_as_before(self) -> None:
        with _switch(False):
            result, sent, _ = self._run(
                {"find_emails": find_emails}, [{"id": "1", "name": "find_emails", "args": {}}],
            )
        self.assertIn(_SECRET, sent[1])
        self.assertNotIn("private", result.calls[0])


class TestKeptTurns(unittest.TestCase):
    def setUp(self) -> None:
        from helpers.conversation import Conversation

        patcher = mock.patch("helpers.conversation._try_persist", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        Conversation.clear()
        self.addCleanup(Conversation.clear)

    def test_history_leaves_it_out_and_the_chat_shows_it(self) -> None:
        from helpers import private_data
        from helpers.conversation import Conversation

        text = "Emails:\n" + _MAIL + "\n\nIt's sunny."
        Conversation.record_turn(
            "read my mail", text,
            calls=[{"name": "find_emails", "args": {}, "result": "Emails:\n" + _MAIL, "private": True}],
            emit=False,
        )
        self.assertNotIn(_SECRET, str(Conversation.get_messages()))
        self.assertIn("It's sunny.", str(Conversation.get_messages()))
        self.assertEqual(private_data.show(Conversation._turns[-1]["assistant"]), text)

    def test_a_result_that_is_not_found_hides_the_whole_reply(self) -> None:
        from helpers import private_data

        kept = private_data.fence("Reworded: " + _SECRET, [{"result": _MAIL, "private": True}])
        self.assertNotIn(_SECRET, private_data.strip(kept))

    def test_a_confirm_button_result_stays_out(self) -> None:
        from helpers.conversation import Conversation
        from helpers.registry import ServiceRegistry

        Conversation.record_turn(
            "reply to Anna", "Should I send it?",
            calls=[{"name": "send_email", "args": {"to": "anna"}, "result": "NOT DONE", "needs_confirm": True}],
            emit=False,
        )
        with _switch(True), mock.patch.dict(ServiceRegistry._job_modules, {"send_email": "gmail"}):
            Conversation.record_confirmed("send_email", {"to": "anna"}, "Reply sent in thread 'The secret plan'.")
        self.assertNotIn(_SECRET, str(Conversation.get_messages()))


class TestOtherPaths(unittest.TestCase):
    def test_new_mail_is_said_as_is_without_the_model(self) -> None:
        from helpers import triggers

        with _switch(True), mock.patch("helpers.notify.notify") as notify, \
                mock.patch("helpers.turn.run_turn") as run_turn:
            triggers._fire(triggers._by_name("new_email"), "New mail: 'The secret plan' from Anna.")
        run_turn.assert_not_called()
        self.assertTrue(notify.call_args.kwargs["private"])

    def test_who_is_anna_leaves_out_mail(self) -> None:
        from helpers import people

        with _switch(True), mock.patch("helpers.config.Config.is_module_enabled", return_value=True), \
                mock.patch.object(people, "recent_mail") as recent_mail:
            line = people._mail("Anna", [])
        recent_mail.assert_not_called()
        self.assertIn("privacy setting", line)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
