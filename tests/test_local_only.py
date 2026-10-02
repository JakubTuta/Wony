"""Browsers do not apply CORS to WebSockets, so before this any website open on
a machine that could reach the panel could open /api/ws, read every turn and
send chat messages — or post to the password-less API.

Run directly: python tests/test_local_only.py
"""
import os
import sys
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _scope(host: str, origin: str = "") -> dict:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return {"type": "websocket", "headers": headers}


class TestLocalOnly(unittest.TestCase):
    def _allowed(self, scope: dict, configured: str = "127.0.0.1") -> bool:
        from helpers.web_app import _allowed

        with mock.patch("helpers.config.Config.get", side_effect=lambda k, d=None: configured if k == "server.host" else d):
            return _allowed(scope)

    def test_the_panels_own_page_is_allowed(self) -> None:
        self.assertTrue(self._allowed(_scope("localhost:8000", "http://localhost:8000")))

    def test_another_website_is_refused(self) -> None:
        self.assertFalse(self._allowed(_scope("localhost:8000", "https://evil.example")))

    def test_a_rebound_host_name_is_refused(self) -> None:
        self.assertFalse(self._allowed(_scope("evil.example:8000", "http://evil.example:8000")))

    def test_a_screen_on_another_machine_still_works(self) -> None:
        self.assertTrue(self._allowed(_scope("192.168.1.20:8000", "http://192.168.1.20:8000"), "192.168.1.20"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
