"""
Wony unified entry point.

Usage:
  ./wony.sh              # default: kiosk (web API + touch UI on the display)
  ./wony.sh kiosk        # same, explicitly
  ./wony.sh text         # console text REPL — the way to debug over SSH
  ./wony.sh doctor       # validate setup and exit
  ./wony.sh autostart install    # start Wony + the browser at boot (systemd)
  ./wony.sh autostart uninstall  # remove both units
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
    """Serve the API and the touch UI. This is what runs on the device."""
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

    # The browser unit embeds server.port in the URL it opens.
    Config.load()

    from helpers.autostart import install, status, uninstall

    if args.action == "install":
        install(browser=not args.no_browser)
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
            "Run with no subcommand to start the kiosk.\n"
            "Examples:\n"
            "  ./wony.sh              # kiosk (default)\n"
            "  ./wony.sh text         # console text REPL\n"
            "  ./wony.sh autostart install"
        ),
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    p_kiosk = subparsers.add_parser("kiosk", help="Serve the API and touch UI (default)")
    p_kiosk.set_defaults(func=cmd_kiosk)

    p_text = subparsers.add_parser("text", help="Console text REPL")
    p_text.set_defaults(func=cmd_text)

    p_doctor = subparsers.add_parser("doctor", help="Validate setup and exit")
    p_doctor.set_defaults(func=cmd_doctor)

    p_auto = subparsers.add_parser("autostart", help="Start Wony at boot")
    p_auto.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="install: enable the systemd user units; uninstall: remove them; status: show them",
    )
    p_auto.add_argument(
        "--no-browser",
        action="store_true",
        help="Install only the API unit, not the fullscreen browser (headless device)",
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
