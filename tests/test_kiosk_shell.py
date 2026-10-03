"""After a rebuild the browser must ask again for index.html: a copy served from
disk keeps naming the old hashed bundle, so the screen would look the same until
someone cleared its cache by hand.

Run directly: python tests/test_kiosk_shell.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestShellIsNeverStale(unittest.TestCase):
    def test_the_html_shell_revalidates_every_time(self) -> None:
        from fastapi.testclient import TestClient

        from helpers.config import Config

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
        import modules  # noqa: F401  (import triggers discover_services)
        from helpers.web_app import build_app

        with tempfile.TemporaryDirectory() as dist:
            with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("<!doctype html><title>Wony</title>")
            with mock.patch("helpers.web_app._DIST_DIR", dist):
                client = TestClient(build_app(), base_url="http://127.0.0.1:8123")
            resp = client.get("/some/page")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("cache-control"), "no-cache")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
