"""
Always-on tray host for Wony.

Run with pythonw.exe for no console window:
  pythonw wony.py tray   (or: pythonw tray_app.py)

Threading model:
  MAIN thread  — pystray Icon.run() (required by pystray on Windows)
  daemon thread — uvicorn web server (WebServerController)
  daemon thread — Porcupine wake-word listener (WakeWordListener)
  daemon threads — pollers / scheduler (BackgroundJobs / APScheduler)
"""
import atexit
import os
import socket
import sys
import typing

# pythonw.exe has no console; redirect stdout/stderr to devnull so print()
# calls from modules don't raise AttributeError.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

_TRAY_LOCK_PORT = 10923  # ephemeral port used as single-instance mutex
_lock_socket: typing.Optional[socket.socket] = None


def _try_acquire_instance_lock() -> bool:
    global _lock_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", _TRAY_LOCK_PORT))
        _lock_socket = sock
        return True
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        return False


def _make_icon_image():
    """Generate a simple tray icon using Pillow (already in core.txt)."""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(100, 149, 237, 255))
    # Small white dot in center for visual interest
    cx = size // 2
    draw.ellipse([cx - 8, cx - 8, cx + 8, cx + 8], fill=(255, 255, 255, 200))
    return img


def _load_icon_image():
    assets_ico = os.path.join(os.path.dirname(__file__), "assets", "wony.ico")
    if os.path.isfile(assets_ico):
        try:
            from PIL import Image
            return Image.open(assets_ico)
        except Exception:
            pass
    return _make_icon_image()


def run_tray() -> None:
    try:
        import pystray
    except ImportError:
        print(
            "pystray not installed. Run: pip install -r requirements/tray.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    # Single-instance guard
    if not _try_acquire_instance_lock():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                "Wony is already running in the system tray.",
                "Wony",
                0x40,  # MB_ICONINFORMATION
            )
        except Exception:
            pass
        return

    # Determine run flags from config (must call Config.load before import Employer)
    from helpers.config import Config
    Config.load()

    audio_mode = True  # tray is always voice-response mode (same feedback loop as voice mode)

    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    notify_on_ready = bool(Config.get("tray.notify_on_ready", True))
    open_browser_on_start = bool(Config.get("tray.open_browser_on_start", False))

    # Bootstrap: starts Employer + registers atexit(shutdown)
    from helpers.bootstrap import BootstrapError, bootstrap
    try:
        employer = bootstrap(
            audio=audio_mode,
            install_signal_handlers=False,
            seed_conversation=True,
            quiet=True,
        )
    except BootstrapError as e:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                f"Wony failed to start:\n\n{e}\n\nCheck your .env and config.yaml.",
                "Wony — Startup Error",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        return

    # Hook the exit job so "exit" spoken via wake word properly tears down the tray
    from modules.employer import Employer

    # Build web server (app is built now; employer + jobs are registered)
    from helpers.web_app import build_app
    app = build_app()
    from helpers.web_runner import WebServerController
    web = WebServerController(app, host, port)

    # Build wake-word listener (no-op if disabled or deps missing)
    from helpers.wakeword import WakeWordListener
    wakeword = WakeWordListener(employer)

    if audio_mode or wakeword._enabled:
        from helpers.recognizer import preload_model
        preload_model()

    # Build controller
    from helpers.assistant_controller import AssistantController
    controller = AssistantController(employer, web, wakeword)

    # Build tray icon
    icon_image = _load_icon_image()
    assistant_name = Config.get("assistant.name", "Wony")

    # Forward references for closures
    _icon_ref: typing.List[typing.Any] = [None]

    def _on_open_web(icon, item) -> None:
        import webbrowser
        controller.ensure_web()
        webbrowser.open(f"http://{host}:{port}")

    def _on_toggle(icon, item) -> None:
        if controller.is_running():
            controller.stop()
        else:
            controller.start()
        icon.update_menu()

    def _toggle_label(item) -> str:
        return "Stop" if controller.is_running() else "Start"

    def _on_exit(icon, item) -> None:
        controller.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open in web", _on_open_web),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_toggle_label, _on_toggle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", _on_exit),
    )

    icon = pystray.Icon(
        name=assistant_name,
        icon=icon_image,
        title=assistant_name,
        menu=menu,
    )
    _icon_ref[0] = icon

    # Hook the exit job so sys.exit(0) from "exit" command shuts down gracefully
    def _tray_exit_hook() -> None:
        controller.shutdown()
        if _icon_ref[0] is not None:
            _icon_ref[0].stop()

    Employer.set_exit_hook(_tray_exit_hook)

    # Ensure icon.stop() fires on process exit (e.g., sys.exit from a thread)
    atexit.register(lambda: _icon_ref[0].stop() if _icon_ref[0] else None)

    # Start everything
    controller.start()

    if notify_on_ready:
        try:
            icon.notify(f"{assistant_name} is running.", title=assistant_name)
        except Exception:
            pass

    if open_browser_on_start:
        try:
            import webbrowser
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    # Block main thread on the tray icon (pystray requirement on Windows)
    icon.run()


if __name__ == "__main__":
    run_tray()
