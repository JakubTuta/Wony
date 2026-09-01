"""
Start Wony at boot, via systemd user units.

Two of them, because a kiosk is two things: the assistant, and a browser
pointed at it.

  wony.service        the API and the touch UI's server
  wony-kiosk.service  Chromium, fullscreen, showing that UI

*User* units rather than system ones: Wony runs as the person who owns the
screen, reads their config.yaml and their credentials, and needs no root. The
one catch is that a user manager normally exits when the last session for that
user ends — `loginctl enable-linger` is what keeps it alive on a headless boot,
so install() turns it on.

Usage:
  python wony.py autostart install
  python wony.py autostart install --no-browser
  python wony.py autostart uninstall
  python wony.py autostart status
"""
import os
import shutil
import subprocess
import sys

UNIT_NAME = "wony.service"
BROWSER_UNIT_NAME = "wony-kiosk.service"

# Raspberry Pi OS ships the binary as chromium-browser; most other Debians call
# it chromium. Guessing wrong fails at boot, on a screen nobody is watching.
_CHROMIUM_BINARIES = ("chromium-browser", "chromium", "chromium-browser-stable")


def _unit_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user")


def _unit_path(name: str = UNIT_NAME) -> str:
    return os.path.join(_unit_dir(), name)


def _chromium() -> str:
    """Path to the browser, or "" when none is installed."""
    for name in _CHROMIUM_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _kiosk_url() -> str:
    """Where the browser points.

    Deliberately localhost and not 127.0.0.1. Both are secure contexts, so the
    screen wake lock works either way, but Twitch embeds validate their `parent`
    parameter against the hostname and accept `localhost` as the one non-SSL
    exception. The IP form would quietly rule that out later.
    """
    from helpers.config import Config

    port = int(Config.get("server.port", 8000))
    return f"http://localhost:{port}"


def _wony_script() -> str:
    """Absolute path to wony.py."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wony.py"))


def _python() -> str:
    """The interpreter to run Wony with — the project venv if there is one.

    setup.py installs into that venv, so the unit must name it explicitly: the
    system python systemd would otherwise use has none of the dependencies.
    """
    repo_root = os.path.dirname(_wony_script())
    for venv in ("venv", ".venv"):
        candidate = os.path.join(repo_root, venv, "bin", "python")
        if os.path.isfile(candidate):
            return candidate

    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
        candidate = os.path.join(virtual_env, "bin", "python")
        if os.path.isfile(candidate):
            return candidate

    return sys.executable


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
    )


def _unit_text() -> str:
    python = _python()
    wony = _wony_script()
    workdir = os.path.dirname(wony)

    return f"""[Unit]
Description=Wony personal AI assistant
# Every module Wony has talks to something over the network, so starting
# before there is a route just fills the log with failed health checks.
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={python} {wony} kiosk
Restart=on-failure
RestartSec=10
# systemd gives services no locale, and the startup summary prints non-ASCII.
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=default.target
"""


def _browser_unit_text(chromium: str) -> str:
    return f"""[Unit]
Description=Wony kiosk browser
# Tied to the graphical session: there is nowhere to draw before one exists,
# and the browser should go away with it rather than linger as a zombie.
PartOf=graphical-session.target
After=graphical-session.target {UNIT_NAME}

[Service]
Type=simple
ExecStart={chromium} --kiosk --noerrdialogs --disable-infobars \\
  --disable-session-crashed-bubble --disable-features=TranslateUI \\
  --check-for-update-interval=31536000 --app={_kiosk_url()}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
"""


def install(browser: bool = True) -> None:
    """Write the units, enable them, and start them now."""
    if not _has_systemd():
        return

    os.makedirs(_unit_dir(), exist_ok=True)
    with open(_unit_path(), "w", encoding="utf-8") as fh:
        fh.write(_unit_text())
    print(f"[autostart] Wrote {_unit_path()}")

    if browser:
        _install_browser_unit()

    _systemctl("daemon-reload")

    result = _systemctl("enable", "--now", UNIT_NAME)
    if result.returncode != 0:
        print(f"[autostart] Failed to enable the unit (exit {result.returncode}):")
        print((result.stdout + result.stderr).strip())
        return

    print(f"[autostart] '{UNIT_NAME}' enabled and started.")
    print(f"  Runs at boot: {_python()} {_wony_script()} kiosk")

    if browser and os.path.exists(_unit_path(BROWSER_UNIT_NAME)):
        # Not --now: there may be no graphical session in the shell that ran
        # this (an SSH install is the normal case). It comes up at boot.
        enabled = _systemctl("enable", BROWSER_UNIT_NAME)
        if enabled.returncode == 0:
            print(f"[autostart] '{BROWSER_UNIT_NAME}' enabled — starts with the display.")
            print(f"  Shows: {_kiosk_url()}")
        else:
            print(f"[autostart] Could not enable '{BROWSER_UNIT_NAME}':")
            print((enabled.stdout + enabled.stderr).strip())


def _install_browser_unit() -> None:
    chromium = _chromium()
    if not chromium:
        print(
            "[autostart] No Chromium found, so the browser unit was skipped. "
            "Wony's API will still start at boot.\n"
            "  Fix: sudo apt install chromium-browser, then re-run this command."
        )
        return

    with open(_unit_path(BROWSER_UNIT_NAME), "w", encoding="utf-8") as fh:
        fh.write(_browser_unit_text(chromium))
    print(f"[autostart] Wrote {_unit_path(BROWSER_UNIT_NAME)}")

    # Without lingering, the user manager — and Wony with it — is torn down as
    # soon as nobody is logged in, which on a boot-to-kiosk device is always.
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    linger = subprocess.run(
        ["loginctl", "enable-linger", user] if user else ["loginctl", "enable-linger"],
        capture_output=True,
        text=True,
    )
    if linger.returncode == 0:
        print("  Lingering enabled — Wony starts at boot without anyone logging in.")
    else:
        print("  Could not enable lingering; Wony will only run while you are logged in.")
        print(f"  Fix: sudo loginctl enable-linger {user or '<your-user>'}")


def uninstall() -> None:
    """Stop both units and remove them."""
    if not _has_systemd():
        return

    removed = False
    for name in (BROWSER_UNIT_NAME, UNIT_NAME):
        _systemctl("disable", "--now", name)

        path = _unit_path(name)
        if os.path.exists(path):
            os.unlink(path)
            print(f"[autostart] '{name}' removed.")
            removed = True

    if removed:
        _systemctl("daemon-reload")
    else:
        print("[autostart] Nothing to remove (already removed or never installed).")


def status() -> None:
    """Print each unit's current state."""
    if not _has_systemd():
        return

    if not os.path.exists(_unit_path()):
        print(f"'{UNIT_NAME}' is not installed. Run: python wony.py autostart install")
        return

    for name in (UNIT_NAME, BROWSER_UNIT_NAME):
        if not os.path.exists(_unit_path(name)):
            print(f"\n'{name}' is not installed.")
            continue
        result = _systemctl("status", name, "--no-pager")
        # systemctl status exits non-zero for a stopped unit, which is
        # information, not an error — print whatever it produced either way.
        print((result.stdout + result.stderr).strip())
        print()


def _has_systemd() -> bool:
    if not os.path.isdir("/run/systemd/system"):
        print(
            "[autostart] This machine does not run systemd, so there is no unit "
            "to install. Start Wony with: python wony.py kiosk"
        )
        return False
    return True
