"""
Wony unified entry point.

Usage:
  python wony.py              # default: tray (always-on background mode)
  python wony.py tray         # always-on tray with system tray icon
  python wony.py text         # console text REPL
  python wony.py voice        # console voice mode (Ctrl+L hotkey + optional wake word)
  python wony.py web          # web server only (FastAPI on configured host:port)
  python wony.py doctor       # validate setup and exit
  python wony.py autostart install    # add Windows logon task
  python wony.py autostart uninstall  # remove Windows logon task
  python wony.py autostart status     # show task status

All subcommands that start the assistant brain load Config before importing
modules, preserving the invariant that Config.load() precedes Employer import.
"""
import argparse
import sys


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_tray(args: argparse.Namespace) -> None:
    import os
    import subprocess

    exe = sys.executable
    # If running under python.exe (console), re-spawn under pythonw.exe so the
    # process survives terminal close.
    if os.path.basename(exe).lower() == "python.exe":
        pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if not os.path.isfile(pythonw):
            pythonw = exe.replace("python.exe", "pythonw.exe")
        if os.path.isfile(pythonw):
            script = os.path.abspath(__file__)
            subprocess.Popen(
                [pythonw, script, "tray"],
                cwd=os.path.dirname(script),
                close_fds=True,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            return

    from tray_app import run_tray
    run_tray()


def cmd_text(args: argparse.Namespace) -> None:
    from helpers.config import Config
    Config.load()

    from helpers.bootstrap import BootstrapError, bootstrap
    try:
        employer = bootstrap(audio=False)
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
        except KeyboardInterrupt:
            print("\nExiting program...")
            break


def cmd_voice(args: argparse.Namespace) -> None:
    from helpers.config import Config
    Config.load()

    from helpers.bootstrap import BootstrapError, bootstrap
    try:
        employer = bootstrap(audio=True)
    except BootstrapError as e:
        print(f"\nCannot start: {e}\n")
        sys.exit(1)

    from helpers.recognizer import preload_model
    preload_model()

    from helpers.audio import Audio
    Audio.play_audio_from_file("voice/bot/ready.wav")
    print("\nListening for key combination (Ctrl + L)...")

    import threading
    from pynput import keyboard as pynput_keyboard

    _stop = threading.Event()

    # Start Porcupine wake-word listener (no-op if disabled/missing)
    from helpers.wakeword import WakeWordListener
    ww = WakeWordListener(employer, exit_event=_stop)
    ww.start()

    def _do_speak() -> None:
        from helpers.logger import logger
        logger.log_system_event("hotkey_fired", "ctrl+l")
        print("[voice] Ctrl+L — listening")
        ww.pause()
        try:
            employer.speak()
        except SystemExit:
            _stop.set()
        finally:
            ww.resume()

    def _hotkey_speak() -> None:
        threading.Thread(target=_do_speak, daemon=True).start()

    hotkey_listener = pynput_keyboard.GlobalHotKeys({"<ctrl>+l": _hotkey_speak})
    hotkey_listener.start()

    try:
        while not _stop.wait(timeout=1):
            pass
    except KeyboardInterrupt:
        print("\nExiting program...")
    finally:
        hotkey_listener.stop()
        ww.stop()


def cmd_web(args: argparse.Namespace) -> None:
    from helpers.config import Config
    Config.load()

    from helpers.bootstrap import BootstrapError, bootstrap
    try:
        bootstrap(audio=False, seed_conversation=True)
    except BootstrapError as e:
        print(f"\nCannot start: {e}\n")
        sys.exit(1)

    from helpers.web_app import build_app
    app = build_app()

    import uvicorn
    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    print(f"\nWony Web Server → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port)


def cmd_doctor(args: argparse.Namespace) -> None:
    from helpers.config import Config
    Config.load()

    from helpers.cache import Cache
    Cache.load_values()

    Cache.set_audio(False)

    import dotenv
    dotenv.load_dotenv()

    from modules.doctor import run_doctor
    print(run_doctor(voice_mode=True))


def cmd_autostart(args: argparse.Namespace) -> None:
    from helpers.autostart import install, uninstall, status
    if args.action == "install":
        install()
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
            "Run with no subcommand to start the always-on tray mode.\n"
            "Examples:\n"
            "  python wony.py              # tray (default)\n"
            "  python wony.py text         # console text REPL\n"
            "  python wony.py voice        # voice mode (Ctrl+L + wake word)\n"
            "  python wony.py web          # web server only\n"
            "  python wony.py autostart install"
        ),
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # tray
    p_tray = subparsers.add_parser("tray", help="Always-on tray mode (default)")
    p_tray.set_defaults(func=cmd_tray)

    # text
    p_text = subparsers.add_parser("text", help="Console text REPL")
    p_text.set_defaults(func=cmd_text)

    # voice
    p_voice = subparsers.add_parser("voice", help="Console voice mode")
    p_voice.set_defaults(func=cmd_voice)

    # web
    p_web = subparsers.add_parser("web", help="Web server only")
    p_web.set_defaults(func=cmd_web)

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Validate setup and exit")
    p_doctor.set_defaults(func=cmd_doctor)

    # autostart
    p_auto = subparsers.add_parser("autostart", help="Windows autostart management")
    p_auto.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="install: add logon task; uninstall: remove it; status: show task info",
    )
    p_auto.set_defaults(func=cmd_autostart)

    args = parser.parse_args()

    if args.subcommand is None:
        cmd_tray(args)
        return

    args.func(args)


if __name__ == "__main__":
    main()
