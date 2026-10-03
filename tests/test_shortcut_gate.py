"""Saying a job's exact name runs it without the model. That shortcut has no
second turn to ask in, so it must never run a job that confirms. Said bare, a
job runs with its defaults, and `power` defaults to "sleep" — a word its gate
lists, but one the gate never saw because no argument was passed.

Run directly: python tests/test_shortcut_gate.py
"""
import os
import sys
import types
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _power(action: str = "sleep") -> str:
    return action


def _background_jobs(action: str = "list") -> str:
    return action


def _weather(city: str = "") -> str:
    return city


_power.__name__ = "power"
_background_jobs.__name__ = "background_jobs"
_weather.__name__ = "weather"


class TestShortcutGate(unittest.TestCase):
    def _match(self, said: str, confirms: dict):
        from modules.employer import Employer

        fake = types.SimpleNamespace(
            available_functions=[_power, _background_jobs, _weather]
        )
        with mock.patch("helpers.registry.ServiceRegistry.get_job_confirms", return_value=confirms):
            return Employer._check_if_user_input_is_command(fake, said)

    def test_a_confirming_job_goes_to_the_model_instead(self) -> None:
        self.assertIsNone(self._match("power", confirms={"power": True}))

    def test_a_job_whose_default_action_confirms_goes_to_the_model(self) -> None:
        confirms = {"power": {"shutdown", "restart", "sleep"}}
        self.assertIsNone(self._match("power", confirms=confirms))

    def test_a_job_whose_default_action_is_harmless_still_runs_directly(self) -> None:
        confirms = {"background_jobs": {"stop"}}
        self.assertIs(self._match("background jobs", confirms=confirms), _background_jobs)

    def test_a_harmless_job_still_runs_directly(self) -> None:
        self.assertIs(self._match("weather", confirms={}), _weather)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
