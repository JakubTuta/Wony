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

    return TestClient(build_app(), base_url="http://127.0.0.1:8123")


class TestLocalOnly(unittest.TestCase):
    """Browsers do not apply CORS to WebSockets, so before this any website the
    user visited could open /api/ws, read every turn and send chat messages."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()

    def test_cross_site_websocket_is_refused(self) -> None:
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "ws://127.0.0.1:8123/api/ws", headers={"Origin": "https://evil.example"}
            ) as ws:
                ws.receive_text()

    def test_same_origin_websocket_is_accepted(self) -> None:
        with self.client.websocket_connect(
            "ws://127.0.0.1:8123/api/ws", headers={"Origin": "http://127.0.0.1:8123"}
        ) as ws:
            ws.send_text("{}")

    def test_cross_site_post_is_refused(self) -> None:
        resp = self.client.post(
            "/api/chat/clear", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_rebound_host_is_refused(self) -> None:
        resp = self.client.get("/api/jobs", headers={"Host": "evil.example:8123"})
        self.assertEqual(resp.status_code, 403)

    def test_cross_site_fetch_metadata_is_refused_even_with_no_origin(self) -> None:
        # A same-origin Origin header plus a cross-site Sec-Fetch-Site should
        # not happen from a real browser, but the second check must still
        # hold on its own — it is not there to agree with the first.
        resp = self.client.get("/api/jobs", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.status_code, 403)

    def test_same_site_fetch_metadata_is_refused(self) -> None:
        resp = self.client.get("/api/jobs", headers={"Sec-Fetch-Site": "same-site"})
        self.assertEqual(resp.status_code, 403)

    def test_same_origin_fetch_metadata_is_accepted(self) -> None:
        resp = self.client.get("/api/jobs", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(resp.status_code, 200)

    def test_no_docs_or_openapi_schema_is_served(self) -> None:
        # Unregistering docs_url/redoc_url/openapi_url (not a 404: the SPA
        # catch-all serves index.html for any unmatched path, same as it
        # would for a typo'd URL) is what matters — no route here may return
        # the OpenAPI schema or the Swagger/ReDoc UI.
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertNotEqual(resp.headers.get("content-type", ""), "application/json")
                self.assertNotIn("swagger-ui", resp.text.lower())
                self.assertNotIn("redoc", resp.text.lower())


class TestAllowedOrigin(unittest.TestCase):
    def test_rules(self) -> None:
        from helpers.server_address import allowed_origin

        self.assertTrue(allowed_origin(None, "127.0.0.1:9000"))
        self.assertTrue(allowed_origin("http://127.0.0.1:9000", "127.0.0.1:9000"))
        self.assertFalse(allowed_origin("http://localhost:5173", "127.0.0.1:9000"))
        self.assertFalse(allowed_origin("http://127.0.0.1:9001", "127.0.0.1:9000"))
        self.assertFalse(allowed_origin("http://evil.example:9000", "127.0.0.1:9000"))
        self.assertFalse(allowed_origin("null", "127.0.0.1:9000"))


class TestRestartEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()

    def test_a_server_without_a_tray_says_it_cannot_restart(self) -> None:
        from unittest import mock

        with mock.patch("helpers.restart._handler", None):
            self.assertFalse(self.client.get("/api/config").json()["can_restart"])
            self.assertEqual(self.client.post("/api/restart").status_code, 409)

    def test_a_registered_handler_is_offered_and_run(self) -> None:
        import threading
        from unittest import mock

        ran = threading.Event()
        with mock.patch("helpers.restart._handler", ran.set), \
                mock.patch("helpers.restart.time.sleep"):
            self.assertTrue(self.client.get("/api/config").json()["can_restart"])
            self.assertEqual(self.client.post("/api/restart").status_code, 200)
            self.assertTrue(ran.wait(2))


class TestCapabilitiesEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _load_app()

    def test_every_capability_has_an_example_and_working_available_are_disjoint(self) -> None:
        caps = self.client.get("/api/capabilities").json()
        self.assertTrue(caps["working"] or caps["available"])
        working_keys = {c["key"] for c in caps["working"]}
        available_keys = {c["key"] for c in caps["available"]}
        self.assertEqual(working_keys & available_keys, set())
        for cap in caps["working"] + caps["available"]:
            with self.subTest(key=cap["key"]):
                self.assertTrue(cap["example"], f"{cap['key']} has no example")


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
        from helpers.conversation import sanitize_calls

        calls = [
            {"name": "note", "args": {"action": "clear"}, "result": "ask", "needs_confirm": True},
            {"name": "note", "args": {"action": "add"}, "result": "done"},
        ]
        safe = sanitize_calls(calls)
        self.assertTrue(safe[0]["needs_confirm"])
        self.assertNotIn("needs_confirm", safe[1])

    def test_needs_confirm_round_trips_through_json(self) -> None:
        from helpers.conversation import sanitize_calls

        safe = sanitize_calls(
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
