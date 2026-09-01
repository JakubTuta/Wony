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
        """systemd starts the kiosk from an arbitrary directory, and
        `wony.py text` can be run from anywhere. Resolving config.yaml
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


class TestKioskManifests(unittest.TestCase):
    def test_every_default_entry_names_a_real_job(self) -> None:
        """Three of the first eight tiles named jobs that did not exist
        (get_weather, check_emails, pause_song). Nothing caught it until the
        endpoint was called by hand — a tile that runs nothing looks exactly
        like a tile whose module is off."""
        from helpers.kiosk import _AMBIENT_CARDS, _DEFAULT_TILES
        from helpers.registry import ServiceRegistry

        # Import every module that owns a default entry so its jobs register.
        # Some will not import (missing optional packages) — those are skipped
        # rather than failed, which is the same thing CI does.
        wanted = {t["module"] for t in _DEFAULT_TILES}
        wanted |= {c["module"] for c in _AMBIENT_CARDS}

        importable = set()
        for module_name in sorted(wanted):
            try:
                __import__(f"modules.{module_name}")
                importable.add(module_name)
            except Exception:
                pass

        registered = ServiceRegistry.get_all_jobs()
        entries = [(t["module"], t["job"]) for t in _DEFAULT_TILES if t["kind"] == "job"]
        entries += [(c["module"], c["job"]) for c in _AMBIENT_CARDS]

        checked = 0
        for module_name, job_name in entries:
            if module_name not in importable:
                continue
            with self.subTest(module=module_name, job=job_name):
                self.assertIn(
                    job_name,
                    registered,
                    f"{module_name} declares a tile/card for '{job_name}', "
                    f"which is not a registered job.",
                )
            checked += 1

        # If nothing was importable the assertions above all passed vacuously.
        self.assertGreater(checked, 0, "No default entries could be checked at all.")

    def test_prompt_tiles_carry_a_prompt(self) -> None:
        """A prompt tile with no prompt sends an empty message to the agent."""
        from helpers.kiosk import _DEFAULT_TILES

        for tile in _DEFAULT_TILES:
            if tile["kind"] == "prompt":
                with self.subTest(tile=tile["id"]):
                    self.assertTrue((tile.get("prompt") or "").strip())

    def test_screen_tiles_name_a_screen(self) -> None:
        """A screen tile with no screen is a tile that does nothing at all —
        there is no job to fall back on, and the failure is silent in the UI."""
        from helpers.kiosk import _DEFAULT_TILES

        for tile in _DEFAULT_TILES:
            if tile["kind"] == "screen":
                with self.subTest(tile=tile["id"]):
                    self.assertTrue((tile.get("screen") or "").strip())

    def test_screen_tiles_name_a_registered_panel(self) -> None:
        """A tile opening a screen whose data never loads is a dead end. Every
        screen tile that reads a panel must name one that exists; the screens
        with nothing to fetch (notifications, commands) are listed here so
        adding a third kind cannot pass unnoticed."""
        from helpers.kiosk import _DEFAULT_TILES
        from helpers.panels import _PANELS

        self_contained = {"notifications", "commands"}
        checked = 0
        for tile in _DEFAULT_TILES:
            if tile["kind"] != "screen":
                continue
            screen = tile["screen"]
            if screen in self_contained:
                continue
            with self.subTest(tile=tile["id"]):
                self.assertIn(
                    screen,
                    _PANELS,
                    f"tile '{tile['id']}' opens '{screen}', which has no panel.",
                )
            checked += 1

        self.assertGreater(checked, 0, "No screen tiles were checked at all.")

    def test_panels_name_the_module_that_gates_them(self) -> None:
        """A panel gated on the wrong module either 503s while its module is
        on, or runs while its module is off."""
        from helpers.panels import _PANELS

        for key, (module_name, _) in _PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(module_name)
                # modules/<name>.py is the whole contract for a module name.
                self.assertTrue(
                    os.path.exists(
                        os.path.join(_REPO_ROOT, "modules", f"{module_name}.py")
                    ),
                    f"panel '{key}' is gated on module '{module_name}', "
                    "which has no modules/ file.",
                )

    def test_screen_tiles_are_not_runnable(self) -> None:
        """POSTing a screen tile used to fall through to _run_job with a null
        job name, answering "'' isn't available right now." instead of saying
        the request made no sense."""
        from helpers import kiosk

        original = kiosk.tiles
        kiosk.tiles = lambda: [
            {"id": "accounts", "label": "Accounts", "icon": "", "kind": "screen",
             "job": None, "prompt": None, "screen": "accounts", "args": {}}
        ]
        try:
            with self.assertRaises(ValueError):
                kiosk.run_tile("accounts")
        finally:
            kiosk.tiles = original


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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
