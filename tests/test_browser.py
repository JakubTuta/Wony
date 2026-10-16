"""The browser a Google or Spotify sign-in opens over the touch panel.

It must appear on the panel with a keyboard, and be gone the moment the sign-in
ends however it ends: a Chromium left running on a 2 GB Pi is the exact problem
the native panel exists to avoid.

Run directly: python tests/test_browser.py
"""
import os
import sys
import threading
import unittest
import webbrowser
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from helpers import browser  # noqa: E402

_URL = "https://accounts.google.com/o/oauth2/auth?x=1"


def _process() -> mock.Mock:
    process = mock.Mock()
    process.poll.return_value = None
    return process


class TestOnThePanel(unittest.TestCase):
    def setUp(self) -> None:
        self.processes: list = []

        def popen(command, **kwargs):
            process = _process()
            process.command = command
            process.env = kwargs.get("env")
            self.processes.append(process)
            return process

        which = {"chromium": "/usr/bin/chromium", "wvkbd-mobintl": "/usr/bin/wvkbd-mobintl"}
        patches = [
            mock.patch("helpers.browser.session_env", return_value={"WAYLAND_DISPLAY": "wayland-0"}),
            mock.patch("helpers.browser.shutil.which", side_effect=lambda name: which.get(name)),
            mock.patch("helpers.browser.subprocess.Popen", side_effect=popen),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_chromium_opens_the_page_as_a_wayland_app_with_a_throwaway_profile(self) -> None:
        with browser.sign_in() as name:
            self.assertTrue(webbrowser.get(name).open(_URL))
            chromium = self.processes[0]
            profile = next(a for a in chromium.command if a.startswith("--user-data-dir=")).split("=", 1)[1]
            self.assertTrue(os.path.isdir(profile))

        self.assertEqual(chromium.command[0], "/usr/bin/chromium")
        self.assertIn(f"--app={_URL}", chromium.command)
        self.assertIn("--ozone-platform=wayland", chromium.command)
        self.assertEqual(chromium.env, {"WAYLAND_DISPLAY": "wayland-0"})
        self.assertFalse(os.path.exists(profile), "the profile outlived the sign-in")

    def test_the_on_screen_keyboard_comes_with_it(self) -> None:
        with browser.sign_in() as name:
            webbrowser.get(name).open(_URL)

        self.assertEqual([p.command[0] for p in self.processes], ["/usr/bin/chromium", "/usr/bin/wvkbd-mobintl"])

    def test_both_are_closed_when_the_sign_in_ends(self) -> None:
        with browser.sign_in() as name:
            webbrowser.get(name).open(_URL)

        for process in self.processes:
            process.terminate.assert_called_once()

    def test_both_are_closed_when_the_sign_in_fails_too(self) -> None:
        with self.assertRaises(RuntimeError):
            with browser.sign_in() as name:
                webbrowser.get(name).open(_URL)
                raise RuntimeError("consent timed out")

        for process in self.processes:
            process.terminate.assert_called_once()

    def test_a_browser_that_ignores_terminate_is_killed(self) -> None:
        import subprocess

        with browser.sign_in() as name:
            webbrowser.get(name).open(_URL)
            self.processes[0].wait.side_effect = subprocess.TimeoutExpired("chromium", 5)

        self.processes[0].kill.assert_called_once()

    def test_only_one_sign_in_is_on_the_glass_at_a_time(self) -> None:
        second_started = threading.Event()

        def second() -> None:
            with browser.sign_in():
                second_started.set()

        with browser.sign_in():
            thread = threading.Thread(target=second)
            thread.start()
            self.assertFalse(second_started.wait(0.3), "two sign-ins overlapped")
        thread.join(timeout=5)
        self.assertTrue(second_started.is_set())


class TestNotOnThePanel(unittest.TestCase):
    def test_with_no_wayland_session_the_default_browser_is_used(self) -> None:
        with mock.patch("helpers.browser.session_env", return_value=None), mock.patch(
            "helpers.browser.subprocess.Popen"
        ) as popen, mock.patch("helpers.browser.webbrowser.open", return_value=True) as default:
            with browser.sign_in() as name:
                webbrowser.get(name).open(_URL)

        default.assert_called_once_with(_URL)
        popen.assert_not_called()

    def test_with_no_chromium_the_default_browser_is_used(self) -> None:
        with mock.patch("helpers.browser.session_env", return_value={"WAYLAND_DISPLAY": "w"}), mock.patch(
            "helpers.browser.shutil.which", return_value=None
        ), mock.patch("helpers.browser.subprocess.Popen") as popen, mock.patch(
            "helpers.browser.webbrowser.open", return_value=True
        ) as default:
            with browser.sign_in() as name:
                webbrowser.get(name).open(_URL)

        default.assert_called_once_with(_URL)
        popen.assert_not_called()

    def test_a_chromium_that_will_not_start_falls_back_too(self) -> None:
        with mock.patch("helpers.browser.session_env", return_value={"WAYLAND_DISPLAY": "w"}), mock.patch(
            "helpers.browser.shutil.which", return_value="/usr/bin/chromium"
        ), mock.patch("helpers.browser.subprocess.Popen", side_effect=OSError("exec format")), mock.patch(
            "helpers.browser.webbrowser.open", return_value=True
        ) as default:
            with browser.sign_in() as name:
                webbrowser.get(name).open(_URL)

        default.assert_called_once_with(_URL)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
