"""Round-trips through the SQLite store, against a throwaway database file.

Run directly: python tests/test_memory_db.py
"""
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestMemoryDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import helpers.memory_db as db

        cls.db = db
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(cls._tmpdir.name, "test.db")

    @classmethod
    def tearDownClass(cls) -> None:
        # Restore the real path — _DB_FILE is module state other tests read.
        cls.db.close()
        cls.db._DB_FILE = cls._real_db_file
        cls._tmpdir.cleanup()

    def setUp(self) -> None:
        self.db.wipe_all()

    def test_turn_roundtrip(self) -> None:
        turn_id = self.db.insert_turn("hello there", "hi back", calls=[{"name": "x"}])
        self.assertIsNotNone(turn_id)

        recent = self.db.recent_turns(10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["user_text"], "hello there")
        self.assertEqual(recent[0]["assistant_text"], "hi back")
        self.assertEqual(recent[0]["calls"], [{"name": "x"}])

    def test_search_finds_inserted_turn(self) -> None:
        self.db.insert_turn("remind me about the dentist", "noted")
        self.assertTrue(self.db.search_turns("dentist"))

    def test_search_survives_fts_metacharacters(self) -> None:
        """A raw user phrase reaches MATCH; FTS5 syntax must not blow up the
        query — it falls back to LIKE instead of raising."""
        self.db.insert_turn("cost is 50% \"all in\"", "ok")
        for needle in ('"', "AND", "*", "col:", "NEAR(", "^x"):
            with self.subTest(needle=needle):
                self.assertIsInstance(self.db.search_turns(needle), list)

    def test_facts_roundtrip_and_overwrite(self) -> None:
        self.db.set_fact("preferred_units", "metric")
        self.assertEqual(self.db.get_fact("preferred_units"), "metric")

        # Same key must update, not duplicate — this is what the `topic`
        # argument on the remember job exists to make possible.
        self.db.set_fact("preferred_units", "imperial")
        self.assertEqual(self.db.get_fact("preferred_units"), "imperial")
        self.assertEqual(len(self.db.all_facts()), 1)

        self.assertTrue(self.db.remove_fact("preferred_units"))
        self.assertFalse(self.db.remove_fact("preferred_units"))

    def test_wipe_clears_everything(self) -> None:
        self.db.insert_turn("a", "b")
        self.db.set_fact("k", "v")
        self.db.wipe_all()
        self.assertEqual(self.db.recent_turns(10), [])
        self.assertEqual(self.db.all_facts(), {})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
