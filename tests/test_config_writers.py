"""env_writer and config_writer hand-edit .env and config.yaml in place to
keep comments and key order. A value with a stray quote or a raw control
character could otherwise break out of its quotes and plant an extra line —
a new KEY=value in .env, or a sibling key in config.yaml.

Run directly: python tests/test_config_writers.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestEnvWriter(unittest.TestCase):
    def _env_path(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        self.addCleanup(os.remove, path)
        return path

    def test_a_newline_in_a_value_is_refused(self) -> None:
        from helpers import env_writer

        path = self._env_path()
        with self.assertRaises(ValueError):
            env_writer.update(path, {"API_KEY": 'x"\nEVIL_KEY=planted'})
        # Refused before writing anything, not half-written.
        self.assertEqual(env_writer.read(path), {})

    def test_a_quote_in_a_value_is_refused(self) -> None:
        from helpers import env_writer

        path = self._env_path()
        with self.assertRaises(ValueError):
            env_writer.update(path, {"API_KEY": 'abc"def'})

    def test_an_ordinary_value_round_trips(self) -> None:
        from helpers import env_writer

        path = self._env_path()
        env_writer.update(path, {"API_KEY": "sk-abc123"})
        self.assertEqual(env_writer.read(path), {"API_KEY": "sk-abc123"})


class TestConfigWriterQuoting(unittest.TestCase):
    def test_control_characters_are_escaped_not_left_raw(self) -> None:
        from helpers.config_writer import format_value

        rendered = format_value("line one\rline two")
        self.assertNotIn("\r", rendered)
        self.assertIn("\\r", rendered)

    def test_a_literal_backslash_and_quote_round_trip(self) -> None:
        import json

        from helpers.config_writer import format_value

        rendered = format_value('a "quoted" path\\here')
        self.assertEqual(json.loads(rendered), 'a "quoted" path\\here')

    def test_a_plain_word_stays_unquoted(self) -> None:
        from helpers.config_writer import format_value

        self.assertEqual(format_value("Wony"), "Wony")

    def test_an_emoji_and_the_line_breaks_yaml_knows_read_back_unchanged(self) -> None:
        """json's default writes an emoji as a \\ud83c\\udf80 pair, which YAML reads
        as two broken characters; U+2028 and U+0085 are line breaks to YAML even
        inside quotes."""
        import yaml

        from helpers.config_writer import format_value

        for text in ("soft \U0001F380 and ł", "one" + chr(0x2028) + "two" + chr(0x85) + "three", "a: \U0001F380"):
            with self.subTest(text=ascii(text)):
                self.assertEqual(yaml.safe_load("key: " + format_value(text))["key"], text)


_FOLDED = """\
assistant:
  name: "Wony"
  personality: >-
    **Role**: You are a calm assistant.
    **Tone**: Soft-spoken, with "quotes" & colons: like this.

    A second paragraph.
  # kept: the comment above the next key
  owner_name: "Tuta"

ai:
  provider: 'gemini'
"""


class TestBlockScalars(unittest.TestCase):
    """A personality written as a `>-` block is how people hand-edit it. Setup
    replaced only the `personality: >-` line and left the text under it behind,
    which is no longer YAML: the next start failed on `**Role**`."""

    def _path(self, text: str) -> str:
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8", newline="\n")
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def _load(self, path: str) -> dict:
        import yaml

        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_replacing_a_folded_value_replaces_its_text_lines_too(self) -> None:
        from helpers import config_writer

        path = self._path(_FOLDED)
        config_writer.update(path, {"assistant.personality": "Be brief & kind."})

        data = self._load(path)
        self.assertEqual(data["assistant"]["personality"], "Be brief & kind.")
        self.assertEqual(data["assistant"]["owner_name"], "Tuta")
        self.assertEqual(data["ai"]["provider"], "gemini")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("**Role**", text)
        self.assertIn("# kept: the comment above the next key", text)

    def test_a_literal_block_is_replaced_the_same_way(self) -> None:
        from helpers import config_writer

        path = self._path(_FOLDED.replace(">-", "|"))
        config_writer.update(path, {"assistant.personality": "Short."})

        self.assertEqual(self._load(path)["assistant"]["personality"], "Short.")

    def test_removing_a_folded_value_removes_its_text_lines_too(self) -> None:
        from helpers import config_writer

        path = self._path(_FOLDED)
        config_writer.remove(path, ["assistant.personality"])

        data = self._load(path)
        self.assertNotIn("personality", data["assistant"])
        self.assertEqual(data["assistant"]["name"], "Wony")

    def test_text_that_only_looks_like_a_key_is_not_one(self) -> None:
        from helpers import config_writer

        path = self._path(_FOLDED)
        config_writer.update(path, {"assistant.Role": "x"})

        data = self._load(path)
        self.assertEqual(data["assistant"]["Role"], "x")
        self.assertIn("**Role**", data["assistant"]["personality"])

    def test_an_edit_that_would_break_the_file_is_refused_and_changes_nothing(self) -> None:
        from helpers import config_writer

        path = self._path(_FOLDED)

        def wreck(lines, key, value):
            lines.append("  *not: valid\n")

        with mock.patch("helpers.config_writer.set_value", side_effect=wreck):
            with self.assertRaises(ValueError):
                config_writer.update(path, {"assistant.name": "x"})

        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), _FOLDED)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
