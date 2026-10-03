"""Saying a job's exact name runs it without the model. That shortcut had no
confirm gate, so saying "close computer" shut the PC down with no question.

Run directly: python tests/test_shortcut_gate.py
"""
import os
import sys
import types
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _job(name: str):
    def fn() -> str:
        return name
    fn.__name__ = name
    return fn


class TestShortcutGate(unittest.TestCase):
    def _match(self, said: str, audio: bool, confirms: dict):
        from modules.employer import Employer

        fake = types.SimpleNamespace(
            available_functions=[_job("system_status"), _job("power"), _job("exit")]
        )
        with mock.patch("helpers.registry.ServiceRegistry.get_job_confirms", return_value=confirms), \
                mock.patch("modules.employer.Cache.get_audio", return_value=audio):
            return Employer._check_if_user_input_is_command(fake, said)

    def test_a_confirming_job_goes_to_the_model_instead(self) -> None:
        self.assertIsNone(self._match("power", audio=True, confirms={"power": True}))

    def test_a_harmless_job_still_runs_directly(self) -> None:
        self.assertEqual(self._match("system status", audio=True, confirms={}).__name__, "system_status")

    def test_a_job_whose_default_action_confirms_goes_to_the_model(self) -> None:
        """Said bare, a job runs with its defaults. The gate only reads the
        arguments it is given, so a default of "sleep" slipped past a set of
        gate words that lists "sleep"."""
        from modules.employer import Employer

        def power(action: str = "sleep") -> str:
            return action

        def background_jobs(action: str = "list") -> str:
            return action

        fake = types.SimpleNamespace(available_functions=[power, background_jobs])
        confirms = {"power": {"shutdown", "sleep"}, "background_jobs": {"stop"}}
        with mock.patch("helpers.registry.ServiceRegistry.get_job_confirms", return_value=confirms):
            self.assertIsNone(Employer._check_if_user_input_is_command(fake, "power"))
            self.assertIs(
                Employer._check_if_user_input_is_command(fake, "background jobs"), background_jobs
            )

    def test_typed_exit_still_works_but_spoken_exit_asks(self) -> None:
        self.assertIsNotNone(self._match("exit", audio=False, confirms={"exit": True}))
        self.assertIsNone(self._match("exit", audio=True, confirms={"exit": True}))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
