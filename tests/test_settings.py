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
  # how it addresses you
  owner_name: "User"

voice:
  speed: 1.0
  wake_word:
    enabled: false
    phrase: "hey jarvis"

enabled_modules:
  - ai
  - basics
  # - weather        # switch on for forecasts

# where the web page listens
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

    def test_a_scalar_leaves_the_comment_below_it_alone(self) -> None:
        """The comment under a value documents the key *below* it. Rewriting
        the value over it strips the file's documentation one setting at a
        time, and nothing about the write looks wrong when it happens."""
        config_writer.update(self.path, {"assistant.name": "Jarvis"})
        text = self._text()
        self.assertIn("# how it addresses you", text)
        self.assertIn("# what you call it", text)  # its own trailing comment
        self.assertEqual(self._load()["assistant"]["owner_name"], "User")

    def test_a_list_leaves_the_next_sections_comment_alone(self) -> None:
        config_writer.update(self.path, {"enabled_modules": ["ai", "weather"]})
        text = self._text()
        self.assertIn("# where the web page listens", text)
        self.assertEqual(self._load()["enabled_modules"], ["ai", "weather"])

    def test_switching_an_option_on_does_not_leave_its_comment_behind(self) -> None:
        """The commented-out option and the new active line used to sit side by
        side, so every module a user switched on was listed twice."""
        config_writer.update(self.path, {"enabled_modules": ["ai", "basics", "weather"]})
        text = self._text()
        self.assertIn("  - weather        # switch on for forecasts\n", text)
        self.assertNotIn("# - weather", text)
        self.assertEqual(text.count("switch on for forecasts"), 1)

    def test_switching_an_option_off_keeps_it_as_a_comment_with_its_note(self) -> None:
        config_writer.update(self.path, {"enabled_modules": ["ai", "weather"]})
        config_writer.update(self.path, {"enabled_modules": ["ai"]})
        text = self._text()
        self.assertIn("  # - weather        # switch on for forecasts\n", text)
        self.assertEqual(self._load()["enabled_modules"], ["ai"])

    def test_a_list_written_twice_is_unchanged(self) -> None:
        wanted = {"enabled_modules": ["ai", "weather"]}
        config_writer.update(self.path, wanted)
        once = self._text()
        config_writer.update(self.path, wanted)
        self.assertEqual(self._text(), once)

    def test_an_already_doubled_list_is_merged(self) -> None:
        """What the old writer left in config.yaml: the module as a bare line and
        again as a commented line carrying the description."""
        with io.open(self.path, "w", encoding="utf-8") as handle:
            handle.write(
                "enabled_modules:\n  - basics\n  - system\n"
                "  # - system         # battery, disk space, memory, network\n"
                "  # - spotify        # play, pause, skip\n\nvoice:\n  speed: 1.0\n"
            )
        config_writer.update(self.path, {"enabled_modules": ["basics", "system"]})
        self.assertEqual(
            self._text(),
            "enabled_modules:\n  - basics\n"
            "  - system         # battery, disk space, memory, network\n"
            "  # - spotify        # play, pause, skip\n\nvoice:\n  speed: 1.0\n",
        )

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

    def test_remove_takes_the_key_its_comment_and_an_emptied_parent(self) -> None:
        """setup.py retires old keys this way; a half-removed block would leave
        config.yaml unparseable or with a dangling section header."""
        removed = config_writer.remove(
            self.path, ["server.host", "server.port", "assistant.owner_name", "not.there"]
        )
        self.assertEqual(removed, ["server.host", "server.port", "assistant.owner_name"])
        data = self._load()
        self.assertNotIn("server", data)
        self.assertNotIn("owner_name", data["assistant"])
        text = self._text()
        self.assertNotIn("# how it addresses you", text)
        self.assertNotIn("# keep this on localhost", text)
        self.assertIn("# what you call it", text)
        self.assertEqual(data["enabled_modules"], ["ai", "basics"])

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

    def test_always_on_modules_are_not_written(self) -> None:
        """They are on whatever the file says; writing them made every saved
        config list ai/status/employer as if they were choices."""
        result = self.settings.apply({}, modules=["weather"])
        self.assertTrue(result["restart_required"])
        import yaml

        with io.open(self.path, encoding="utf-8") as handle:
            enabled = yaml.safe_load(handle)["enabled_modules"]
        self.assertEqual(enabled, ["weather"])

    def test_null_choice_round_trips(self) -> None:
        """'Windows default' on the page is null in the file, not the text."""
        self.settings.apply({"voice.input_device": "Windows default"})
        import yaml

        with io.open(self.path, encoding="utf-8") as handle:
            voice = yaml.safe_load(handle)["voice"]
        self.assertIsNone(voice["input_device"])

    def test_every_field_key_exists_in_the_schema(self) -> None:
        """A key that does not resolve reads back as its default no matter what
        was written, so the control looks live and does nothing.

        Secret fields are excluded: their key is an environment variable name,
        not a config.yaml path, and Config.get() rightly does not know it.
        """
        from helpers.config import Config

        missing = object()
        for _, fields in self.settings._all_sections():
            for field in fields:
                if field.kind == "secret":
                    continue
                with self.subTest(key=field.key):
                    self.assertIsNot(
                        Config.get(field.key, missing), missing,
                        f"{field.key} is not in the config schema",
                    )

    def test_every_option_in_the_example_config_is_on_the_page(self) -> None:
        """config.example.yaml promises "everything here can also be changed on
        the Settings page". An option added to the file but not to _FIELDS
        leaves the page silently short."""
        import yaml

        with io.open(os.path.join(_REPO_ROOT, "config.example.yaml"), encoding="utf-8") as handle:
            example = yaml.safe_load(handle)

        def leaves(node: dict, prefix: str = "") -> list:
            found = []
            for name, value in node.items():
                if isinstance(value, dict):
                    found += leaves(value, f"{prefix}{name}.")
                else:
                    found.append(f"{prefix}{name}")
            return found

        # enabled_modules is the Features list, not a field.
        offered = {field.key for _, fields in self.settings._FIELDS for field in fields}
        for key in leaves({k: v for k, v in example.items() if k != "enabled_modules"}):
            with self.subTest(key=key):
                self.assertIn(key, offered, f"{key} is in config.example.yaml but not on the Settings page")

    def test_describe_field_matches_what_the_page_gets(self) -> None:
        """setup.py asks through describe_field; it must be the page's own field."""
        page = {
            field["key"]: field
            for section in self.settings.describe()["sections"]
            for field in section["fields"]
        }
        self.assertEqual(self.settings.describe_field("voice.speed"), page["voice.speed"])
        with self.assertRaises(self.settings.SettingsError):
            self.settings.describe_field("not.a.setting")

    def test_every_described_field_is_writable(self) -> None:
        """describe() and apply() share one field lookup; a field the UI shows
        but apply() rejects would be a dead control."""
        described = [
            field["key"]
            for section in self.settings.describe()["sections"]
            for field in section["fields"]
        ]
        self.assertTrue(described)
        for key in described:
            self.assertIsNotNone(self.settings._field_by_key(key), f"{key} is shown but not writable")


class TestSecretFields(unittest.TestCase):
    """A secret field's key is an env var name, written to .env instead of
    config.yaml — apply() must route it there and never echo the value back."""

    def setUp(self) -> None:
        import helpers.settings as settings

        self.settings = settings
        self.dir = tempfile.mkdtemp()
        self._real_env_file = settings.ENV_FILE
        settings.ENV_FILE = os.path.join(self.dir, ".env")
        self._had_key = "ANTHROPIC_API_KEY" in os.environ
        self._old_value = os.environ.get("ANTHROPIC_API_KEY")

    def tearDown(self) -> None:
        self.settings.ENV_FILE = self._real_env_file
        if self._had_key:
            os.environ["ANTHROPIC_API_KEY"] = self._old_value
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_a_typed_value_is_written_to_env_and_environ(self) -> None:
        result = self.settings.apply({"ANTHROPIC_API_KEY": "sk-test-123"})
        self.assertTrue(result["restart_required"])
        self.assertIn("ANTHROPIC_API_KEY", result["written"])
        self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "sk-test-123")
        with io.open(self.settings.ENV_FILE, encoding="utf-8") as handle:
            self.assertIn('ANTHROPIC_API_KEY="sk-test-123"', handle.read())

    def test_a_blank_value_leaves_it_unchanged(self) -> None:
        """describe() never sends the real secret back, so a field the user
        never touched always arrives here as blank — writing it would blow
        away whatever was already set."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-existing"
        result = self.settings.apply({"ANTHROPIC_API_KEY": ""})
        self.assertEqual(result["written"], [])
        self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "sk-existing")

    def test_describe_never_reveals_the_value(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-existing"
        fields = [f for _, fs in self.settings._all_sections() for f in fs if f.key == "ANTHROPIC_API_KEY"]
        self.assertEqual(len(fields), 1)
        self.assertIs(self.settings._current(fields[0]), True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
