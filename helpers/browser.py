"""The browser a Google or Spotify sign-in opens, shown over the touch panel.

Google blocks sign-in inside embedded webviews (`disallowed_useragent`) and its
device-code flow does not allow Gmail or Calendar scopes, so a real browser has
to show the consent page. The panel has none running: Chromium is started for
the sign-in only, with the on-screen keyboard beside it, and closed the moment
the OAuth flow returns, so it costs memory for a minute a year.

On a machine with no Wayland session (a dev PC, an SSH session) or no Chromium,
the page opens in whatever browser `webbrowser` would pick.
"""
import contextlib
import os
import shutil
import subprocess
import tempfile
import threading
import typing
import webbrowser

from helpers.wayland import session_env

NAME = "wony-sign-in"

_CHROMIUM_BINARIES = ("chromium", "chromium-browser")
_KEYBOARD = "wvkbd-mobintl"

# One sign-in on the glass at a time: two windows over each other help nobody.
_lock = threading.Lock()


def chromium() -> typing.Optional[str]:
    for name in _CHROMIUM_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


class _SignInBrowser(webbrowser.BaseBrowser):
    """Opens one consent page in a throwaway Chromium and keeps it to close later."""

    def __init__(self) -> None:
        super().__init__(NAME)
        self._processes: typing.List[subprocess.Popen] = []
        self._profile = ""

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        env = session_env()
        binary = chromium()
        if env is None or binary is None:
            return webbrowser.open(url)

        # A fresh profile each time: nothing from a sign-in is kept on the Pi.
        self._profile = tempfile.mkdtemp(prefix="wony-sign-in-")
        try:
            self._processes.append(self._spawn([
                binary,
                f"--app={url}",
                "--ozone-platform=wayland",
                f"--user-data-dir={self._profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--noerrdialogs",
                "--disable-infobars",
                "--disable-session-crashed-bubble",
                "--disable-features=TranslateUI",
                "--check-for-update-interval=31536000",
                "--start-maximized",
            ], env))
        except OSError:
            return webbrowser.open(url)

        keyboard = shutil.which(_KEYBOARD)
        if keyboard:
            with contextlib.suppress(OSError):
                self._processes.append(self._spawn([keyboard], env))
        return True

    @staticmethod
    def _spawn(command: typing.List[str], env: typing.Dict[str, str]) -> subprocess.Popen:
        return subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def close(self) -> None:
        for process in reversed(self._processes):
            if process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self._processes.clear()
        if self._profile:
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = ""


@contextlib.contextmanager
def sign_in() -> typing.Iterator[str]:
    """The name to give `webbrowser.get()` (or google_auth_oauthlib's `browser=`)
    for the length of one sign-in. The window and keyboard close on the way out,
    whether the sign-in finished, timed out or failed."""
    with _lock:
        browser = _SignInBrowser()
        webbrowser.register(NAME, None, instance=browser)
        try:
            yield NAME
        finally:
            browser.close()
