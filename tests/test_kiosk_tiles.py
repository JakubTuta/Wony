"""Kiosk home-screen tile storage.

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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
