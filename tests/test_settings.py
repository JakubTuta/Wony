"""The settings page writes config.yaml. That file is also hand-edited, and it
is the only thing standing between a user and an assistant that sends email
without being asked — so both halves are covered here: the writer must not eat
the comments, and the endpoint must not accept a key nobody offered.

Run directly: python tests/test_settings.py
"""
import io
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from helpers import config_writer  # noqa: E402

SAMPLE = """# Wony configuration
assistant:
  name: "Wony"        # what you call it
  owner_name: "User"

voice:
  speed: 1.0
  wake_word:
    enabled: false
    phrase: "hey jarvis"

enabled_modules:
  - ai
  - basics

server:
  # keep this on localhost
  host: "127.0.0.1"
  port: 8000
"""


class TestConfigWriter(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with io.open(self.path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE)

    def _load(self) -> dict:
        import yaml

        with io.open(self.path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _text(self) -> str:
        with io.open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def test_comments_survive_a_write(self) -> None:
        """Rewriting the file with a YAML dumper would delete every comment in
        it — which is most of what makes config.yaml readable."""
        config_writer.update(self.path, {"voice.speed": 1.4})
        text = self._text()
        self.assertIn("# Wony configuration", text)
        self.assertIn("# keep this on localhost", text)
        self.assertIn("# what you call it", text)
        self.assertEqual(self._load()["voice"]["speed"], 1.4)

    def test_nested_key_keeps_its_siblings(self) -> None:
        config_writer.update(self.path, {"voice.wake_word.enabled": True})
        wake_word = self._load()["voice"]["wake_word"]
        self.assertEqual(wake_word, {"enabled": True, "phrase": "hey jarvis"})

    def test_missing_key_and_block_are_created(self) -> None:
        config_writer.update(
            self.path,
            {"modules.gmail.allow_write": True, "voice.wake_word.threshold": 0.4},
        )
        data = self._load()
        self.assertIs(data["modules"]["gmail"]["allow_write"], True)
        self.assertEqual(data["voice"]["wake_word"]["threshold"], 0.4)
        self.assertEqual(data["voice"]["wake_word"]["phrase"], "hey jarvis")

    def test_list_is_replaced_wholesale(self) -> None:
        config_writer.update(self.path, {"enabled_modules": ["ai", "status", "weather"]})
        self.assertEqual(self._load()["enabled_modules"], ["ai", "status", "weather"])
        # The section after the list must survive being rewritten.
        self.assertEqual(self._load()["server"]["port"], 8000)

    def test_values_that_yaml_would_misread_are_quoted(self) -> None:
        config_writer.update(
            self.path,
            {
                "assistant.name": "yes",
                "assistant.owner_name": "Tuta: the second",
                "voice.hotkeys.push_to_talk": "<ctrl>+<alt>+w",
            },
        )
        data = self._load()
        self.assertEqual(data["assistant"]["name"], "yes")
        self.assertEqual(data["assistant"]["owner_name"], "Tuta: the second")
        self.assertEqual(data["voice"]["hotkeys"]["push_to_talk"], "<ctrl>+<alt>+w")

    def test_null_round_trips(self) -> None:
        config_writer.update(self.path, {"voice.hotkeys.push_to_talk": None})
        self.assertIsNone(self._load()["voice"]["hotkeys"]["push_to_talk"])


class TestSettingsSurface(unittest.TestCase):
    """The editable surface is an allowlist. Anything else reaching config.yaml
    through an unauthenticated local endpoint would be a way to rewrite the
    file arbitrarily."""

    def setUp(self) -> None:
        from helpers.config import Config

        Config.load()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with io.open(self.path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE)

        import helpers.settings as settings

        self.settings = settings
        self._real_file = settings.CONFIG_FILE
        settings.CONFIG_FILE = self.path

    def tearDown(self) -> None:
        self.settings.CONFIG_FILE = self._real_file
        from helpers.config import Config

        Config.load()

    def test_unknown_key_is_refused(self) -> None:
        with self.assertRaises(self.settings.SettingsError):
            self.settings.apply({"ai.anthropic_model": "something"})
        with self.assertRaises(self.settings.SettingsError):
            self.settings.apply({"../../etc/passwd": "x"})

    def test_out_of_range_number_is_refused(self) -> None:
        with self.assertRaises(self.settings.SettingsError):
            self.settings.apply({"voice.volume": 5})

    def test_unknown_module_is_refused(self) -> None:
        with self.assertRaises(self.settings.SettingsError):
            self.settings.apply({}, modules=["basics", "not_a_module"])

    def test_always_on_modules_are_kept(self) -> None:
        result = self.settings.apply({}, modules=["weather"])
        self.assertTrue(result["restart_required"])
        import yaml

        with io.open(self.path, encoding="utf-8") as handle:
            enabled = yaml.safe_load(handle)["enabled_modules"]
        self.assertIn("ai", enabled)
        self.assertIn("status", enabled)
        self.assertIn("weather", enabled)

    def test_every_field_key_exists_in_the_schema(self) -> None:
        """A key that does not resolve reads back as its default no matter what
        was written, so the control looks live and does nothing."""
        from helpers.config import Config

        missing = object()
        for key in self.settings._BY_KEY:
            with self.subTest(key=key):
                self.assertIsNot(
                    Config.get(key, missing), missing, f"{key} is not in the config schema"
                )

    def test_every_described_field_is_writable(self) -> None:
        """describe() and apply() share one field list; a field the UI shows but
        apply() rejects would be a dead control."""
        described = [
            field["key"]
            for section in self.settings.describe()["sections"]
            for field in section["fields"]
        ]
        self.assertTrue(described)
        for key in described:
            self.assertIn(key, self.settings._BY_KEY, f"{key} is shown but not writable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
