"""Logs are plain text files kept on disk indefinitely — a stray API key or
query-string token written into one sits there until the user thinks to look.
8 log files on a real install carried OpenWeatherMap's `appid=` before this.

Run directly: python tests/test_logger_redaction.py
"""
import os
import sys
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestRedact(unittest.TestCase):
    def test_a_query_param_that_commonly_carries_a_key_is_redacted(self) -> None:
        from helpers.logger import _redact

        for param in ("appid", "key", "token"):
            with self.subTest(param=param):
                text = f"GET https://example.com/x?{param}=abc123&other=1 failed"
                self.assertNotIn("abc123", _redact(text))
                self.assertIn(f"{param}=[REDACTED]", _redact(text))

    def test_a_configured_secrets_live_value_is_redacted_wherever_it_appears(self) -> None:
        from helpers.logger import _redact

        with mock.patch("helpers.settings.secret_env_keys", return_value=["FAKE_API_KEY"]), \
                mock.patch.dict(os.environ, {"FAKE_API_KEY": "sk-super-secret-value"}):
            text = "request to provider failed: bearer sk-super-secret-value rejected"
            self.assertNotIn("sk-super-secret-value", _redact(text))

    def test_log_error_and_log_function_call_both_redact(self) -> None:
        from helpers.logger import Logger

        log = Logger()
        with mock.patch.object(log, "logger") as inner, \
                mock.patch.object(log, "_log_csv") as csv_log:
            log.log_error("fetch failed: https://x.example/?appid=abcd1234")
            logged = inner.error.call_args[0][0]
            self.assertNotIn("abcd1234", logged)

            log.log_function_call("get_weather", "", {"url": "https://x.example/?key=zzz999"})
            logged = inner.info.call_args[0][0]
            self.assertNotIn("zzz999", logged)
        self.assertTrue(csv_log.called)

    def test_text_with_nothing_sensitive_is_unchanged(self) -> None:
        from helpers.logger import _redact

        self.assertEqual(_redact("hello world"), "hello world")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
