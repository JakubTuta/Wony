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
import typing
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
        import re

        from helpers.kiosk import _AMBIENT_CARDS, _DEFAULT_TILES

        # Read the module's source rather than the registry: a module only
        # registers its jobs once it is enabled AND its credentials are in
        # place, so a registry check passes or fails by local config instead of
        # by whether the name is real.
        entries = [(t["module"], t["job"]) for t in _DEFAULT_TILES if t["kind"] == "job"]
        entries += [(c["module"], c["job"]) for c in _AMBIENT_CARDS]

        sources: typing.Dict[str, str] = {}
        for module_name in {name for name, _ in entries}:
            path = os.path.join(_REPO_ROOT, "modules", f"{module_name}.py")
            with open(path, encoding="utf-8") as handle:
                sources[module_name] = handle.read()

        for module_name, job_name in entries:
            with self.subTest(module=module_name, job=job_name):
                self.assertRegex(
                    sources[module_name],
                    rf"(?m)^\s*def {re.escape(job_name)}\(",
                    f"{module_name} declares a tile/card for '{job_name}', "
                    f"which modules/{module_name}.py does not define.",
                )

        self.assertTrue(entries, "No default entries could be checked at all.")

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

        for key, spec in _PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(spec.module)
                # modules/<name>.py is the whole contract for a module name.
                self.assertTrue(
                    os.path.exists(
                        os.path.join(_REPO_ROOT, "modules", f"{spec.module}.py")
                    ),
                    f"panel '{key}' is gated on module '{spec.module}', "
                    "which has no modules/ file.",
                )

    def test_every_panel_loader_resolves(self) -> None:
        """A panel whose snapshot was renamed fails only when tapped, which is
        exactly where nobody is looking for it."""
        import inspect

        from helpers.panels import _PANELS

        # What each panel actually calls. Checked against the module rather
        # than the registry, which is only populated once modules have loaded.
        free_functions = {"weather": "snapshot", "home_assistant": "snapshot"}
        methods = {
            "calendar": "agenda_snapshot",
            "spotify": "playback_snapshot",
            "google_accounts": "accounts_snapshot",
            "scheduler": "reminders_snapshot",
        }

        checked = 0
        for key, spec in _PANELS.items():
            try:
                module = __import__(f"modules.{spec.module}", fromlist=["*"])
            except Exception:
                continue  # optional dependency missing; same as CI
            with self.subTest(panel=key):
                if spec.module in free_functions:
                    name = free_functions[spec.module]
                    self.assertTrue(
                        callable(getattr(module, name, None)),
                        f"panel '{key}' calls {spec.module}.{name}(), which is gone.",
                    )
                else:
                    name = methods[spec.module]
                    owners = [
                        cls
                        for _, cls in inspect.getmembers(module, inspect.isclass)
                        if cls.__module__ == module.__name__ and hasattr(cls, name)
                    ]
                    self.assertTrue(
                        owners,
                        f"panel '{key}' calls {spec.module}.{name}(), "
                        "which no class in that module defines.",
                    )
            checked += 1

        self.assertGreater(checked, 0, "No panels could be checked at all.")

    def test_a_loaders_keyerror_is_not_mistaken_for_an_unknown_panel(self) -> None:
        """panel() raises KeyError for a name that does not exist, and the API
        answers 404. A KeyError from inside a loader means something else
        entirely and must not read as 'no such panel'."""
        def explode() -> dict:
            raise KeyError("main")

        from helpers import panels
        from helpers.config import Config

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
        assert Config._settings is not None
        original_modules = list(Config._settings.enabled_modules)
        # _Panel is a NamedTuple, so the entry is replaced rather than patched.
        original_panel = panels._PANELS["weather"]
        try:
            Config._settings.enabled_modules = ["weather"]
            panels._PANELS["weather"] = original_panel._replace(load=explode)
            with self.assertRaises(RuntimeError):
                panels.panel("weather")

            # And a genuinely unknown key still raises KeyError.
            with self.assertRaises(KeyError):
                panels.panel("nonsense")
        finally:
            panels._PANELS["weather"] = original_panel
            Config._settings.enabled_modules = original_modules

    def test_available_follows_enabled_modules(self) -> None:
        """The tile row is built from this; a panel for a module that is off is
        a button that only ever 503s."""
        from helpers.config import Config
        from helpers.panels import available

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
        assert Config._settings is not None
        original = list(Config._settings.enabled_modules)
        try:
            Config._settings.enabled_modules = ["weather", "spotify"]
            keys = [p["key"] for p in available()]
            self.assertEqual(keys, ["weather", "music"])

            Config._settings.enabled_modules = []
            self.assertEqual(available(), [])
        finally:
            Config._settings.enabled_modules = original

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


class TestKioskJobsShareTheAgentLock(unittest.TestCase):
    """A tile runs a job on the request thread. Both of these fail silently:
    the flag one makes a running turn narrate every tool call, and the idle one
    only shows up as a screen that stopped refreshing."""

    def test_a_tile_waits_for_a_turn_in_progress(self) -> None:
        from helpers import kiosk
        from helpers.decorators import agent_lock
        from helpers.registry import ServiceRegistry

        started = threading.Event()
        ServiceRegistry._jobs["_probe"] = lambda: started.set() or "done"
        try:
            with agent_lock:
                worker = threading.Thread(
                    target=lambda: kiosk._run_job("_probe", {}, source="test")
                )
                worker.start()
                # The lock is held here, so the job must not have run yet.
                self.assertFalse(started.wait(0.3))
            worker.join(timeout=5)
            self.assertTrue(started.is_set())
        finally:
            ServiceRegistry._jobs.pop("_probe", None)

    def test_the_idle_screen_gives_up_instead_of_queueing(self) -> None:
        from helpers import kiosk
        from helpers.decorators import agent_lock
        from helpers.registry import ServiceRegistry

        ServiceRegistry._jobs["_probe"] = lambda: "done"
        try:
            with agent_lock:
                result = kiosk._run_job("_probe", {}, source="ambient:x", wait=False)
            self.assertFalse(result.ok)
            self.assertEqual(result.text, "")
        finally:
            ServiceRegistry._jobs.pop("_probe", None)


class TestNotifications(unittest.TestCase):
    def test_wipe_clears_notifications(self) -> None:
        """'Erase everything you know about me' has to mean the reminders that
        already fired too, not just conversation history."""
        import inspect

        from helpers import memory_db

        source = inspect.getsource(memory_db.wipe_all)
        self.assertIn("notifications", source)

    def test_notify_survives_a_dead_database(self) -> None:
        """A poller must not die because the DB is locked — the message still
        has to reach a connected screen."""
        from unittest import mock

        from helpers import events, notify as notify_mod

        seen = []
        events.subscribe(seen.append)
        try:
            with mock.patch(
                "helpers.memory_db.insert_notification",
                side_effect=OSError("database is locked"),
            ):
                notify_mod.notify("Timer done", kind="reminder", source="scheduler")
        finally:
            events.unsubscribe(seen.append)

        self.assertEqual(len(seen), 1, seen)
        self.assertEqual(seen[0]["type"], "notification")
        self.assertEqual(seen[0]["text"], "Timer done")

    def test_several_messages_arrive_as_one(self) -> None:
        """The pollers hand over a list; passing it straight through would put
        the word 'list' on the screen."""
        from unittest import mock

        from helpers import notify as notify_mod

        with mock.patch("helpers.memory_db.insert_notification") as insert:
            insert.side_effect = lambda text, kind, source: {
                "id": 1, "ts": "", "kind": kind, "source": source,
                "text": text, "acknowledged": False,
            }
            notify_mod.notify(["You have 2 new email(s).", "From: Ada"],
                              kind="alert", source="gmail")
            self.assertEqual(
                insert.call_args.args[0], "You have 2 new email(s). From: Ada"
            )

    def test_unknown_kind_falls_back_rather_than_raising(self) -> None:
        """kind reaches the UI as a style name; an unknown one must not throw
        inside a background thread."""
        from unittest import mock

        from helpers import notify as notify_mod

        with mock.patch("helpers.memory_db.insert_notification") as insert:
            insert.side_effect = lambda text, kind, source: {
                "id": 1, "ts": "", "kind": kind, "source": source,
                "text": text, "acknowledged": False,
            }
            notify_mod.notify("hello", kind="klaxon", source="test")
            self.assertEqual(insert.call_args.kwargs["kind"], "info")

    def test_empty_message_is_dropped(self) -> None:
        """An empty list from a poller that found nothing must not become a
        blank row in the notifications screen."""
        from unittest import mock

        from helpers import notify as notify_mod

        with mock.patch("helpers.memory_db.insert_notification") as insert:
            notify_mod.notify([])
            notify_mod.notify("   ")
            insert.assert_not_called()


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
