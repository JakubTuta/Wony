"""Timer/reminder behaviour, without waiting on real clock time.

Reminders are the only timer Wony has, so this covers both plain countdowns and
the "run job X later" path. Run directly: python tests/test_scheduler.py
"""

import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.decorators import capture_response, set_agent_active  # noqa: E402
from helpers.registry import register_job  # noqa: E402

# Same switch the agent loop uses: stops capture_response echoing every job's
# return value into the test output.
set_agent_active(True)

_fired: list = []


@register_job(module_name="basics", summary="test target")
@capture_response
def _fake_device(target: str = "", action: str = "") -> str:
    """
    [TEST JOB] Stand-in for a real controllable device.

    Args:
        target (str): what to act on
        action (str): what to do

    Returns:
        str: confirmation
    """
    _fired.append((target, action))
    return f"Turned {action} {target}."


def _bare_scheduler():
    """A Scheduler with a live APScheduler but no DB — persistence has its own path."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from modules.scheduler import Scheduler

    sched = Scheduler.__new__(Scheduler)
    sched._sched = BackgroundScheduler(daemon=True)
    sched._reminders = {}
    sched._missed = []
    sched._sched.start()
    return sched


class TestParseTrigger(unittest.TestCase):
    def test_seconds_are_a_valid_delay(self) -> None:
        from modules.scheduler import _parse_trigger

        for phrase in ("in 10 seconds", "after 10 seconds", "in 45 seconds"):
            kind, kwargs, error = _parse_trigger(phrase)
            self.assertIsNone(error, phrase)
            self.assertEqual(kind, "date", phrase)
            self.assertGreater(kwargs["run_date"], datetime.now(), phrase)

    def test_clock_times_and_recurrence(self) -> None:
        from modules.scheduler import _parse_trigger

        self.assertEqual(_parse_trigger("tomorrow at 9am")[0], "date")
        self.assertEqual(_parse_trigger("every day at 8am")[0], "cron")
        self.assertEqual(_parse_trigger("every 2 hours")[1], {"hours": 2})

    def test_past_time_is_refused(self) -> None:
        from modules.scheduler import _parse_trigger

        _, _, error = _parse_trigger("yesterday at 9am")
        self.assertIsNotNone(error)


class TestDescribe(unittest.TestCase):
    def test_short_delays_read_as_a_countdown(self) -> None:
        from modules.scheduler import _describe

        now = datetime.now()
        self.assertEqual(_describe(now + timedelta(seconds=10)), "in 10 seconds")
        self.assertEqual(_describe(now + timedelta(seconds=1)), "in 1 second")
        self.assertEqual(_describe(now + timedelta(minutes=5)), "in 5 minutes")

    def test_far_off_times_read_as_a_clock(self) -> None:
        from modules.scheduler import _describe

        tomorrow = datetime.now() + timedelta(days=1)
        self.assertIn(tomorrow.strftime("%d %b"), _describe(tomorrow))


class TestReminders(unittest.TestCase):
    def setUp(self) -> None:
        _fired.clear()
        # Reminders persist to wony.db — a test run must not leave rows in the
        # user's real database.
        for name in ("save_reminder", "delete_reminder"):
            patcher = mock.patch(f"helpers.memory_db.{name}")
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sched = _bare_scheduler()

    def tearDown(self) -> None:
        self.sched._sched.shutdown(wait=False)

    def _add(self, **kwargs) -> str:
        from modules.scheduler import Scheduler

        return Scheduler.add_reminder(self.sched, **kwargs)

    def test_timer_with_an_action_runs_the_job(self) -> None:
        result = self._add(
            when="in 1 second",
            action_job="_fake_device",
            action_args={"target": "kitchen light", "action": "on"},
        )
        self.assertIn("Timer set", result)
        self.assertIn("run _fake_device", result)
        time.sleep(2.5)
        self.assertEqual(_fired, [("kitchen light", "on")])

    def test_action_args_accepts_a_json_string(self) -> None:
        # Gemini sometimes emits object params as a JSON string rather than a dict.
        self._add(
            when="in 1 second",
            action_job="_fake_device",
            action_args='{"target": "lamp", "action": "off"}',
        )
        time.sleep(2.5)
        self.assertEqual(_fired, [("lamp", "off")])

    def test_unknown_action_job_is_refused_up_front(self) -> None:
        result = self._add(when="in 1 hour", action_job="definitely_not_a_job")
        self.assertIn("Unknown action job", result)
        self.assertEqual(self.sched._sched.get_jobs(), [])

    def test_plain_timer_needs_no_action(self) -> None:
        result = self._add(when="in 5 minutes", text="tea is ready")
        self.assertIn("Timer set", result)
        self.assertIn("in 5 minutes", result)

    def test_empty_timer_is_refused(self) -> None:
        self.assertIn("Error", self._add(when="in 5 minutes"))

    def test_list_and_cancel_all(self) -> None:
        from modules.scheduler import Scheduler

        self._add(when="in 5 minutes", text="one")
        self._add(when="in 10 minutes", text="two")
        listing = Scheduler.list_reminders(self.sched)
        self.assertIn("2 active", listing)
        self.assertIn("in 5 minutes", listing)

        self.assertIn("Cancelled", Scheduler.cancel_reminder(self.sched, "all"))
        self.assertEqual(Scheduler.list_reminders(self.sched), "Nothing scheduled.")

    def test_cancel_finds_an_action_only_timer_by_job_name(self) -> None:
        from modules.scheduler import Scheduler

        # An action-only timer has no text, so job name is the only handle on it.
        self._add(when="in 5 minutes", action_job="_fake_device", action_args={})
        self.assertIn("Cancelled", Scheduler.cancel_reminder(self.sched, "_fake_device"))

    def test_action_waits_for_the_agent_lock(self) -> None:
        from helpers.decorators import agent_lock

        # A timer firing mid-turn must not run its job inside another agent's run.
        with agent_lock:
            self._add(
                when="in 1 second",
                action_job="_fake_device",
                action_args={"target": "lamp", "action": "on"},
            )
            time.sleep(2.5)
            self.assertEqual(_fired, [], "action ran while the agent held the lock")

        deadline = time.time() + 5
        while not _fired and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(_fired, [("lamp", "on")])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
