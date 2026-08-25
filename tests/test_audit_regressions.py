"""Guards for behaviours that were silently wrong before.

Each case here is a bug that shipped and looked fine from the outside: a config
file that was never read, a document that was indexed but only searchable by its
first page, pollers that disappeared when the assistant was paused, an MCP tool
that could take over a built-in job's name.

Run directly: python tests/test_audit_regressions.py
"""
import os
import sys
import tempfile
import threading
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestConfigIsRepoAnchored(unittest.TestCase):
    def test_config_found_from_any_working_directory(self) -> None:
        """The tray is started by Task Scheduler from an arbitrary directory,
        and `wony.py text` can be run from anywhere. Resolving config.yaml
        against the CWD meant both silently fell through to defaults."""
        from helpers.config import _resolve_yaml_path

        original = os.getcwd()
        with tempfile.TemporaryDirectory() as elsewhere:
            try:
                os.chdir(elsewhere)
                resolved = _resolve_yaml_path("config.example.yaml")
            finally:
                os.chdir(original)

        self.assertIsNotNone(resolved)
        self.assertEqual(
            os.path.normcase(os.path.dirname(os.path.abspath(resolved))),
            os.path.normcase(_REPO_ROOT),
        )


class TestSemanticChunking(unittest.TestCase):
    def test_long_document_becomes_many_chunks(self) -> None:
        """A whole document in one embedding row is searchable by its opening
        paragraph and nothing else — the model truncates the rest."""
        from helpers.semantic import _CHUNK_CHARS, chunk_text

        text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(40))
        chunks = chunk_text(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= _CHUNK_CHARS for c in chunks))
        # The tail must survive: it is what "index a 50-page PDF" is asking for.
        self.assertIn("Paragraph 39", chunks[-1])

    def test_short_document_is_one_chunk(self) -> None:
        from helpers.semantic import chunk_text

        self.assertEqual(chunk_text("just a note"), ["just a note"])
        self.assertEqual(chunk_text("   "), [])


class TestBackgroundJobSuspend(unittest.TestCase):
    def setUp(self) -> None:
        from helpers.jobs import BackgroundJobs

        self.jobs = BackgroundJobs
        self.jobs.stop_all()

    def tearDown(self) -> None:
        self.jobs.stop_all()

    def test_suspended_jobs_come_back_on_resume(self) -> None:
        """Pausing the assistant used to call stop_all(), which permanently
        dropped every poller the user had asked for."""
        ran = threading.Event()

        self.assertTrue(self.jobs.start("poller", ran.set, interval=0.05))
        self.assertTrue(ran.wait(2.0))

        self.assertEqual(self.jobs.suspend_all(), ["poller"])
        self.assertEqual(self.jobs.list_jobs(), [])

        ran.clear()
        self.assertEqual(self.jobs.resume_suspended(), ["poller"])
        self.assertTrue(ran.wait(2.0))

    def test_stop_all_is_permanent(self) -> None:
        self.jobs.start("poller", lambda: None, interval=60)
        self.jobs.stop_all()
        self.assertEqual(self.jobs.resume_suspended(), [])


class TestMcpToolNaming(unittest.TestCase):
    def test_tool_cannot_shadow_a_builtin_job(self) -> None:
        """An external server naming a tool `exit` would otherwise replace the
        built-in job — and disconnecting the server would delete it."""
        from helpers.mcp_client import _job_name_for

        taken = {"exit": "", "send_email": "gmail"}
        self.assertEqual(_job_name_for("srv", "exit", taken), "srv_exit")
        self.assertEqual(_job_name_for("srv", "send_email", taken), "srv_send_email")

    def test_own_tools_keep_their_name_across_reconnects(self) -> None:
        from helpers.mcp_client import _job_name_for

        taken = {"search": "mcp:srv"}
        self.assertEqual(_job_name_for("srv", "search", taken), "search")

    def test_provider_illegal_characters_are_stripped(self) -> None:
        """Providers reject tool names outside [A-Za-z0-9_-]."""
        from helpers.mcp_client import _job_name_for

        self.assertEqual(_job_name_for("srv", "read file!", {}), "read_file_")


class TestWeatherUnits(unittest.TestCase):
    def test_configured_units_reach_the_request(self) -> None:
        """modules.weather.default_units was documented as metric|imperial but
        the job hardcoded metric and a °C suffix."""
        from helpers.config import Config
        from modules import weather

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
        assert Config._settings is not None
        original = Config._settings.modules.weather.default_units
        try:
            for configured, expected_units, expected_symbol in [
                ("metric", "metric", "°C"),
                ("imperial", "imperial", "°F"),
                ("nonsense", "metric", "°C"),
            ]:
                Config._settings.modules.weather.default_units = configured
                with self.subTest(configured=configured):
                    self.assertEqual(weather.units(), expected_units)
                    self.assertEqual(weather.temperature_symbol(), expected_symbol)
        finally:
            Config._settings.modules.weather.default_units = original


class TestImageMimeMatchesEncoding(unittest.TestCase):
    def test_declared_mime_matches_the_bytes_we_send(self) -> None:
        """Screenshots are PNG; declaring image/jpeg is rejected by Anthropic
        and mis-sniffed by Gemini."""
        import base64

        import numpy as np

        from helpers.tools import IMAGE_MIME_TYPE, numpy_image_to_base64_bytes

        encoded = numpy_image_to_base64_bytes(np.zeros((4, 4, 3), dtype=np.uint8))
        self.assertIsNotNone(encoded)
        self.assertEqual(IMAGE_MIME_TYPE, "image/png")
        self.assertTrue(base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
