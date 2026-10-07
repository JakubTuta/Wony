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

    def test_search_treats_metacharacters_as_words(self) -> None:
        """FTS5 operators in a spoken phrase must match text, not change the
        query — 'flight AND hotel' is a thing a user says, not an operator."""
        self.db.insert_turn("book the flight and hotel", "ok")
        self.assertTrue(self.db.search_turns("flight AND hotel"))
        self.assertTrue(self.db.search_turns("hotel"))
        self.assertFalse(self.db.search_turns("submarine"))

    def test_recent_turns_ordered_within_one_second(self) -> None:
        """Timestamps are second-resolution, so ordering must key on the
        autoincrement id or a fast burst comes back shuffled."""
        for i in range(5):
            self.db.insert_turn(f"turn {i}", "ok")
        recent = self.db.recent_turns(10)
        self.assertEqual([t["user_text"] for t in recent], [f"turn {i}" for i in range(5)])

    def test_embedding_upsert_replaces_in_place(self) -> None:
        """The unique indexes are partial, and SQLite only matches an
        ON CONFLICT target to a partial index when the WHERE clause is
        repeated — without it every semantic write raised and was swallowed."""
        self.db.upsert_embedding("fact", None, "boss", "boss: Anna", b"\x01" * 4)
        self.db.upsert_embedding("fact", None, "boss", "boss: Bea", b"\x02" * 4)
        self.db.upsert_embedding("turn", 7, None, "a turn", b"\x03" * 4)
        self.db.upsert_embedding("turn", 7, None, "same turn again", b"\x04" * 4)

        rows = {r["ref_key"] or r["ref_id"]: r["text"] for r in self.db.all_embeddings()}
        self.assertEqual(rows, {"boss": "boss: Bea", 7: "same turn again"})

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

    def test_prompt_keeps_stated_and_newest_facts_not_the_first_letters(self) -> None:
        """The prompt used to take the first 40 facts by name, so the learner's
        'writing_style' and anything else late in the alphabet silently fell out."""
        from helpers import profile

        conn = self.db._get_conn()
        for i in range(45):
            self.db.set_fact(f"a_{i:02d}", "old guess", source="auto")
        self.db.set_fact("writing_style", "short and friendly", source="auto")
        self.db.set_fact("zoo_pass", "the user has a zoo pass")
        conn.execute("UPDATE facts SET ts = '2026-01-01T00:00:00' WHERE key LIKE 'a_%'")
        conn.execute("UPDATE facts SET ts = '2026-10-01T00:00:00' WHERE key = 'writing_style'")
        conn.execute("UPDATE facts SET ts = '2025-01-01T00:00:00' WHERE key = 'zoo_pass'")
        conn.commit()

        text = profile.Profile.as_text()
        self.assertIn("zoo pass", text)
        self.assertIn("writing style", text)
        self.assertEqual(text.count("old guess"), profile._MAX_PROMPT_FACTS - 2)

    def test_a_fact_left_out_of_the_prompt_comes_back_when_asked_about(self) -> None:
        from unittest import mock

        from helpers import profile

        for i in range(profile._MAX_PROMPT_FACTS):
            self.db.set_fact(f"pref_{i:02d}", "likes tea")
        self.db.set_fact("dentist", "the dentist is Dr Nowak on Main Street", source="auto")
        conn = self.db._get_conn()
        conn.execute("UPDATE facts SET ts = '2020-01-01T00:00:00' WHERE key = 'dentist'")
        conn.commit()

        with mock.patch("helpers.semantic.ready", return_value=False), \
                mock.patch("helpers.semantic.warm"):
            self.assertNotIn("Nowak", profile.Profile.as_text())
            self.assertIn("Nowak", profile.Profile.relevant("when is my dentist appointment"))
            self.assertEqual(profile.Profile.relevant("play some jazz"), "")

    def test_wipe_clears_everything(self) -> None:
        self.db.insert_turn("a", "b")
        self.db.set_fact("k", "v")
        self.db.wipe_all()
        self.assertEqual(self.db.recent_turns(10), [])
        self.assertEqual(self.db.all_facts(), {})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
