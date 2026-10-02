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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
