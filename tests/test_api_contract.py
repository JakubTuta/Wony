"""The routes both the PC web page and the wall panel call, and the shapes each
depends on. This file is the same on both branches: a change to a shared route
changes it here, and then on the other branch too.

Run directly: python tests/test_api_contract.py
"""
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _load_app():
    from fastapi.testclient import TestClient

    from helpers.config import Config

    Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
    import modules  # noqa: F401  (import triggers discover_services)
    from helpers.web_app import build_app

    return TestClient(build_app(), base_url="http://127.0.0.1:8123")


class TestJobsContract(unittest.TestCase):
    """/api/jobs hands the UI what it needs to run its own confirm dialog:
    `confirms` says whether the job is gated at all, and `confirm_words` narrows
    that to the `action` values that ask (null: every call asks)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()
        cls.jobs = {job["name"]: job for job in cls.client.get("/api/jobs").json()["jobs"]}

    def test_every_job_has_the_same_fields(self) -> None:
        self.assertTrue(self.jobs)
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                for field in ("name", "module", "summary", "description", "parameters"):
                    self.assertIn(field, job)
                self.assertIsInstance(job["confirms"], bool)
                words = job["confirm_words"]
                if words is not None:
                    self.assertTrue(job["confirms"])
                    self.assertIsInstance(words, list)
                    self.assertTrue(all(isinstance(word, str) for word in words))

    def test_a_job_with_gate_words_lists_them(self) -> None:
        # background_jobs lives in `employer`, one of the always-on modules
        # (helpers.config.ALWAYS_ON) — guaranteed registered whichever config
        # another test in this process loaded first.
        job = self.jobs["background_jobs"]
        self.assertTrue(job["confirms"])
        self.assertEqual(job["confirm_words"], ["stop"])

    def test_a_job_that_always_confirms_has_no_word_list(self) -> None:
        job = self.jobs["exit"]
        self.assertTrue(job["confirms"])
        self.assertIsNone(job["confirm_words"])

    def test_a_job_with_no_gate_does_not_confirm(self) -> None:
        job = self.jobs["get_datetime"]
        self.assertFalse(job["confirms"])
        self.assertIsNone(job["confirm_words"])


class TestNotificationsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import helpers.memory_db as db

        cls.db = db
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(cls._tmpdir.name, "test.db")
        cls.client = _load_app()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.db._DB_FILE = cls._real_db_file
        cls._tmpdir.cleanup()

    def setUp(self) -> None:
        self.client.post("/api/notifications/ack-all")

    def _unread(self) -> list:
        return self.client.get("/api/notifications").json()["notifications"]

    def test_one_notification_is_acknowledged_by_its_id(self) -> None:
        first = self.db.insert_notification("Timer done", kind="reminder")
        second = self.db.insert_notification("New mail", kind="info")

        resp = self.client.post(f"/api/notifications/{first['id']}/ack")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "acknowledged"})
        self.assertEqual([n["id"] for n in self._unread()], [second["id"]])

    def test_acknowledging_one_that_does_not_exist_is_a_404(self) -> None:
        resp = self.client.post("/api/notifications/999999/ack")
        self.assertEqual(resp.status_code, 404)

    def test_all_can_be_acknowledged_at_once(self) -> None:
        self.db.insert_notification("One")
        self.db.insert_notification("Two")

        resp = self.client.post("/api/notifications/ack-all")

        self.assertEqual(resp.json(), {"cleared": 2})
        self.assertEqual(self._unread(), [])

    def test_acknowledged_ones_are_listed_only_when_asked_for(self) -> None:
        made = self.db.insert_notification("Done already")
        self.client.post(f"/api/notifications/{made['id']}/ack")

        self.assertEqual(self._unread(), [])
        everything = self.client.get("/api/notifications?include_acknowledged=true").json()["notifications"]
        self.assertIn(made["id"], [n["id"] for n in everything])


class TestConfirmButton(unittest.TestCase):
    """The chat's Confirm button runs a call the model asked about. A "yes"
    typed afterwards used to run it a second time, and the history still said
    NOT DONE."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()

    def test_the_click_spends_the_armed_call_and_tells_the_history(self) -> None:
        from unittest import mock

        from helpers import confirm
        from helpers.conversation import Conversation
        from helpers.registry import ServiceRegistry
        from helpers.turn_context import user_request

        sent = []

        def send_note(to: str, body: str = "", cc: str = "") -> str:
            """Sends a note."""
            sent.append(to)
            return f"Sent to {to}."

        args = {"to": "anna", "body": "hi"}
        with mock.patch.dict(ServiceRegistry._jobs, {"send_note": send_note}), \
                mock.patch.dict(ServiceRegistry._job_confirms, {"send_note": True}), \
                mock.patch.object(Conversation, "_turns", []), \
                mock.patch("helpers.conversation._try_persist", return_value=None):
            confirm.begin_turn()
            with user_request("send it"):
                self.assertIsNotNone(confirm.check("send_note", args))
            Conversation.record_turn(
                "send anna a note", "Should I send it?", emit=False,
                calls=[{"name": "send_note", "args": {**args, "cc": ""}, "result": "NOT DONE", "needs_confirm": True}],
            )

            resp = self.client.post("/api/invoke", json={"name": "send_note", "args": args})
            self.assertTrue(resp.json()["ok"])
            self.assertEqual(sent, ["anna"])

            # A later "yes" re-sends the call: it must ask again, not run again.
            confirm.begin_turn()
            with user_request("yes"):
                self.assertIsNotNone(confirm.check("send_note", args))

            turn = Conversation._turns[-1]
            self.assertIn("Sent to anna.", turn["assistant"])
            self.assertNotIn("needs_confirm", turn["calls"][0])
        confirm.reset()


class TestConfirmNormalizesArgs(unittest.TestCase):
    def test_a_blank_or_default_argument_does_not_make_it_ask_again(self) -> None:
        from unittest import mock

        from helpers import confirm
        from helpers.registry import ServiceRegistry
        from helpers.turn_context import user_request

        def mail(to: str, cc: str = "", urgent: bool = False) -> str:
            """Mails."""
            return "ok"

        with mock.patch.dict(ServiceRegistry._jobs, {"mail": mail}), \
                mock.patch.dict(ServiceRegistry._job_confirms, {"mail": True}):
            confirm.begin_turn()
            with user_request("mail anna"):
                self.assertIsNotNone(confirm.check("mail", {"to": "anna"}))
            confirm.begin_turn()
            with user_request("yes"):
                self.assertIsNone(confirm.check("mail", {"to": "anna ", "cc": "", "urgent": False}))
        confirm.reset()


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
