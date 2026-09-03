"""Switching the panel off and on without touching anything behind it.

There is no sleep to fall back on here. No Raspberry Pi suspends to RAM —
`systemctl suspend` answers `Sleep verb "suspend" not supported` on every model
including the 5 — so the only power state between "on" and "off" is the one we
build: the display dark, every process still resident, and a tap on the glass
to bring it back.

Which command does that depends on what is drawing the screen, and Raspberry Pi
OS has changed that twice. Bookworm defaults to Wayland (labwc, or wayfire on
older images), where `xset`, `xrandr` and — on most images — `vcgencmd
display_power` all silently do nothing. So there is no single right command,
only a list to try in order:

  wlopm       Wayland output power management. The output stays configured and
              only its power goes down, so window layout and the touchscreen's
              input mapping survive. First choice when it is installed.
  backlight   /sys/class/backlight/*/bl_power, the official DSI panel's own
              backlight. Nothing above the kernel is involved, so it cannot
              disturb the compositor at all. Needs write access to sysfs.
  vcgencmd    The old firmware call. Still works on some HDMI + KMS setups.
  xset        DPMS, for anyone still running X11.
  wlr-randr   Last, because --off disables the output rather than powering it
              down: labwc's own docs warn that this re-arranges views, and an
              output that is gone may take the touchscreen's input mapping with
              it — which would cost us the tap that wakes it up.

Whichever backend turned the screen off is the one asked to turn it back on, so
a half-applied pair can never leave the panel dark with nothing able to reach
it. And when none of them work — a dev machine, an SSH session with no session
bus — off() says so rather than pretending, and the UI still blacks its own
page out.

None of this is a setting. Which command works is a fact about the device, not
a preference, and asking someone to know the difference between wlopm and
wlr-randr before they can turn their screen off at night is the wrong
question — so the list is tried in order and the answer is discovered.
"""

import glob
import os
import shutil
import subprocess
import typing

# These commands return immediately or not at all; a hang here would block the
# request that asked for sleep.
_TIMEOUT_SECONDS = 5

# Set by the backend that last succeeded, so on() is the mirror of off().
_last_used: str = ""


def _wayland_env() -> typing.Optional[typing.Dict[str, str]]:
    """Environment for a Wayland client, or None if there is no session.

    Wony runs under `systemctl --user`, which is the same user as the desktop
    session but not the same environment: systemd hands a service neither
    WAYLAND_DISPLAY nor XDG_RUNTIME_DIR. Both are recoverable — the runtime dir
    from the uid, the display from whichever socket is sitting in it (labwc
    tends to be wayland-0, wayfire wayland-1, so guessing either would be wrong
    half the time).
    """
    env = dict(os.environ)

    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime or not os.path.isdir(runtime):
        getuid = getattr(os, "getuid", None)
        if getuid is None:
            return None
        runtime = f"/run/user/{getuid()}"
        if not os.path.isdir(runtime):
            return None
        env["XDG_RUNTIME_DIR"] = runtime

    if not env.get("WAYLAND_DISPLAY"):
        sockets = sorted(
            name
            for name in os.listdir(runtime)
            if name.startswith("wayland-") and not name.endswith(".lock")
        )
        if not sockets:
            return None
        env["WAYLAND_DISPLAY"] = sockets[0]

    return env


def _run(command: typing.List[str], env: typing.Optional[typing.Dict[str, str]] = None) -> bool:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# ── backends ────────────────────────────────────────────────────────────────


def _wlopm_available() -> bool:
    return bool(shutil.which("wlopm")) and _wayland_env() is not None


def _wlopm(on: bool) -> bool:
    env = _wayland_env()
    if env is None:
        return False
    return _run(["wlopm", "--on" if on else "--off", "*"], env=env)


def _backlight_files() -> typing.List[str]:
    return sorted(glob.glob("/sys/class/backlight/*/bl_power"))


def _backlight_available() -> bool:
    return any(os.access(path, os.W_OK) for path in _backlight_files())


def _backlight(on: bool) -> bool:
    # FB_BLANK_UNBLANK is 0 and FB_BLANK_POWERDOWN is 4, but the rpi_backlight
    # driver only distinguishes zero from non-zero, and every published recipe
    # for this panel writes 1. Keep to the recipe.
    value = "0" if on else "1"
    wrote = False
    for path in _backlight_files():
        try:
            with open(path, "w", encoding="ascii") as fh:
                fh.write(value)
            wrote = True
        except OSError:
            continue
    return wrote


def _vcgencmd_available() -> bool:
    return bool(shutil.which("vcgencmd"))


def _vcgencmd(on: bool) -> bool:
    # Exits 0 even where it does nothing (Wayland + full KMS), so this is only
    # tried after the backends that can be trusted to have had an effect.
    return _run(["vcgencmd", "display_power", "1" if on else "0"])


def _xset_available() -> bool:
    return bool(shutil.which("xset")) and bool(os.environ.get("DISPLAY"))


def _xset(on: bool) -> bool:
    return _run(["xset", "dpms", "force", "on" if on else "off"])


def _wlr_output() -> str:
    """The output to act on: the first one wlr-randr lists.

    A kiosk has one screen. If it ever has two, both should go dark together
    anyway — and wlopm, which is tried well before this, does exactly that.
    """
    env = _wayland_env()
    if env is None:
        return ""
    try:
        result = subprocess.run(
            ["wlr-randr"], capture_output=True, text=True,
            timeout=_TIMEOUT_SECONDS, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        # Outputs head their own block at column zero; modes are indented.
        if line and not line[0].isspace():
            return line.split()[0]
    return ""


def _wlr_randr_available() -> bool:
    return bool(shutil.which("wlr-randr")) and _wayland_env() is not None


def _wlr_randr(on: bool) -> bool:
    env = _wayland_env()
    output = _wlr_output()
    if env is None or not output:
        return False
    return _run(["wlr-randr", "--output", output, "--on" if on else "--off"], env=env)


class _Backend(typing.NamedTuple):
    name: str
    available: typing.Callable[[], bool]
    apply: typing.Callable[[bool], bool]


_BACKENDS: typing.Tuple[_Backend, ...] = (
    _Backend("wlopm", _wlopm_available, _wlopm),
    _Backend("backlight", _backlight_available, _backlight),
    _Backend("vcgencmd", _vcgencmd_available, _vcgencmd),
    _Backend("xset", _xset_available, _xset),
    _Backend("wlr-randr", _wlr_randr_available, _wlr_randr),
)

_BY_NAME = {backend.name: backend for backend in _BACKENDS}


def probe() -> typing.List[str]:
    """Which backends this device could use, best first. For the doctor."""
    return [backend.name for backend in _BACKENDS if backend.available()]


def set_power(on: bool) -> typing.Tuple[bool, str]:
    """Turn the panel on or off. Returns (worked, backend name or reason).

    Turning it back on is deliberately not limited to the backend that turned
    it off: if that one has since become unavailable — the compositor
    restarted, wlopm was uninstalled — a dark screen with no way back is the
    one failure this module must not have. So the remembered backend goes
    first, then every other one.
    """
    global _last_used

    order = list(_BACKENDS)

    if on and _last_used:
        remembered = _BY_NAME.get(_last_used)
        if remembered is not None:
            order = [remembered] + [b for b in order if b.name != _last_used]

    tried = []
    for backend in order:
        if not backend.available():
            continue
        tried.append(backend.name)
        if backend.apply(on):
            _last_used = backend.name if not on else _last_used
            return True, backend.name

    if tried:
        return False, f"every backend refused ({', '.join(tried)})"
    return False, "no display control on this system"


def off() -> typing.Tuple[bool, str]:
    return set_power(False)


def on() -> typing.Tuple[bool, str]:
    return set_power(True)
