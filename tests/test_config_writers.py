"""config_writer hand-edits config.yaml in place to keep comments and key order.
A value with a raw control character could otherwise break out of its quotes
and plant a sibling key.

Run directly: python tests/test_config_writers.py
"""
import json
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestConfigWriterQuoting(unittest.TestCase):
    def test_control_characters_are_escaped_not_left_raw(self) -> None:
        from helpers.config_writer import format_value

        rendered = format_value("line one\rline two")
        self.assertNotIn("\r", rendered)
        self.assertIn("\\r", rendered)

    def test_a_literal_backslash_and_quote_round_trip(self) -> None:
        from helpers.config_writer import format_value

        rendered = format_value('a "quoted" path\\here')
        self.assertEqual(json.loads(rendered), 'a "quoted" path\\here')

    def test_a_plain_word_stays_unquoted(self) -> None:
        from helpers.config_writer import format_value

        self.assertEqual(format_value("Wony"), "Wony")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
