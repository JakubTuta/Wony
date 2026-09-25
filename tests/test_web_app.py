"""The web UI trusts three shapes from this API: `confirms` on every job (so it
can render "Always confirms" / "Confirms on: …" without a hardcoded list),
`needs_confirm` surviving the JSON round-trip on a blocked tool call (so a
reloaded chat still shows the inline confirm card), and `/api/pins` rejecting
a pin that names a job that does not exist (the endpoint has no other
allowlist).

Run directly: python tests/test_web_app.py
"""
import json
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

    return TestClient(build_app())


class TestJobsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()

    def test_confirms_is_bool_or_string_list(self) -> None:
        jobs = self.client.get("/api/jobs").json()["jobs"]
        self.assertTrue(jobs)
        for job in jobs:
            with self.subTest(job=job["name"]):
                confirms = job["confirms"]
                if isinstance(confirms, bool):
                    continue
                self.assertIsInstance(confirms, list)
                self.assertTrue(all(isinstance(g, str) for g in confirms))

    def test_a_gated_job_reports_its_gate_words(self) -> None:
        # background_jobs lives in `employer`, one of the always-on modules
        # (helpers.config.ALWAYS_ON) — unlike a switchable module, it is
        # guaranteed to be registered no matter which config another test in
        # this same process loaded before `import modules` first ran.
        jobs = {job["name"]: job for job in self.client.get("/api/jobs").json()["jobs"]}
        self.assertEqual(jobs["background_jobs"]["confirms"], ["cancel", "stop", "stop all"])


class TestSanitizeCalls(unittest.TestCase):
    def test_needs_confirm_survives_sanitization(self) -> None:
        from helpers.web_app import _sanitize_calls

        calls = [
            {"name": "note", "args": {"action": "clear"}, "result": "ask", "needs_confirm": True},
            {"name": "note", "args": {"action": "add"}, "result": "done"},
        ]
        safe = _sanitize_calls(calls)
        self.assertTrue(safe[0]["needs_confirm"])
        self.assertNotIn("needs_confirm", safe[1])

    def test_needs_confirm_round_trips_through_json(self) -> None:
        from helpers.web_app import _sanitize_calls

        safe = _sanitize_calls(
            [{"name": "note", "args": {}, "result": "ask", "needs_confirm": True}]
        )
        reloaded = json.loads(json.dumps(safe))
        self.assertTrue(reloaded[0]["needs_confirm"])


class TestPinsEndpoint(unittest.TestCase):
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

    def test_unknown_job_is_refused(self) -> None:
        resp = self.client.post(
            "/api/pins",
            json={"pins": [{
                "id": "1", "kind": "run", "job": "definitely_not_a_job",
                "title": "x", "args": {},
            }]},
        )
        self.assertEqual(resp.status_code, 422)

    def test_valid_pins_round_trip(self) -> None:
        # system_status lives in the always-on `status` module, so it is
        # guaranteed registered regardless of which config another test in
        # this process loaded before `import modules` first ran.
        pins = [{
            "id": "1", "kind": "run", "job": "system_status", "module": "status", "title": "Status", "args": {},
        }]
        saved = self.client.post("/api/pins", json={"pins": pins})
        self.assertEqual(saved.status_code, 200)
        fetched = self.client.get("/api/pins").json()["pins"]
        self.assertEqual(fetched, pins)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
