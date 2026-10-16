"""Making the Pi a Wony panel at boot, and putting the desktop back.

The risk here is a Pi that boots to a black screen: the desktop turned off and
the panel not turned on. These tests pin the order of the steps, that a failure
in the middle restores what it changed, and that uninstall undoes install.

Run directly: python tests/test_autostart.py
"""
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from helpers import autostart  # noqa: E402


@unittest.skipIf(os.name == "nt", "the unit is written for Linux paths")
class TestPanelUnit(unittest.TestCase):
    def _exec_start(self, text: str) -> list:
        line = next(line for line in text.splitlines() if line.startswith("ExecStart="))
        return shlex.split(line[len("ExecStart="):])

    def test_labwc_runs_the_panel_as_its_session_and_exits_with_it(self) -> None:
        with mock.patch("helpers.autostart._REPO_ROOT", "/home/pi/wony"), mock.patch(
            "helpers.autostart._python", return_value="/home/pi/wony/venv/bin/python"
        ), mock.patch("helpers.autostart._labwc", return_value="/usr/bin/labwc"):
            text = autostart._panel_unit_text("pi")

        self.assertEqual(
            self._exec_start(text),
            ["/usr/bin/labwc", "-C", "/home/pi/wony/kiosk/session",
             "-S", "/home/pi/wony/venv/bin/python /home/pi/wony/wony.py panel"],
        )

    def test_a_path_with_spaces_survives_both_layers_of_quoting(self) -> None:
        with mock.patch("helpers.autostart._REPO_ROOT", "/home/pi/my wony"), mock.patch(
            "helpers.autostart._python", return_value="/home/pi/my wony/venv/bin/python"
        ), mock.patch("helpers.autostart._labwc", return_value="/usr/bin/labwc"):
            words = self._exec_start(autostart._panel_unit_text("pi"))

        self.assertEqual(words[2], "/home/pi/my wony/kiosk/session")
        self.assertEqual(
            shlex.split(words[4]),
            ["/home/pi/my wony/venv/bin/python", "/home/pi/my wony/wony.py", "panel"],
        )

    def test_it_takes_the_display_and_the_login_tty_like_a_display_manager(self) -> None:
        text = autostart._panel_unit_text("pi")
        for line in (
            "User=pi",
            "PAMName=login",
            "Conflicts=getty@tty1.service",
            "TTYPath=/dev/tty1",
            "Restart=always",
            "WantedBy=graphical.target",
            "Alias=display-manager.service",
        ):
            self.assertIn(line, text.splitlines())

    def test_the_session_bus_is_the_owners_not_roots(self) -> None:
        with mock.patch("helpers.autostart._uid", return_value=1001):
            text = autostart._panel_unit_text("pi")

        self.assertIn("Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus", text.splitlines())

    def test_a_percent_in_a_path_is_not_a_systemd_specifier(self) -> None:
        self.assertEqual(autostart._systemd_quote("/a%b"), '"/a%%b"')
        self.assertEqual(autostart._systemd_quote('say "hi"'), '"say \\"hi\\""')


class AutostartTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.unit = os.path.join(self.dir, "wony-panel.service")
        self.state_file = os.path.join(self.dir, "state.json")
        self.sudo: list = []
        self.refuse: set = set()
        self.manager = "lightdm.service"

        def fake_sudo(*command: str) -> bool:
            self.sudo.append(command)
            if command in self.refuse:
                return False
            if command[0] == "install":
                shutil.copy(command[3], command[4])
            elif command[0] == "rm":
                if os.path.exists(command[2]):
                    os.unlink(command[2])
            return True

        patches = [
            mock.patch("helpers.autostart._has_systemd", return_value=True),
            mock.patch("helpers.autostart._sudo", side_effect=fake_sudo),
            mock.patch("helpers.autostart._panel_unit_path", return_value=self.unit),
            mock.patch("helpers.autostart._STATE_FILE", self.state_file),
            mock.patch("helpers.autostart._screen_ready", return_value=None),
            mock.patch("helpers.autostart._install_assistant", return_value=True),
            mock.patch("helpers.autostart._remove_legacy_browser_unit"),
            mock.patch("helpers.autostart._user_systemctl"),
            mock.patch("helpers.autostart._current_display_manager", side_effect=lambda: self.manager),
            mock.patch("helpers.autostart._default_target", return_value="graphical.target"),
            mock.patch("helpers.autostart.getpass.getuser", return_value="pi"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)

    def commands(self) -> list:
        return [" ".join(c) for c in self.sudo]


class TestInstall(AutostartTestCase):
    def test_the_unit_goes_in_before_the_desktop_goes_out(self) -> None:
        autostart.install()

        steps = self.commands()
        self.assertTrue(steps[0].startswith("install -m 0644 "))
        self.assertEqual(
            steps[1:],
            [
                "systemctl daemon-reload",
                "systemctl disable lightdm.service",
                "systemctl enable wony-panel.service",
                "systemctl set-default graphical.target",
            ],
        )
        self.assertTrue(os.path.exists(self.unit))

    def test_how_to_undo_it_is_written_down_first(self) -> None:
        autostart.install()

        with open(self.state_file, encoding="utf-8") as fh:
            self.assertEqual(
                json.load(fh), {"display_manager": "lightdm.service", "default_target": "graphical.target"}
            )

    def test_installing_again_does_not_mistake_the_panel_for_the_desktop(self) -> None:
        autostart.install()
        self.manager = ""  # now the display manager is our own panel
        autostart.install()

        with open(self.state_file, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["display_manager"], "lightdm.service")

    def test_if_the_panel_cannot_be_enabled_the_desktop_comes_back(self) -> None:
        self.refuse.add(("systemctl", "enable", "wony-panel.service"))

        autostart.install()

        self.assertEqual(self.commands()[-1], "systemctl enable lightdm.service")

    def test_if_the_desktop_cannot_be_disabled_nothing_else_changes(self) -> None:
        self.refuse.add(("systemctl", "disable", "lightdm.service"))

        autostart.install()

        self.assertNotIn("systemctl enable wony-panel.service", self.commands())

    def test_a_failed_unit_install_leaves_the_desktop_alone(self) -> None:
        autostart._sudo.side_effect = lambda *command: False

        autostart.install()

        self.assertEqual(len(autostart._sudo.call_args_list), 1)

    def test_without_the_screens_packages_the_desktop_is_not_touched(self) -> None:
        with mock.patch("helpers.autostart._screen_ready", return_value="missing packages"):
            autostart.install()

        self.assertEqual(self.sudo, [])

    def test_a_headless_install_needs_no_sudo_at_all(self) -> None:
        autostart.install(screen=False)

        self.assertEqual(self.sudo, [])


class TestUninstall(AutostartTestCase):
    def test_uninstall_undoes_install(self) -> None:
        autostart.install()
        self.sudo.clear()

        autostart.uninstall()

        self.assertEqual(
            self.commands(),
            [
                "systemctl disable wony-panel.service",
                f"rm -f {self.unit}",
                "systemctl daemon-reload",
                "systemctl enable lightdm.service",
                "systemctl set-default graphical.target",
            ],
        )
        self.assertFalse(os.path.exists(self.unit))
        self.assertFalse(os.path.exists(self.state_file))

    def test_without_a_record_it_says_how_to_get_the_desktop_back(self) -> None:
        with open(self.unit, "w", encoding="utf-8") as fh:
            fh.write("[Unit]\n")

        with mock.patch("builtins.print") as out:
            autostart.uninstall()

        shown = " ".join(str(call.args[0]) for call in out.call_args_list if call.args)
        self.assertIn("sudo systemctl enable lightdm", shown)

    def test_a_device_that_never_had_the_panel_is_left_alone(self) -> None:
        autostart.uninstall()

        self.assertEqual(self.sudo, [])


class TestLegacyUnit(unittest.TestCase):
    def test_the_old_chromium_unit_is_removed_on_install(self) -> None:
        with tempfile.TemporaryDirectory() as unit_dir:
            old = os.path.join(unit_dir, autostart.LEGACY_BROWSER_UNIT_NAME)
            with open(old, "w", encoding="utf-8") as fh:
                fh.write("[Unit]\n")
            with mock.patch("helpers.autostart._unit_dir", return_value=unit_dir), mock.patch(
                "helpers.autostart._user_systemctl"
            ) as systemctl:
                autostart._remove_legacy_browser_unit()

            self.assertFalse(os.path.exists(old))
            systemctl.assert_any_call("disable", "--now", autostart.LEGACY_BROWSER_UNIT_NAME)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
