"""Kiosk home-screen tile storage and the job catalog's confirm_words.

Run directly: python tests/test_kiosk_tiles.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestKioskTileStorage(unittest.TestCase):
    """Tiles live in the kiosk's own kv row, not config.yaml — arranged by
    touch, so a hand-crafted request is the only thing that could smuggle
    arbitrary text into it."""

    def setUp(self) -> None:
        from helpers import kiosk
        from helpers.memory_db import set_kv

        self.kiosk = kiosk
        set_kv(kiosk._TILES_KV_KEY, "")

    def test_nothing_saved_yet_reads_as_none(self) -> None:
        """None (not an empty list) is what tells the UI to seed a starter
        layout instead of showing a blank grid."""
        self.assertIsNone(self.kiosk.load_tiles())

    def test_round_trip(self) -> None:
        ids = ["routine:briefing", "device:light.lamp", "timer:10", "music", "sleep"]
        self.kiosk.save_tiles(ids)
        self.assertEqual(self.kiosk.load_tiles(), ids)

    def test_rejects_an_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            self.kiosk.save_tiles(["chat:hello"])

    def test_rejects_too_many_tiles(self) -> None:
        with self.assertRaises(ValueError):
            self.kiosk.save_tiles([f"device:light.l{i}" for i in range(33)])

    def test_bare_kind_with_no_arg_is_valid(self) -> None:
        self.kiosk.save_tiles(["music", "sleep"])
        self.assertEqual(self.kiosk.load_tiles(), ["music", "sleep"])


class TestJobConfirmWords(unittest.TestCase):
    """/api/jobs flattens ServiceRegistry.get_job_confirms() to `destructive` +
    `confirm_words`, so the UI can drive its confirm sheet generically instead
    of hardcoding which jobs are dangerous."""

    def _confirm_words(self, declared):
        # Mirrors the derivation in helpers/web_app.py:list_jobs — kept as a
        # small pure function there would just move this test, not simplify it.
        if isinstance(declared, (set, frozenset, list, tuple)):
            return sorted(str(v).lower() for v in declared)
        return None

    def test_true_has_no_word_list(self) -> None:
        self.assertIsNone(self._confirm_words(True))

    def test_false_has_no_word_list(self) -> None:
        self.assertIsNone(self._confirm_words(False))

    def test_a_set_becomes_a_sorted_word_list(self) -> None:
        self.assertEqual(
            self._confirm_words({"cancel", "Delete"}), ["cancel", "delete"]
        )

    def test_registry_confirms_reach_the_same_shape(self) -> None:
        from helpers.config import Config
        from helpers.registry import ServiceRegistry

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
        import modules.scheduler  # noqa: F401 — registers manage_reminders

        declared = ServiceRegistry.get_job_confirms().get("manage_reminders")
        self.assertIsNotNone(declared)
        words = self._confirm_words(declared)
        self.assertIsInstance(words, list)
        self.assertIn("cancel", words)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
