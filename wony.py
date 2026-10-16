"""
Wony unified entry point.

Usage:
  ./wony.sh              # default: kiosk (the assistant and its API, no screen)
  ./wony.sh kiosk        # same, explicitly
  ./wony.sh panel        # the touch panel; needs the assistant running
  ./wony.sh text         # console text REPL — the way to debug over SSH
  ./wony.sh doctor       # validate setup and exit
  ./wony.sh autostart install    # make this device a Wony panel at boot (systemd)
  ./wony.sh autostart uninstall  # undo it and bring the desktop back
  ./wony.sh autostart status     # show unit status

All subcommands that start the assistant brain load Config before importing
modules, preserving the invariant that Config.load() precedes Employer import.
"""

import argparse
import sys

# systemd starts services with no locale set, so stdout defaults to ASCII and
# the first ✓ in the health summary kills the process with UnicodeEncodeError.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Setup gate ────────────────────────────────────────────────────────────────


# What to tell someone whose second copy was refused (helpers/instance.py).
_STOP_HINT = (
    "Stop it first — `systemctl --user stop wony` if it starts at boot, otherwise "
    "close the terminal it runs in — then try again."
)


def _require_setup() -> None:
    """Block the app until setup.py has run.

    setup.py writes .wony_setup on success, recording the interpreter it set up.
    We refuse to start if that marker is missing, or if the app is being launched
    with a different interpreter than the one set up (e.g. system python when the
    packages live in the project venv) — which would otherwise fail with cryptic
    ImportErrors.
    """
    import json
    import os

    root = os.path.dirname(os.path.abspath(__file__))
    marker = os.path.join(root, ".wony_setup")
    setup_cmd = "./wony.sh setup"

    if not os.path.exists(marker):
        print(
            "\nWony is not set up yet.\n"
            f"Run the setup script first:\n\n    {setup_cmd}\n\n"
            "It installs dependencies, creates .env / config.yaml, and unlocks the app.\n"
        )
        sys.exit(1)

    try:
        # utf-8-sig: tolerate a BOM (some editors write one).
        with open(marker, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception:
        data = {}

    want_dir = data.get("python_dir")
    have_dir = os.path.dirname(os.path.abspath(sys.executable))
    if want_dir and os.path.normcase(os.path.abspath(want_dir)) != os.path.normcase(
        have_dir
    ):
        want_py = data.get("python", os.path.join(want_dir, "python"))
        if os.path.exists(want_py):
            # Run by hand with another Python (`python3 wony.py ...`): switch to
            # the one setup.py actually installed everything for — refusing just
            # moves the same cryptic ImportError one step later. execv never
            # returns.
            os.execv(want_py, [want_py, os.path.abspath(__file__)] + sys.argv[1:])
            return
        print(
            "\nWrong Python interpreter for Wony.\n"
            f"Setup installed everything for:\n    {want_py}\n"
            f"but you launched with:\n    {sys.executable}\n\n"
            "That interpreter no longer exists. Re-run setup.py to target this one.\n"
        )
        sys.exit(1)


# ── Subcommand handlers ───────────────────────────────────────────────────────


def cmd_kiosk(args: argparse.Namespace) -> None:
    """Run the assistant and serve its API. The touch panel (`panel`) is a
    separate process that talks to it, so a crash on screen never stops timers."""
    from helpers.config import Config

    Config.load()

    from helpers import instance

    instance.claim_or_exit(_STOP_HINT)

    from helpers.bootstrap import BootstrapError, bootstrap

    try:
        bootstrap(seed_conversation=True)
    except BootstrapError as e:
        print(f"\nCannot start: {e}\n")
        sys.exit(1)

    from helpers.web_app import build_app

    app = build_app()

    import uvicorn

    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    print(f"\nWony → http://{host}:{port}\n")
    # Only one Wony may hold the port. On the device systemd enforces that;
    # everywhere else uvicorn's own bind failure is the check.
    uvicorn.run(app, host=host, port=port)


def cmd_panel(args: argparse.Namespace) -> None:
    """Show the touch panel and stay until it closes."""
    import os

    from helpers import screen
    from helpers.config import Config

    Config.load()

    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    # A server bound to every interface is still reachable on loopback.
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    command = screen.panel_command(f"http://{host}:{port}", windowed=args.windowed)
    if command is None:
        print(
            "\nThe touch panel needs Qt's QML runtime, which is not installed.\n"
            "Run './wony.sh setup' to install it, or by hand:\n\n"
            f"    {screen.install_command(screen.APT_PACKAGES)}\n"
        )
        sys.exit(1)
    # The panel replaces this process: under labwc's session command that makes
    # the panel the session, so closing it ends the session and systemd restarts it.
    os.execv(command[0], command)


def cmd_text(args: argparse.Namespace) -> None:
    from helpers.config import Config

    Config.load()

    from helpers import instance

    instance.claim_or_exit(_STOP_HINT)

    from helpers.bootstrap import BootstrapError, bootstrap

    try:
        employer = bootstrap()
    except BootstrapError as e:
        print(f"\nCannot start: {e}\n")
        sys.exit(1)

    from helpers.logger import logger

    print("Listening for text input...")
    while True:
        try:
            user_input = input("\nEnter a command: ")
            logger.log_user_input(user_input, "text")
            employer.job_on_command(user_input)
        except (KeyboardInterrupt, EOFError):
            # EOFError: Ctrl+D, or stdin closing on piped input.
            print("\nExiting program...")
            break


def cmd_doctor(args: argparse.Namespace) -> None:
    from helpers.config import Config

    Config.load()

    from helpers.cache import Cache

    Cache.load_values()

    import dotenv

    dotenv.load_dotenv()

    from modules.doctor import run_doctor

    print(run_doctor())


def cmd_autostart(args: argparse.Namespace) -> None:
    from helpers.config import Config

    Config.load()

    from helpers.autostart import install, status, uninstall

    if args.action == "install":
        install(screen=not args.no_screen)
    elif args.action == "uninstall":
        uninstall()
    elif args.action == "status":
        status()


# ── Argument parser ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wony",
        description="Wony personal AI assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run with no subcommand to start the assistant.\n"
            "Examples:\n"
            "  ./wony.sh              # the assistant (default)\n"
            "  ./wony.sh panel        # the touch panel\n"
            "  ./wony.sh text         # console text REPL\n"
            "  ./wony.sh autostart install"
        ),
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    p_kiosk = subparsers.add_parser("kiosk", help="Run the assistant and its API (default)")
    p_kiosk.set_defaults(func=cmd_kiosk)

    p_panel = subparsers.add_parser(
        "panel", help="Show the touch panel (the assistant must be running)"
    )
    p_panel.add_argument(
        "--windowed",
        action="store_true",
        help="A 1280x800 window instead of fullscreen, for trying it on a desktop",
    )
    p_panel.set_defaults(func=cmd_panel)

    p_text = subparsers.add_parser("text", help="Console text REPL")
    p_text.set_defaults(func=cmd_text)

    p_doctor = subparsers.add_parser("doctor", help="Validate setup and exit")
    p_doctor.set_defaults(func=cmd_doctor)

    p_auto = subparsers.add_parser("autostart", help="Turn this device into a Wony panel at boot")
    p_auto.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="install: start Wony and its screen at boot; uninstall: undo it; status: show it",
    )
    p_auto.add_argument(
        "--no-screen",
        action="store_true",
        help="Start only the assistant at boot, not the touch panel (headless device)",
    )
    p_auto.set_defaults(func=cmd_autostart)

    args = parser.parse_args()

    # Gate everything that starts the assistant. `doctor` stays open so users can
    # still diagnose, but it is not the app itself.
    if args.subcommand != "doctor":
        _require_setup()

    if args.subcommand is None:
        cmd_kiosk(args)
        return

    args.func(args)


if __name__ == "__main__":
    main()
