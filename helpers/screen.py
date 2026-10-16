"""What the touch panel needs from the operating system.

The panel is a Qt Quick app (kiosk/) run by Qt's own `qml6` tool inside a bare
labwc session. Both come from apt on Raspberry Pi OS Trixie (Debian 13); nothing
is compiled and no Python or Node runs inside the panel.

Standard library only: setup.py imports this before any package is installed.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import typing

# Raspberry Pi OS Trixie ships Qt 6.8; Bookworm stops at 6.4, which is too old.
MIN_DEBIAN_VERSION = 13

# Everything `qml6 kiosk/Main.qml` and the sign-in browser need. Chromium opens
# only while Google or Spotify asks the user to sign in (helpers/browser.py).
APT_PACKAGES = (
    "qml-qt6",
    "qml6-module-qtqml",
    "qml6-module-qtqml-models",
    "qml6-module-qtqml-workerscript",
    "qml6-module-qtquick",
    "qml6-module-qtquick-window",
    "qml6-module-qtquick-shapes",
    "qml6-module-qtwebsockets",
    "qt6-wayland",
    "labwc",
    "wlopm",
    "wvkbd",
    "kanshi",
    "chromium",
)

_PANEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kiosk")

# Where the `qml` tool lives, in the order to look.
_QML_NAMES = ("qml6",)
_QML_PATHS = ("/usr/lib/qt6/bin/qml",)


def debian_version() -> typing.Optional[int]:
    """The Debian release this is (13 on Trixie), or None off Debian."""
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    fields = dict(line.split("=", 1) for line in lines if "=" in line)
    version = fields.get("VERSION_ID", "").strip('"')
    return int(version) if version.isdigit() else None


def _qml_tool() -> typing.Optional[str]:
    for name in _QML_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in _QML_PATHS:
        if os.path.exists(path):
            return path
    return None


def panel_command(api_url: str, windowed: bool = False) -> typing.Optional[typing.List[str]]:
    """The command that shows the panel, talking to the API at `api_url`; None
    when nothing here can run it.

    On the Pi that is Qt's own `qml6`. On a dev machine it is the small PySide6
    launcher (requirements/dev-screen.txt): `pyside6-qml` rejects arguments
    for the app, and the panel needs --api.
    """
    extra = ["--api", api_url] + (["--windowed"] if windowed else [])
    main_qml = os.path.join(_PANEL_DIR, "Main.qml")
    tool = _qml_tool()
    if tool:
        return [tool, main_qml, "--"] + extra
    if importlib.util.find_spec("PySide6") is not None:
        return [sys.executable, os.path.join(_PANEL_DIR, "tools", "dev_panel.py")] + extra
    return None


def installed(package: str) -> bool:
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", package],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.endswith("install ok installed")


def missing_packages() -> typing.List[str]:
    """The apt packages not installed yet. Empty off Debian, where apt is not the way."""
    if not shutil.which("dpkg-query"):
        return []
    return [package for package in APT_PACKAGES if not installed(package)]


def install_command(packages: typing.Iterable[str]) -> str:
    return "sudo apt-get install -y " + " ".join(packages)
