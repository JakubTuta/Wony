"""The labwc config the touch panel's session runs with (helpers/session.py).

The session uses its own config directory, so the person's Screen Configuration
(which writes the touchscreen's rotation into their own rc.xml) is invisible to
it unless carried over. Without that, a rotated display taps in the old
orientation: the tabs draw along the bottom and respond on the right.

Run directly: python tests/test_session.py
"""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from helpers import session  # noqa: E402

_USERS = """\
<?xml version="1.0"?>
<labwc_config xmlns="http://openbox.org/3.4/rc">
  <theme><name>PiXtrix</name></theme>
  <keyboard><default /><keybind key="A-F4"><action name="Close" /></keybind></keyboard>
  <touch deviceName="10-0014 Goodix Capacitive TouchScreen" mapToOutput="DSI-2" />
  <libinput>
    <device category="touch">
      <calibrationMatrix>0 -1 1 1 0 0</calibrationMatrix>
    </device>
  </libinput>
</labwc_config>
"""


class SessionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.home = os.path.join(self.root.name, "config")
        self.system = os.path.join(self.root.name, "etc")
        self.dest = os.path.join(self.root.name, "session")
        patch = mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": self.home, "XDG_CONFIG_DIRS": self.system}
        )
        patch.start()
        self.addCleanup(patch.stop)

    def write_rc(self, base: str, text: str) -> None:
        folder = os.path.join(base, "labwc")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "rc.xml"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def built(self) -> ET.Element:
        session.build(self.dest)
        return ET.parse(os.path.join(self.dest, "rc.xml")).getroot()


class TestInputSettings(SessionTestCase):
    def test_the_touchscreens_rotation_is_carried_over(self) -> None:
        self.write_rc(self.home, _USERS)

        root = self.built()

        matrix = root.find("./libinput/device/calibrationMatrix")
        self.assertEqual(matrix.text.strip(), "0 -1 1 1 0 0")
        self.assertEqual(root.find("touch").get("mapToOutput"), "DSI-2")

    def test_their_shortcuts_and_theme_are_not(self) -> None:
        self.write_rc(self.home, _USERS)

        root = self.built()

        self.assertIsNone(root.find("theme"))
        self.assertEqual(list(root.find("keyboard")), [])

    def test_the_panels_own_settings_stay(self) -> None:
        self.write_rc(self.home, _USERS)

        rule = self.built().find("./windowRules/windowRule")

        self.assertEqual(rule.get("serverDecoration"), "no")

    def test_without_a_config_the_panel_still_starts(self) -> None:
        root = self.built()

        self.assertIsNone(root.find("libinput"))
        self.assertIsNotNone(root.find("windowRules"))

    def test_their_own_file_beats_the_systems(self) -> None:
        self.write_rc(self.system, _USERS.replace("DSI-2", "SYSTEM-1"))
        self.write_rc(self.home, _USERS)

        self.assertEqual(self.built().find("touch").get("mapToOutput"), "DSI-2")

    def test_the_systems_file_is_used_when_they_have_none(self) -> None:
        self.write_rc(self.system, _USERS.replace("DSI-2", "SYSTEM-1"))

        self.assertEqual(self.built().find("touch").get("mapToOutput"), "SYSTEM-1")

    def test_a_config_that_will_not_parse_does_not_stop_the_panel(self) -> None:
        self.write_rc(self.home, "<labwc_config><touch")

        with mock.patch("sys.stderr"):
            root = self.built()

        self.assertIsNone(root.find("touch"))
        self.assertIsNotNone(root.find("windowRules"))

    def test_a_rebuild_replaces_rather_than_doubles(self) -> None:
        self.write_rc(self.home, _USERS)
        session.build(self.dest)

        root = self.built()

        self.assertEqual(len(root.findall("libinput")), 1)
        self.assertEqual(len(root.findall("touch")), 1)


class TestSessionFiles(SessionTestCase):
    def test_the_environment_and_autostart_come_along(self) -> None:
        session.build(self.dest)

        for name in ("environment", "autostart", "rc.xml"):
            self.assertTrue(os.path.isfile(os.path.join(self.dest, name)), name)

    def test_labwc_runs_the_panel_as_its_session_and_exits_with_it(self) -> None:
        with mock.patch("helpers.session.shutil.which", return_value="/usr/bin/labwc"), mock.patch(
            "helpers.session.config_dir", return_value=self.dest
        ):
            command = session.command("/home/pi/wony/venv/bin/python", "/home/pi/wony/wony.py")

        self.assertEqual(command[:3], ["/usr/bin/labwc", "-C", self.dest])
        self.assertEqual(command[3], "-S")
        self.assertEqual(command[4], "/home/pi/wony/venv/bin/python /home/pi/wony/wony.py panel")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
