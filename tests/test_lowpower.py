"""Deep sleep: the state machine, not the hardware.

The display backends can only be tested on the device they are for, so every
test here stubs them out. What is worth guarding is everything around them —
that a bad wake time never leaves the panel dark, that waking is idempotent
because the screen calls it on any touch, and that a scheduled wake actually
arrives.

Run directly: python tests/test_lowpower.py
"""
import datetime
import os
import sys
import threading
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class _FakePanel:
    """Stands in for helpers.display, and records what it was asked to do."""

    def __init__(self) -> None:
        self.calls: list = []
        self.lit = True

    def off(self):
        self.calls.append(False)
        self.lit = False
        return True, "fake"

    def on(self):
        self.calls.append(True)
        self.lit = True
        return True, "fake"


class TestWakeTimeParsing(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import lowpower

        self.lowpower = lowpower

    def test_blank_means_wake_on_touch(self) -> None:
        self.assertIsNone(self.lowpower.parse_wake_time(""))
        self.assertIsNone(self.lowpower.parse_wake_time("   "))

    def test_clock_time_is_always_in_the_future(self) -> None:
        """'sleep at 23:00, wake at 07:00' must not resolve to this morning."""
        from helpers.timeutil import now_local

        now = now_local()
        for hour in range(24):
            with self.subTest(hour=hour):
                target = self.lowpower.parse_wake_time(f"{hour:02d}:30")
                assert target is not None
                self.assertGreater(target, now)
                self.assertEqual(target.hour, hour)
                self.assertEqual(target.minute, 30)
                self.assertLessEqual(target - now, datetime.timedelta(days=1))

    def test_durations(self) -> None:
        from helpers.timeutil import now_local

        now = now_local()
        eight = self.lowpower.parse_wake_time("8h")
        ninety = self.lowpower.parse_wake_time("90m")
        assert eight is not None and ninety is not None
        self.assertAlmostEqual((eight - now).total_seconds(), 8 * 3600, delta=5)
        self.assertAlmostEqual((ninety - now).total_seconds(), 90 * 60, delta=5)

    def test_nonsense_is_refused(self) -> None:
        for text in ("tomorrow-ish", "25:00", "07:99", "-3h"):
            with self.subTest(text=text):
                with self.assertRaises(self.lowpower.WakeTimeError):
                    self.lowpower.parse_wake_time(text)

    def test_a_past_datetime_is_refused(self) -> None:
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        with self.assertRaises(self.lowpower.WakeTimeError):
            self.lowpower.parse_wake_time(past)


class TestSleepCycle(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import display, lowpower
        from helpers.cache import Cache

        self.lowpower = lowpower
        self.panel = _FakePanel()
        self._real = (display.off, display.on)
        display.off, display.on = self.panel.off, self.panel.on
        # enter() remembers the wake time it was given, and that is the user's
        # real cache file.
        self._saved = Cache.get_value(lowpower._LAST_WAKE_KEY, None)
        lowpower.reset_on_start()
        self.panel.calls.clear()

    def tearDown(self) -> None:
        from helpers import display
        from helpers.cache import Cache

        self.lowpower.reset_on_start()
        display.off, display.on = self._real
        Cache.set_value(self.lowpower._LAST_WAKE_KEY, self._saved)

    def test_sleep_then_wake(self) -> None:
        self.lowpower.enter(wake_at="", reason="test")
        self.assertTrue(self.lowpower.is_asleep())
        self.assertFalse(self.panel.lit)
        self.assertIsNone(self.lowpower.status()["wake_at"])

        self.lowpower.wake(reason="test")
        self.assertFalse(self.lowpower.is_asleep())
        self.assertTrue(self.panel.lit)

    def test_waking_twice_is_harmless(self) -> None:
        """The overlay posts /api/wake on any touch without checking first."""
        self.lowpower.enter(reason="test")
        self.lowpower.wake(reason="test")
        before = len(self.panel.calls)
        self.lowpower.wake(reason="test")
        self.assertEqual(len(self.panel.calls), before)

    def test_a_bad_wake_time_leaves_the_screen_on(self) -> None:
        """The one failure that matters: dark, with no wake time and nobody
        expecting it."""
        with self.assertRaises(self.lowpower.WakeTimeError):
            self.lowpower.enter(wake_at="half past nine", reason="test")
        self.assertFalse(self.lowpower.is_asleep())
        self.assertTrue(self.panel.lit)
        self.assertEqual(self.panel.calls, [])

    def test_sleeping_again_re_arms_the_wake_time(self) -> None:
        self.lowpower.enter(wake_at="07:00", reason="test")
        first = self.lowpower.status()["wake_at"]
        self.lowpower.enter(wake_at="08:00", reason="test")
        second = self.lowpower.status()["wake_at"]
        self.assertNotEqual(first, second)
        self.assertIn("T08:00:00", second)
        self.assertTrue(self.lowpower.is_asleep())

    def test_the_scheduled_wake_arrives(self) -> None:
        woke = threading.Event()
        from helpers import events

        def listener(payload: dict) -> None:
            if payload.get("type") == "sleep" and not payload.get("asleep"):
                woke.set()

        events.subscribe(listener)
        try:
            # 0.6 seconds, expressed the way the parser takes it.
            self.lowpower.enter(wake_at="0.01m", reason="test")
            self.assertTrue(woke.wait(timeout=10), "the wake timer never fired")
        finally:
            events.unsubscribe(listener)

        self.assertFalse(self.lowpower.is_asleep())
        self.assertTrue(self.panel.lit)

    def test_only_a_touch_or_the_clock_can_wake_it(self) -> None:
        """Sleep is for not being disturbed. A message arriving overnight is
        recorded and waits until morning; it must not light the room up.

        Checked against the source rather than by raising a real notification,
        which would write to the database this test has no business touching.
        """
        import inspect

        from helpers import lowpower, notify

        self.assertFalse(hasattr(lowpower, "on_notification"))
        self.assertNotIn("lowpower", inspect.getsource(notify))

    def test_restart_turns_the_panel_back_on(self) -> None:
        """A crash mid-sleep leaves a dark panel and a process that has no idea."""
        self.lowpower.enter(reason="test")
        self.assertFalse(self.panel.lit)
        self.lowpower.reset_on_start()
        self.assertTrue(self.panel.lit)
        self.assertFalse(self.lowpower.is_asleep())


class TestLastWakeIsRemembered(unittest.TestCase):
    """The one persisted thing: last night's answer, so tonight is one tap."""

    def setUp(self) -> None:
        from helpers import display, lowpower
        from helpers.cache import Cache

        self.lowpower = lowpower
        self.panel = _FakePanel()
        self._real = (display.off, display.on)
        display.off, display.on = self.panel.off, self.panel.on
        self._saved = Cache.get_value(lowpower._LAST_WAKE_KEY, None)
        lowpower.reset_on_start()

    def tearDown(self) -> None:
        from helpers import display
        from helpers.cache import Cache

        self.lowpower.reset_on_start()
        display.off, display.on = self._real
        Cache.set_value(self.lowpower._LAST_WAKE_KEY, self._saved)

    def test_a_chosen_time_comes_back(self) -> None:
        self.lowpower.enter(wake_at="06:45", reason="test")
        self.lowpower.wake(reason="test")
        self.assertEqual(self.lowpower.status()["last_wake"], "06:45")

    def test_wake_on_touch_is_also_an_answer(self) -> None:
        """Empty is a choice — "until I touch it" — not an absence of one."""
        self.lowpower.enter(wake_at="", reason="test")
        self.assertEqual(self.lowpower.status()["last_wake"], "")

    def test_a_refused_time_is_not_remembered(self) -> None:
        """Storing it would hand the same error back tomorrow night."""
        self.lowpower.enter(wake_at="06:45", reason="test")
        self.lowpower.wake(reason="test")
        with self.assertRaises(self.lowpower.WakeTimeError):
            self.lowpower.enter(wake_at="quarter to seven", reason="test")
        self.assertEqual(self.lowpower.status()["last_wake"], "06:45")


class TestNothingIsConfigurable(unittest.TestCase):
    """Sleep deliberately has no settings: which command darkens this panel is
    a fact about the device, and the rest are answers nobody should have to
    give twice. A key creeping back in is the regression."""

    def test_sleep_has_no_config_keys(self) -> None:
        from helpers.config import Config

        self.assertIsNone(Config.get("kiosk.sleep", None))

    def test_sleep_has_no_settings_fields(self) -> None:
        from helpers.settings import _BY_KEY

        self.assertEqual([key for key in _BY_KEY if "sleep" in key], [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
