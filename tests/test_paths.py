"""Data files must resolve against the repo, not the process CWD.

The tray is launched by Task Scheduler and `wony.py text` can be started from
anywhere; a CWD-relative default silently creates a second wony.db / cache.json
next to wherever the process happened to start.

Run directly: python tests/test_paths.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestPaths(unittest.TestCase):
    def _assert_in_repo(self, path: str, label: str) -> None:
        self.assertTrue(os.path.isabs(path), f"{label} is not absolute: {path}")
        self.assertEqual(
            os.path.normcase(os.path.dirname(os.path.abspath(path))).rstrip("\\/"),
            os.path.normcase(os.path.abspath(_REPO_ROOT)).rstrip("\\/"),
            f"{label} does not live in the repo root: {path}",
        )

    def test_repo_root_is_the_project_dir(self) -> None:
        from helpers.paths import REPO_ROOT

        self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, "wony.py")))

    def test_resolve_leaves_absolute_paths_alone(self) -> None:
        from helpers.paths import resolve

        absolute = os.path.abspath(os.sep + "somewhere" + os.sep + "models.onnx")
        self.assertEqual(resolve(absolute), absolute)

    def test_database_is_repo_anchored(self) -> None:
        import helpers.memory_db as db

        self._assert_in_repo(db._DB_FILE, "wony.db")

    def test_cache_is_repo_anchored(self) -> None:
        from helpers.cache import Cache

        self._assert_in_repo(Cache._filename, "cache.json")

    def test_credentials_are_repo_anchored(self) -> None:
        import helpers.accounts as accounts

        self.assertTrue(os.path.isabs(accounts._ACCOUNTS_FILE))
        self.assertTrue(
            os.path.abspath(accounts._ACCOUNTS_FILE).startswith(
                os.path.abspath(_REPO_ROOT)
            ),
            f"accounts.json escapes the repo: {accounts._ACCOUNTS_FILE}",
        )

    def test_audio_flag_is_process_state(self) -> None:
        """Muting must not be written to disk — `wony.py doctor` used to flip a
        running tray to silent through the shared cache file."""
        from helpers.cache import Cache

        before = Cache.get_audio()
        persisted = dict(Cache.get_values())
        try:
            Cache.set_audio(True)
            self.assertTrue(Cache.get_audio())
            Cache.set_audio(False)
            self.assertFalse(Cache.get_audio())
            # Toggling must not touch the persisted store at all.
            self.assertEqual(Cache.get_values(), persisted)
        finally:
            Cache.set_audio(before)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
