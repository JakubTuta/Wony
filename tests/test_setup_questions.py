"""setup.py used to skip most of config.example.yaml: personality, "speak up on
its own" and "learn about me" were never asked, nor the clock timeout or the
power-off switch. Nothing failed — the questions just were not there — so these
pin what setup asks and where the answers land.

Run directly: python tests/test_setup_questions.py
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# Only for a port clash; the default works, and nobody picks a free port by guessing.
_NOT_ASKED = {"server.port"}


def _load_setup():
    spec = importlib.util.spec_from_file_location("setup_under_test", os.path.join(_REPO_ROOT, "setup.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSetupQuestions(unittest.TestCase):
    def setUp(self) -> None:
        import helpers.settings as settings

        self.setup = _load_setup()
        self.settings = settings
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        shutil.copyfile(os.path.join(_REPO_ROOT, "config.example.yaml"), self.path)

        # Config, the settings screen and setup must all read and write this
        # copy, not the config.yaml of whoever runs the tests.
        patches = [
            mock.patch("helpers.config._resolve_yaml_path", return_value=self.path),
            mock.patch.object(settings, "CONFIG_FILE", self.path),
            mock.patch.object(self.setup, "CONFIG", self.path),
            mock.patch.object(self.setup, "repo_on_path"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(self._reload_config)

    def _reload_config(self) -> None:
        from helpers.config import Config

        Config.load()

    def _saved(self) -> dict:
        import yaml

        with io.open(self.path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _answer(self, answers: dict):
        """Stand in for input(): the answer whose key appears in the prompt, or
        Enter when none does."""
        def reply(prompt: str = "") -> str:
            for fragment, answer in answers.items():
                if fragment in prompt:
                    return answer
            return ""
        return mock.patch("builtins.input", side_effect=reply)

    def test_about_you_asks_personality_and_both_privacy_switches(self) -> None:
        answers = {
            "Personality": "Dry humour, short answers.",
            "Speak up on its own": "y",
            "Learn about me on its own": "y",
        }
        with self._answer(answers):
            self.setup.step_assistant()
        assistant = self._saved()["assistant"]
        self.assertEqual(assistant["personality"], "Dry humour, short answers.")
        self.assertIs(assistant["proactive"]["enabled"], True)
        self.assertIs(assistant["memory"]["learn_from_my_data"], True)

    def test_pressing_enter_through_about_you_leaves_the_switches_off(self) -> None:
        with self._answer({}):
            self.setup.step_assistant()
        assistant = self._saved()["assistant"]
        self.assertIs(assistant["proactive"]["enabled"], False)
        self.assertIs(assistant["memory"]["learn_from_my_data"], False)

    def test_a_number_out_of_range_is_asked_again(self) -> None:
        with mock.patch("builtins.input", side_effect=["99", "10"]):
            self.setup.ask_setting("ai.history.max_turns")
        self.assertEqual(self._saved()["ai"]["history"]["max_turns"], 10)

    def test_this_device_asks_the_screen_and_power_settings(self) -> None:
        answers = {
            "Power off this device": "y",
            "Ask before every device": "y",
            "Go to the clock after": "30",
        }
        with self._answer(answers):
            self.setup.step_device({"kiosk"})
        saved = self._saved()
        self.assertIs(saved["modules"]["basics"]["allow_power_off"], True)
        self.assertIs(saved["kiosk"]["confirm_all_devices"], True)
        self.assertEqual(saved["kiosk"]["idle_minutes"], 30)
        # Enter on the 3-or-4 choice keeps a number, not the text "3".
        self.assertEqual(saved["kiosk"]["home_columns"], 3)

    def test_pressing_enter_through_this_device_leaves_the_switches_off(self) -> None:
        with self._answer({}):
            self.setup.step_device({"kiosk"})
        saved = self._saved()
        self.assertIs(saved["modules"]["basics"]["allow_power_off"], False)
        self.assertIs(saved["kiosk"]["confirm_all_devices"], False)

    def test_without_the_kiosk_the_screen_is_not_asked_about(self) -> None:
        prompts = []

        def reply(prompt: str = "") -> str:
            prompts.append(prompt)
            return ""

        with mock.patch("builtins.input", side_effect=reply):
            self.setup.step_device(set())
        self.assertFalse([p for p in prompts if "clock" in p or "every device" in p])

    def test_the_working_day_is_asked(self) -> None:
        with self._answer({"Working day starts": "8", "Working day ends": "17"}):
            self.setup.step_working_day()
        calendar = self._saved()["modules"]["calendar"]
        self.assertEqual((calendar["work_start_hour"], calendar["work_end_hour"]), (8, 17))

    def test_every_setting_on_the_screen_is_asked_somewhere_in_setup(self) -> None:
        """A setting added to the Settings screen but never to setup is the same
        silent gap again."""
        with io.open(os.path.join(_REPO_ROOT, "setup.py"), encoding="utf-8") as handle:
            source = handle.read()
        for _, fields in self.settings._FIELDS:
            for field in fields:
                if field.key in _NOT_ASKED:
                    continue
                with self.subTest(key=field.key):
                    self.assertIn(f'"{field.key}"', source, f"setup.py never asks about {field.key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
