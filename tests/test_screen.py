"""The touch panel (kiosk/), loaded offscreen against a fixture API.

A QML mistake is a blank or half-drawn screen on the device, the hardest place
to notice it. This loads the real Main.qml, walks every tab and sheet, and
fails on any QML warning; then taps a few things and checks what reached the API.
Needs PySide6 (requirements/dev-screen.txt) and the fastapi/uvicorn the server
already uses; without PySide6 the Qt tests skip.

Also covers how the panel is found and launched (helpers/screen.py).

Run directly: python tests/test_screen.py
"""
import importlib.util
import os
import sys
import time
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The same renderer on every machine, so what is drawn does not depend on a GPU.
os.environ.setdefault("QT_QUICK_BACKEND", "software")

HAVE_QT = importlib.util.find_spec("PySide6") is not None

# Where things are on the 1280x800 panel. The layout is fixed, so a tap is a point.
NAV = {"home": (150, 740), "rooms": (450, 740), "music": (750, 740), "macros": (1050, 740)}
GEAR = (1126, 48)
BELL = (1208, 48)
SETTINGS_ACCOUNTS = (240, 132)
SETTINGS_SLEEP = (386, 132)
ADD_ACCOUNT = (640, 624)
KEYS_QWE = [(80, 498), (205, 498), (329, 498)]
ADD_AND_SIGN_IN = (640, 404)
LIGHT_TILE = (160, 240)
LOCK_TILE = (730, 240)
ROUTINE_TILE = (160, 560)
CONFIRM_YES = (796, 474)
SLEEP_NOW = (640, 627)
EDIT = (1037, 48)
ADD_TILE = (170, 560)

# Not QML problems: the offscreen platform has no system font directory.
_HARMLESS = ("Cannot find font directory", "Note that Qt no longer ships fonts")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed (requirements/dev-screen.txt)")
class TestPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import shiboken6
        from PySide6.QtCore import qInstallMessageHandler
        from PySide6.QtGui import QGuiApplication

        from tests import screen_fixture

        cls._shiboken = shiboken6
        cls.messages: list = []

        def handler(mode, context, message):
            cls.messages.append(f"{mode.name} {context.file}:{context.line} {message}")

        qInstallMessageHandler(handler)
        cls._server = screen_fixture.serve()
        cls.url, cls.fixture = cls._server.__enter__()
        cls.state = cls.fixture.state.fixture
        cls.app = QGuiApplication.instance() or QGuiApplication(
            ["panel-test", "--api", cls.url, "--windowed"]
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)

    def setUp(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuick import QQuickWindow

        from tests import screen_fixture

        self.messages.clear()
        self.state["posted"].clear()
        self.state["tiles"] = list(screen_fixture.DEFAULT_TILES)
        self.state["seen"].clear()

        self.engine = QQmlApplicationEngine()
        self.engine.load(QUrl.fromLocalFile(os.path.join(_REPO_ROOT, "kiosk", "Main.qml")))
        roots = self.engine.rootObjects()
        self.assertTrue(roots, "Main.qml did not load:\n" + "\n".join(self.messages))
        pointer = self._shiboken.Shiboken.getCppPointer(roots[0])[0]
        self.window = self._shiboken.Shiboken.wrapInstance(pointer, QQuickWindow)
        self.window.resize(1280, 800)
        # Connected means the panel has config, tiles and a socket to talk on.
        self.pump_until(lambda: "/api/sleep" in self.state["seen"], "the panel never connected")
        self.pump(800)

    def tearDown(self) -> None:
        self.window = None
        self.engine.deleteLater()
        self.pump(100)

    def pump(self, ms: int) -> None:
        end = time.time() + ms / 1000
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def pump_until(self, condition, why: str, seconds: float = 10) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail(why)

    def tap(self, point, wait: int = 500) -> None:
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(*point))
        self.pump(wait)

    def qml_problems(self) -> list:
        return [m for m in self.messages if not any(ok in m for ok in _HARMLESS)]

    def test_the_panel_draws_instead_of_staying_blank(self) -> None:
        image = self.window.grabWindow()
        self.assertEqual((image.width(), image.height()), (1280, 800))
        # The clock at the top left is light text on a dark panel.
        light = sum(
            1
            for x in range(30, 260, 2)
            for y in range(20, 80, 2)
            if image.pixelColor(x, y).lightness() > 200
        )
        self.assertGreater(light, 100, "no clock was drawn")
        self.assertEqual(self.qml_problems(), [])

    def test_every_tab_and_sheet_opens_without_a_qml_warning(self) -> None:
        for name in ("rooms", "music", "macros", "home"):
            self.tap(NAV[name], 700)

        self.tap(EDIT)
        self.tap(ADD_TILE)  # the add-a-tile sheet
        self.tap((938, 181))  # its Close button
        self.tap(EDIT)

        self.tap(BELL)  # notifications
        self.tap((100, 700))  # tapping outside closes it

        self.tap(GEAR, 900)  # settings
        self.tap(SETTINGS_ACCOUNTS, 900)
        self.tap(ADD_ACCOUNT)  # the add sheet, with the on-screen keyboard
        self.tap((1246, 231))  # its X
        self.tap(SETTINGS_SLEEP)  # the sleep sheet

        self.assertEqual(self.qml_problems(), [])

    def test_tapping_a_light_toggles_it_through_the_api(self) -> None:
        self.tap(LIGHT_TILE)
        self.pump_until(lambda: self.state["posted"], "the tap never reached the API")
        self.assertEqual(
            self.state["posted"][0],
            ("control", {"entity_id": "light.lamp", "action": "toggle"}),
        )

    def test_a_routine_runs_over_the_socket_the_guard_lets_through(self) -> None:
        """The fixture applies helpers/local_only.py. If the panel's WebSocket sent
        an Origin the real server refuses, it would never connect and say
        'Not connected' instead of sending the sentence."""
        self.tap(ROUTINE_TILE)
        self.pump_until(lambda: self.state["posted"], "the routine never ran")
        self.assertEqual(self.state["posted"][0], ("chat", "run my good night routine"))

    def test_a_lock_asks_before_it_moves(self) -> None:
        self.tap(LOCK_TILE)
        self.assertEqual(self.state["posted"], [], "the lock moved without being confirmed")
        self.tap(CONFIRM_YES)
        self.pump_until(lambda: self.state["posted"], "confirming did nothing")
        self.assertEqual(
            self.state["posted"][0],
            ("control", {"entity_id": "lock.front", "action": "unlock"}),
        )

    def test_the_on_screen_keyboard_types_into_a_field(self) -> None:
        self.tap(GEAR, 900)
        self.tap(SETTINGS_ACCOUNTS, 900)
        self.tap(ADD_ACCOUNT, 700)
        for key in KEYS_QWE:
            self.tap(key, 200)
        self.tap(ADD_AND_SIGN_IN)
        self.pump_until(lambda: self.state["posted"], "the account was never added")
        self.assertEqual(
            self.state["posted"][0],
            ("invoke", {"name": "manage_google_accounts", "args": {"action": "add", "name": "qwe"}}),
        )

    def test_sleep_goes_through_the_api_and_remembers_the_wake_time(self) -> None:
        self.tap(GEAR, 900)
        self.tap(SETTINGS_SLEEP)
        self.tap(SLEEP_NOW)
        self.pump_until(lambda: self.state["posted"], "sleep never reached the API")
        # The fixture says the last wake time was 07:00, so it is pre-chosen.
        self.assertEqual(self.state["posted"][0], ("sleep", {"wake_at": "07:00"}))

    def test_the_home_layout_is_saved_when_a_tile_is_added(self) -> None:
        self.tap(EDIT)
        self.tap(ADD_TILE)
        self.tap((400, 270))  # the first thing offered
        self.pump_until(lambda: len(self.state["tiles"]) == 7, "the new tile was not saved")


class TestFindingThePanel(unittest.TestCase):
    def test_the_qml_tool_wins_and_gets_the_api_after_a_double_dash(self) -> None:
        from helpers import screen

        with mock.patch("helpers.screen.shutil.which", return_value="/usr/bin/qml6"):
            command = screen.panel_command("http://127.0.0.1:8000", windowed=True)
        self.assertEqual(command[0], "/usr/bin/qml6")
        self.assertTrue(command[1].endswith("Main.qml"))
        self.assertEqual(command[2:], ["--", "--api", "http://127.0.0.1:8000", "--windowed"])

    def test_a_dev_machine_falls_back_to_the_pyside_launcher(self) -> None:
        from helpers import screen

        with mock.patch("helpers.screen._qml_tool", return_value=None), mock.patch(
            "helpers.screen.importlib.util.find_spec", return_value=object()
        ):
            command = screen.panel_command("http://127.0.0.1:8000")
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("dev_panel.py"))
        self.assertEqual(command[2:], ["--api", "http://127.0.0.1:8000"])

    def test_nothing_to_run_it_with_says_so(self) -> None:
        from helpers import screen

        with mock.patch("helpers.screen._qml_tool", return_value=None), mock.patch(
            "helpers.screen.importlib.util.find_spec", return_value=None
        ):
            self.assertIsNone(screen.panel_command("http://127.0.0.1:8000"))

    def test_only_packages_dpkg_does_not_know_are_missing(self) -> None:
        from helpers import screen

        have = {"qml-qt6", "labwc"}
        with mock.patch("helpers.screen.shutil.which", return_value="/usr/bin/dpkg-query"), mock.patch(
            "helpers.screen.installed", side_effect=lambda package: package in have
        ):
            missing = screen.missing_packages()
        self.assertNotIn("labwc", missing)
        self.assertIn("wvkbd", missing)
        self.assertEqual(len(missing), len(screen.APT_PACKAGES) - len(have))

    def test_off_debian_nothing_is_reported_missing(self) -> None:
        from helpers import screen

        with mock.patch("helpers.screen.shutil.which", return_value=None):
            self.assertEqual(screen.missing_packages(), [])

    def test_the_install_command_names_every_package(self) -> None:
        from helpers import screen

        command = screen.install_command(screen.APT_PACKAGES)
        self.assertTrue(command.startswith("sudo apt-get install -y "))
        for package in ("qml-qt6", "qt6-wayland", "labwc", "wlopm", "wvkbd", "chromium"):
            self.assertIn(package, command)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
