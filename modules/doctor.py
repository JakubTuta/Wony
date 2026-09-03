import os
import platform
import shutil

from helpers.decorators import capture_response
from helpers.paths import repo_path
from helpers.registry import register_job
from helpers.requirements import Requirement, evaluate

_NON_MODULE_CHECKS = [
    (
        "Semantic memory",
        Requirement(
            pip_modules=["fastembed"],
            setup_hint="pip install -r requirements/semantic.txt",
        ),
    ),
]

# Below this, the device is one browser tab away from the OOM killer.
_MIN_FREE_RAM_MB = 250

# Enough headroom for logs, the SQLite database, and a pip upgrade.
_MIN_FREE_DISK_MB = 500


def _module_checks() -> list:
    """(label, Requirement) for every module that declared one, plus the
    non-module features. Modules are read from the registry so this never
    drifts from what the modules themselves require."""
    from helpers.registry import ServiceRegistry

    checks = [
        (name, req)
        for name, req in sorted(ServiceRegistry.get_module_requirements().items())
    ]
    checks += list(_NON_MODULE_CHECKS)
    return checks


def run_doctor() -> str:
    """Run all setup checks and return a formatted report."""
    from helpers.model import describe_readiness

    lines = ["Setup diagnostics:"]

    if os.path.exists(repo_path(".env")):
        lines.append("  ✓ .env file found.")
    else:
        lines.append("  ✗ .env file missing — create it in the project root.")
        lines.append("    Add at least one of: ANTHROPIC_API_KEY, GEMINI_API_KEY")

    if os.path.exists(repo_path("config.yaml")):
        lines.append("  ✓ config.yaml found.")
    else:
        lines.append(
            "  ! config.yaml missing — using config.example.yaml defaults.\n"
            "    Copy it: cp config.example.yaml config.yaml"
        )

    ai_ok, ai_msg = describe_readiness()
    prefix = "✓" if ai_ok else "✗"
    lines.append(f"  {prefix} AI: {ai_msg}")

    for label, req in _module_checks():
        ok, reason = evaluate(req)
        if ok:
            lines.append(f"  ✓ {label}")
        else:
            lines.append(f"  ✗ {label}: {reason}")
            if req.setup_hint:
                lines.append(f"    Fix: {req.setup_hint}")

    lines.append(_screen_line())

    lines.append(_sleep_line())

    raspotify = _raspotify_line()
    if raspotify:
        lines.append(raspotify)

    lines.extend(_platform_checks())

    return "\n".join(lines)


def _screen_line() -> str:
    """The touch UI is a built bundle, and forgetting to build it is silent —
    the API answers fine and the screen shows a bare 404."""
    if os.path.isfile(repo_path(os.path.join("kiosk", "dist", "index.html"))):
        return "  ✓ Screen bundle built."
    return (
        "  ✗ Screen bundle missing — the API works but the display will be blank.\n"
        "    Fix: cd kiosk && npm install && npm run build"
    )


def _sleep_line() -> str:
    """Whether the Sleep tile will actually darken this panel.

    Worth its own line because the failure is invisible until someone tries it
    at bedtime: the page goes black, the backlight stays on all night, and
    nothing anywhere says why.
    """
    from helpers import display

    usable = display.probe()
    if usable:
        return f"  ✓ Sleep: can switch the panel off with {usable[0]}."

    return (
        "  ! Sleep: nothing here can switch the panel off, so sleeping will only\n"
        "    black out the page. On Raspberry Pi OS Bookworm the screen runs on\n"
        "    Wayland, where xset and vcgencmd do nothing.\n"
        "    Fix: sudo apt install wlopm — and run Wony in the same session as "
        "the desktop."
    )


def _raspotify_line() -> str:
    """Only meaningful once Spotify is on and this device is meant to play the
    music itself. A dead raspotify looks exactly like 'no active device'."""
    from helpers.config import Config

    if not Config.is_module_enabled("spotify"):
        return ""
    if shutil.which("systemctl") is None:
        return ""

    import subprocess

    try:
        state = subprocess.run(
            ["systemctl", "is-active", "raspotify"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""

    if state == "active":
        return "  ✓ raspotify running — this device is a Spotify Connect target."
    if state == "inactive" or state == "failed":
        return (
            f"  ! raspotify is {state}. Spotify control still works; this device "
            "just will not play the music itself.\n"
            "    Fix: sudo systemctl enable --now raspotify"
        )
    # "unknown" — not installed. Not a fault: playing on another speaker is fine.
    return ""


def _platform_checks() -> list:
    """What actually goes wrong on a small single-board machine: a 32-bit
    userland with no wheels for it, and running out of RAM or disk."""
    lines = ["\n  Device:"]

    machine = platform.machine()
    bits = platform.architecture()[0]
    lines.append(f"    {platform.system()} {platform.release()} on {machine} ({bits})")

    if machine in ("armv6l", "armv7l") or bits == "32bit":
        lines.append(
            "  ✗ 32-bit userland. Semantic memory needs onnxruntime, which "
            "publishes no 32-bit ARM wheels."
        )
        lines.append("    Fix: reinstall with the 64-bit build of Raspberry Pi OS.")

    lines.append(_ram_line())
    lines.append(_disk_line())

    return lines


def _ram_line() -> str:
    """Read available memory from /proc/meminfo — no psutil dependency for one number."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    free_mb = int(line.split()[1]) // 1024
                    break
            else:
                return "    ! Could not read MemAvailable from /proc/meminfo."
    except OSError:
        return "    (memory check skipped — no /proc/meminfo on this system)"

    if free_mb < _MIN_FREE_RAM_MB:
        return (
            f"  ✗ Only {free_mb} MB RAM available (want at least "
            f"{_MIN_FREE_RAM_MB} MB). Close something, or disable semantic memory."
        )
    return f"    ✓ {free_mb} MB RAM available."


def _disk_line() -> str:
    try:
        free_mb = shutil.disk_usage(repo_path(".")).free // (1024 * 1024)
    except OSError as e:
        return f"    ! Could not check free disk space: {e}"

    if free_mb < _MIN_FREE_DISK_MB:
        return (
            f"  ✗ Only {free_mb} MB free on the Wony partition (want at least "
            f"{_MIN_FREE_DISK_MB} MB)."
        )
    return f"    ✓ {free_mb} MB free disk."


@register_job
@capture_response
def check_setup() -> str:
    """
    [SYSTEM DIAGNOSTICS JOB] Validates the full assistant setup and prints a ✓/✗ checklist.
    Checks .env, config.yaml, AI provider, each integration's requirements, and
    whether the device has the architecture, memory and disk space Wony needs.
    Prints exactly what to fix for anything that is missing or broken.

    Returns:
        str: Full diagnostics report with ✓/✗ per component and fix instructions.
    """
    return run_doctor()
