"""Calendar dates used to fall back to today on anything that was not ISO or
today/tomorrow/yesterday, so "create it on Friday" quietly booked today, and
"14.30" crashed the time parser.

Run directly: python tests/test_calendar_dates.py
"""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# A Wednesday, so "friday" and "next monday" both have one obvious answer.
_NOW = datetime(2026, 9, 30, 10, 0).astimezone()


class TestCalendarDates(unittest.TestCase):
    def setUp(self) -> None:
        from modules.calendar import Calendar

        self.cal = Calendar.__new__(Calendar)
        patcher = mock.patch("helpers.timeutil.now_local", return_value=_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("modules.calendar.now_local", return_value=_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_weekdays_land_on_the_right_day(self) -> None:
        self.assertEqual(self.cal._parse_date("friday").date().isoformat(), "2026-10-02")
        self.assertEqual(self.cal._parse_date("next monday").date().isoformat(), "2026-10-05")
        self.assertEqual(self.cal._parse_date("tomorrow").date().isoformat(), "2026-10-01")
        self.assertEqual(self.cal._parse_date("2026-12-24").date().isoformat(), "2026-12-24")
        self.assertEqual(self.cal._parse_date("").date().isoformat(), "2026-09-30")

    def test_unreadable_dates_are_refused_not_turned_into_today(self) -> None:
        with self.assertRaises(ValueError):
            self.cal._parse_date("the day after the meeting with bob")

    def test_times_in_common_spellings(self) -> None:
        base = self.cal._parse_date("friday")
        for spoken, expected in (("14.30", "14:30"), ("2pm", "14:00"), ("9:30am", "09:30"), ("9", "09:00")):
            with self.subTest(spoken=spoken):
                self.assertEqual(self.cal._parse_time(spoken, base).strftime("%H:%M"), expected)
        with self.assertRaises(ValueError):
            self.cal._parse_time("lunchish", base)

    def test_a_job_says_so_instead_of_raising(self) -> None:
        out = self.cal.manage_event(action="create", title="Dentist", date="sometime soonish")
        self.assertIn("couldn't understand the date", out)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
