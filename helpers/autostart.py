"""
Turn this device into a Wony panel: Wony and its screen start at boot.

Two systemd units, because a panel is two things: the assistant, and the screen
that shows it.

  wony.service         the assistant and its API. A *user* unit: Wony runs as
                       the person who owns the screen, reads their config.yaml
                       and credentials, and needs no root. `loginctl
                       enable-linger` keeps the user manager alive on a boot
                       nobody logs in to.
  wony-panel.service   a bare labwc session whose only program is the touch
                       panel (`wony.py panel`). A *system* unit, because it
                       takes the display: it is installed as the display
                       manager, so no desktop starts. Closing the panel ends
                       the session and systemd starts it again.

Installing it needs sudo; every sudo command is printed before it runs.
uninstall() puts the desktop back exactly as install() found it.

Usage:
  ./wony.sh autostart install
  ./wony.sh autostart install --no-screen     # assistant only, headless device
  ./wony.sh autostart uninstall
  ./wony.sh autostart status
"""
import getpass
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import typing

UNIT_NAME = "wony.service"
PANEL_UNIT_NAME = "wony-panel.service"
# Written by older versions: Chromium in kiosk mode. Removed on install/uninstall.
LEGACY_BROWSER_UNIT_NAME = "wony-kiosk.service"

_SYSTEM_UNIT_DIR = "/etc/systemd/system"
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# What the display looked like before install(), so uninstall() can restore it.
_STATE_FILE = os.path.join(_REPO_ROOT, ".wony_autostart.json")


def _unit_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user")


def _unit_path(name: str = UNIT_NAME) -> str:
    return os.path.join(_unit_dir(), name)


def _panel_unit_path() -> str:
    return os.path.join(_SYSTEM_UNIT_DIR, PANEL_UNIT_NAME)


def _wony_script() -> str:
    """Absolute path to wony.py."""
    return os.path.join(_REPO_ROOT, "wony.py")


def _python() -> str:
    """The interpreter to run Wony with — the project venv if there is one.

    setup.py installs into that venv, so the unit must name it explicitly: the
    system python systemd would otherwise use has none of the dependencies.
    """
    for venv in ("venv", ".venv"):
        candidate = os.path.join(_REPO_ROOT, venv, "bin", "python")
        if os.path.isfile(candidate):
            return candidate

    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
        candidate = os.path.join(virtual_env, "bin", "python")
        if os.path.isfile(candidate):
            return candidate

    return sys.executable


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True)


def _user_systemctl(*args: str) -> subprocess.CompletedProcess:
    return _systemctl("--user", *args)


def _sudo(*command: str) -> bool:
    """Run a command as root, showing it first and leaving the terminal to sudo
    for its password prompt."""
    print(f"[autostart]   sudo {shlex.join(command)}")
    try:
        return subprocess.run(["sudo", *command]).returncode == 0
    except OSError:
        return False


def _systemd_quote(argument: str) -> str:
    """One word of an ExecStart line: quoted, with systemd's escapes."""
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


# ── the assistant (user unit) ─────────────────────────────────────────────────


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


def _install_assistant() -> bool:
    os.makedirs(_unit_dir(), exist_ok=True)
    with open(_unit_path(), "w", encoding="utf-8") as fh:
        fh.write(_unit_text())
    print(f"[autostart] Wrote {_unit_path()}")

    # Without lingering, the user manager — and Wony with it — is torn down as
    # soon as nobody is logged in, which on a boot-to-panel device is always.
    user = getpass.getuser()
    linger = subprocess.run(["loginctl", "enable-linger", user], capture_output=True, text=True)
    if linger.returncode == 0:
        print("  Lingering enabled — Wony starts at boot without anyone logging in.")
    else:
        print("  Could not enable lingering; Wony will only run while you are logged in.")
        print(f"  Fix: sudo loginctl enable-linger {user}")

    _user_systemctl("daemon-reload")
    result = _user_systemctl("enable", "--now", UNIT_NAME)
    if result.returncode != 0:
        print(f"[autostart] Failed to enable the unit (exit {result.returncode}):")
        print((result.stdout + result.stderr).strip())
        return False

    print(f"[autostart] '{UNIT_NAME}' enabled and started.")
    print(f"  Runs at boot: {_python()} {_wony_script()} kiosk")
    return True


def _remove_legacy_browser_unit() -> None:
    path = _unit_path(LEGACY_BROWSER_UNIT_NAME)
    if not os.path.exists(path):
        return
    _user_systemctl("disable", "--now", LEGACY_BROWSER_UNIT_NAME)
    os.unlink(path)
    _user_systemctl("daemon-reload")
    print(f"[autostart] Removed the old '{LEGACY_BROWSER_UNIT_NAME}' (Chromium is no longer the screen).")


# ── the screen (system unit) ──────────────────────────────────────────────────


def _uid() -> int:
    """The owner's user id, for their runtime directory (/run/user/<uid>). Not
    systemd's %U: in a system unit that is root's, not the service's User=."""
    return os.getuid() if hasattr(os, "getuid") else 1000


def _panel_unit_text(user: str) -> str:
    # `wony.py session` builds labwc's config (helpers/session.py) and becomes
    # labwc, with the panel as its one program. labwc exits when the panel does,
    # so a crashed or closed panel ends the session and Restart= brings it back.
    exec_start = " ".join(_systemd_quote(word) for word in (_python(), _wony_script(), "session"))
    return f"""[Unit]
Description=Wony touch panel
# Takes tty1 and the display, like a display manager does.
ConditionPathExists=/dev/tty0
After=systemd-user-sessions.service plymouth-quit-wait.service getty@tty1.service systemd-logind.service
Wants=dbus.socket systemd-logind.service
Conflicts=getty@tty1.service
Before=graphical.target
# A panel that cannot start (a missing package) should not spin forever.
StartLimitIntervalSec=120
StartLimitBurst=20

[Service]
Type=simple
User={user}
ExecStart={exec_start}
Restart=always
RestartSec=3
# A logind session on seat0 gives labwc the display and the touchscreen.
PAMName=login
Environment=XDG_SESSION_TYPE=wayland
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{_uid()}/bus
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
UtmpIdentifier=tty1
UtmpMode=user

[Install]
WantedBy=graphical.target
# Installed as the display manager: no desktop starts beside it.
Alias=display-manager.service
"""


def _current_display_manager() -> str:
    """The unit that is the display manager now (lightdm.service on Raspberry Pi
    OS), or "" when there is none or it is already ours."""
    result = _systemctl("show", "display-manager.service", "--property=Id,LoadState")
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    unit = fields.get("Id", "")
    if fields.get("LoadState") != "loaded" or unit in ("", "display-manager.service", PANEL_UNIT_NAME):
        return ""
    return unit


def _default_target() -> str:
    return _systemctl("get-default").stdout.strip() or "graphical.target"


def _read_state() -> typing.Dict[str, str]:
    try:
        with open(_STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_state(state: typing.Dict[str, str]) -> None:
    with open(_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def _screen_ready() -> typing.Optional[str]:
    """Why the screen cannot be installed yet, or None when it can."""
    from helpers import screen

    if screen.panel_command("") is None or not shutil.which("labwc"):
        missing = screen.missing_packages() or list(screen.APT_PACKAGES)
        return (
            "The screen's packages are not installed. Run ./wony.sh setup, or:\n"
            f"    {screen.install_command(missing)}"
        )
    return None


def _install_panel() -> None:
    problem = _screen_ready()
    if problem:
        print(f"[autostart] Skipped the screen. {problem}\n  Wony's assistant will still start at boot.")
        return

    user = getpass.getuser()
    print(
        "\n[autostart] Making this device a Wony panel. The desktop will no longer start at boot;\n"
        "  './wony.sh autostart uninstall' brings it back. This needs sudo:"
    )

    # Remember how to undo it, once: a second install must not record our own
    # panel as "the desktop".
    state = _read_state()
    if not state:
        state = {"display_manager": _current_display_manager(), "default_target": _default_target()}
        _write_state(state)

    with tempfile.NamedTemporaryFile("w", suffix=".service", delete=False, encoding="utf-8") as tmp:
        tmp.write(_panel_unit_text(user))
    try:
        installed = _sudo("install", "-m", "0644", tmp.name, _panel_unit_path())
    finally:
        os.unlink(tmp.name)
    if not installed or not _sudo("systemctl", "daemon-reload"):
        print("[autostart] Could not install the screen's unit; the desktop is unchanged.")
        return

    # The display-manager alias can only belong to one unit, so the desktop's goes first.
    manager = state.get("display_manager", "")
    if manager and not _sudo("systemctl", "disable", manager):
        print(f"[autostart] Could not disable {manager}; the desktop is unchanged.")
        return
    if not _sudo("systemctl", "enable", PANEL_UNIT_NAME) or not _sudo("systemctl", "set-default", "graphical.target"):
        print("[autostart] Could not enable the screen's unit; putting the desktop back.")
        if manager:
            _sudo("systemctl", "enable", manager)
        return

    print(f"[autostart] '{PANEL_UNIT_NAME}' enabled — the panel comes up at the next boot.")
    print("  Reboot to start it. (Starting it now would fight the desktop for the display.)")
    print("  Already running it? Apply this with: sudo systemctl restart wony-panel")


def _uninstall_panel() -> bool:
    """Remove the screen's unit and restore the desktop. True if anything was done."""
    if not os.path.exists(_panel_unit_path()):
        return False

    print("[autostart] Removing the screen and restoring the desktop. This needs sudo:")
    state = _read_state()

    _sudo("systemctl", "disable", PANEL_UNIT_NAME)
    _sudo("rm", "-f", _panel_unit_path())
    _sudo("systemctl", "daemon-reload")

    manager = state.get("display_manager", "")
    if manager:
        _sudo("systemctl", "enable", manager)
    target = state.get("default_target", "")
    if target:
        _sudo("systemctl", "set-default", target)
    if not state:
        print("  No record of the old display manager. If the desktop does not come back, run:")
        print("    sudo systemctl enable lightdm && sudo systemctl set-default graphical.target")

    if os.path.exists(_STATE_FILE):
        os.unlink(_STATE_FILE)
    print(f"[autostart] '{PANEL_UNIT_NAME}' removed. Reboot to get the desktop back.")
    return True


# ── commands ──────────────────────────────────────────────────────────────────


def install(screen: bool = True) -> None:
    """Install the assistant's unit and, unless `screen` is false, the panel's."""
    if not _has_systemd():
        return

    _remove_legacy_browser_unit()
    if _install_assistant() and screen:
        _install_panel()


def uninstall() -> None:
    """Remove both units and put the desktop back."""
    if not _has_systemd():
        return

    removed = _uninstall_panel()

    for name in (LEGACY_BROWSER_UNIT_NAME, UNIT_NAME):
        _user_systemctl("disable", "--now", name)

        path = _unit_path(name)
        if os.path.exists(path):
            os.unlink(path)
            print(f"[autostart] '{name}' removed.")
            removed = True

    if removed:
        _user_systemctl("daemon-reload")
    else:
        print("[autostart] Nothing to remove (already removed or never installed).")


def status() -> None:
    """Print each unit's current state."""
    if not _has_systemd():
        return

    if not os.path.exists(_unit_path()):
        print(f"'{UNIT_NAME}' is not installed. Run: ./wony.sh autostart install")
        return

    result = _user_systemctl("status", UNIT_NAME, "--no-pager")
    # systemctl status exits non-zero for a stopped unit, which is information,
    # not an error — print whatever it produced either way.
    print((result.stdout + result.stderr).strip())
    print()

    if not os.path.exists(_panel_unit_path()):
        print(f"'{PANEL_UNIT_NAME}' is not installed: this device boots to its normal desktop.")
        return
    result = _systemctl("status", PANEL_UNIT_NAME, "--no-pager")
    print((result.stdout + result.stderr).strip())
    manager = _read_state().get("display_manager", "")
    if manager:
        print(f"\nThe desktop ({manager}) comes back with: ./wony.sh autostart uninstall")


def screen_enabled() -> bool:
    """Whether the panel's unit is installed and enabled. For the doctor."""
    return os.path.exists(_panel_unit_path()) and _systemctl("is-enabled", PANEL_UNIT_NAME).returncode == 0


def _has_systemd() -> bool:
    if not os.path.isdir("/run/systemd/system"):
        print(
            "[autostart] This machine does not run systemd, so there is no unit "
            "to install. Start Wony with: ./wony.sh kiosk"
        )
        return False
    return True
