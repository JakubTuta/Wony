"""What Wony says without being asked is part of the conversation.

The calendar watcher told the user about a new train on Telegram; asked "what
time is the event?", the model had never seen that message. notify() reached
the bell, the speaker and the phone, but not the history the next turn reads.

Run directly: python tests/test_notices.py
"""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _NoticeTest(unittest.TestCase):
    """A throwaway database, no speaker, no log files, and every event caught."""

    def setUp(self) -> None:
        import helpers.memory_db as db
        from helpers import events
        from helpers.conversation import Conversation

        tmpdir = tempfile.TemporaryDirectory()
        real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(tmpdir.name, "test.db")

        def restore() -> None:
            db.close()
            db._DB_FILE = real_db_file
            tmpdir.cleanup()

        self.addCleanup(restore)
        for patcher in (
            mock.patch("helpers.audio.Audio"),
            mock.patch("helpers.logger.logger"),
            mock.patch("helpers.triggers.logger"),
            mock.patch("helpers.semantic.is_available", return_value=False),
            # Wide enough that nothing is trimmed, so no summary call is made.
            mock.patch.object(Conversation, "_max_turns", return_value=50),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        Conversation.clear()
        self.addCleanup(Conversation.clear)
        self.events = []
        events.subscribe(self.events.append)
        self.addCleanup(events.unsubscribe, self.events.append)

    def history(self):
        from helpers.conversation import Conversation

        return Conversation.get_messages()


class TestTheNextTurnSeesIt(_NoticeTest):
    def test_the_calendar_watchers_message_is_in_the_history(self) -> None:
        from helpers import triggers
        from helpers.turn import TurnResult

        said = "A new calendar entry: a PKP Intercity trip from Kraków to Warszawa."
        watcher = triggers.Trigger("new_event", "", lambda: None, 0.0, 0.0, trusted=False)
        with mock.patch("helpers.turn.run_turn", return_value=TurnResult(said, [], False, None)):
            triggers._fire(watcher, "New on the calendar: 'Podróż z PKP Intercity'.")

        user, assistant = self.history()
        self.assertIn("Nobody asked", user["content"])
        self.assertIn("trigger:new_event", user["content"])
        self.assertIn(said, assistant["content"])
        # An invite title is someone else's words: fenced for the model...
        self.assertIn("<<<untrusted", assistant["content"])
        # ...but not for the person reading the chat.
        (turn,) = [e for e in self.events if e.get("type") == "turn"]
        self.assertEqual(turn["assistant"], said)
        self.assertEqual(turn["source"], "trigger:new_event")

    def test_a_reminder_reads_as_wonys_own_words_and_outlives_a_restart(self) -> None:
        from helpers.memory_db import visible_turns
        from helpers.notify import notify

        notify("Reminder: call Anna", kind="reminder", source="scheduler")

        _, assistant = self.history()
        self.assertEqual(assistant["content"], "Reminder: call Anna")
        (row,) = visible_turns(5)  # what a restart seeds the history from
        self.assertEqual(row["source"], "scheduler")
        self.assertEqual(row["user_text"], "")

    def test_a_browse_result_arrives_fenced(self) -> None:
        from helpers import browser
        from modules import web

        def run_now(name, target, pass_stop_event=False):
            target(threading.Event())
            return True

        with mock.patch.object(browser, "available", return_value=True), \
                mock.patch.object(web, "_run_task", return_value="The battery is 5000 mAh."), \
                mock.patch("helpers.jobs.BackgroundJobs.is_running", return_value=False), \
                mock.patch("helpers.jobs.BackgroundJobs.start", side_effect=run_now):
            web._start_task("https://example.com", "find the battery size")

        _, assistant = self.history()
        self.assertIn("5000 mAh", assistant["content"])
        self.assertIn('<<<untrusted source="browse"', assistant["content"])

    def test_a_job_that_notifies_mid_turn_does_not_wait_for_its_own_turn(self) -> None:
        from helpers.decorators import agent_lock
        from helpers.notify import notify

        def job_inside_a_turn() -> None:
            with agent_lock:
                notify("Google Maps is near its free allowance.", kind="alert", source="maps")

        worker = threading.Thread(target=job_inside_a_turn, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "notify() waited on the agent_lock its own turn holds")
        self.assertEqual(len(self.history()), 2)

    def test_the_chat_window_shows_it_as_wony_speaking_up(self) -> None:
        from helpers.notify import notify
        from tests.test_web_app import _load_app

        notify("New mail: 'Lunch?' from Ada.", kind="alert", source="trigger:new_email", untrusted=True)

        (turn,) = _load_app().get("/api/chat/history").json()["turns"]
        self.assertEqual(turn["source"], "trigger:new_email")
        self.assertEqual(turn["assistant"], "New mail: 'Lunch?' from Ada.")
        self.assertEqual(turn["user"], "")


class TestWatcherWithoutTheModel(_NoticeTest):
    """With the AI unreachable a watcher still has its news: the plain sentence
    it found, not "Something went wrong" and not nothing."""

    def _fire(self, result) -> str:
        from helpers import triggers

        watcher = triggers.Trigger("new_event", "", lambda: None, 0.0, 0.0, trusted=False)
        fact = "New on the calendar: 'Train to Warszawa' (2026-10-17 12:16)."
        with mock.patch("helpers.turn.run_turn", return_value=result):
            triggers._fire(watcher, fact)
        (sent,) = [e["text"] for e in self.events if e.get("type") == "notification"]
        self.assertIn(fact, self.history()[-1]["content"])
        return sent

    def test_a_failed_ai_call_sends_the_fact(self) -> None:
        from helpers.turn import TurnResult

        failure = "Something went wrong: provider unreachable"
        sent = self._fire(TurnResult(failure, [], False, failure))
        self.assertEqual(sent, "New on the calendar: 'Train to Warszawa' (2026-10-17 12:16).")

    def test_a_turn_that_ran_out_of_time_sends_the_fact(self) -> None:
        from helpers.turn import TurnResult

        sent = self._fire(TurnResult("Sorry, that took too long — I'm stopping there.", [], True, None))
        self.assertIn("Train to Warszawa", sent)

    def test_a_new_event_says_when_it_is(self) -> None:
        from helpers import triggers
        from helpers.registry import ServiceRegistry
        from modules.calendar import Calendar

        cal = Calendar.__new__(Calendar)
        event = {"id": "e1", "summary": "Train to Warszawa", "start": {"dateTime": "2026-10-17T12:16:00+02:00"}}
        with mock.patch.object(triggers, "_module_on", return_value=True), \
                mock.patch.object(ServiceRegistry, "get_service_instance", return_value=cal), \
                mock.patch.object(Calendar, "new_events", return_value=[event]):
            triggers._events_seen.record([])  # past the first poll, which only records
            self.assertEqual(triggers._new_event(), "New on the calendar: 'Train to Warszawa' (2026-10-17 12:16).")


class TestPrivateStaysOffTheModel(_NoticeTest):
    def test_phone_numbers_shown_to_the_user_are_not_in_the_history(self) -> None:
        from modules import contacts
        from modules.contacts import Person, Phone

        service = contacts.Contacts.__new__(contacts.Contacts)
        found = [Person("Tom", ["tom@x.com"], [Phone("mobile", "+48 600 700 800")])]
        with mock.patch.object(contacts.Contacts, "search", return_value=found):
            contacts.Contacts.contact(service, "find", "Tom")

        self.assertEqual(self.history(), [])
        shown = [e for e in self.events if e.get("type") == "notification"]
        self.assertIn("600 700 800", shown[0]["text"])


class TestNoticesAreNotTheUsersWords(_NoticeTest):
    def test_learning_and_the_person_lookup_skip_them(self) -> None:
        from helpers import learn, people
        from helpers.notify import notify

        for i in range(learn._MIN_NEW_TURNS):
            notify(f"Reminder {i}: send Anna the budget", kind="reminder", source="scheduler")

        with mock.patch.object(learn, "_ask_for_facts") as ask:
            self.assertEqual(learn.learn_facts(), 0)
        ask.assert_not_called()
        self.assertEqual(people._talks("Anna", []), "")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
