"""
Always-on tray host for Wony.

Run with pythonw.exe for no console window:
  pythonw wony.py tray   (or: pythonw tray_app.py)

Threading model:
  MAIN thread  — pystray Icon.run() (required by pystray on Windows)
  daemon thread — uvicorn web server (WebServerController)
  daemon thread — openWakeWord wake-word listener (WakeWordListener)
  daemon thread — global push-to-talk hotkey listener (pynput, optional)
  daemon threads — pollers / scheduler (BackgroundJobs / APScheduler)
"""

import atexit
import os
import socket
import sys
import threading
import typing

# pythonw.exe has no console; redirect stdout/stderr to a UTF-8 null sink so
# print() calls don't raise AttributeError or UnicodeEncodeError.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_INSTANCE_NAME = "WonyAssistantTraySingleInstance"
_lock_handle: typing.Any = None
_lock_socket: typing.Optional[socket.socket] = None


def _try_acquire_instance_lock() -> bool:
    """True if this process is the only tray instance.

    A named mutex, not a bound port: any unrelated program holding the port
    would otherwise look like a running Wony and block startup entirely.
    """
    global _lock_handle, _lock_socket

    if sys.platform == "win32":
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        # use_last_error so the error code belongs to CreateMutexW, and
        # c_void_p so a 64-bit handle is not truncated on the way back.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        handle = kernel32.CreateMutexW(None, False, _INSTANCE_NAME)
        if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _lock_handle = handle  # released when the process exits
        return True

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind("\0" + _INSTANCE_NAME)  # abstract namespace: no file to clean up
        _lock_socket = sock
        return True
    except OSError:
        sock.close()
        return False


_STATE_COLORS = {
    "idle": (100, 149, 237),  # cornflower blue
    "listening": (72, 199, 116),  # green
    "thinking": (255, 193, 7),  # amber
    "speaking": (167, 80, 214),  # purple
}


def _make_icon_image(state: str = "idle"):
    """Generate a tray icon with a color matching the assistant state."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r, g, b = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
    draw.ellipse([4, 4, size - 4, size - 4], fill=(r, g, b, 255))
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
    return _make_icon_image("idle")


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

    audio_mode = (
        True  # tray is always voice-response mode (same feedback loop as voice mode)
    )

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
    # Build web server (app is built now; employer + jobs are registered)
    from helpers.web_app import build_app
    from modules.employer import Employer

    app = build_app()
    from helpers.web_runner import WebServerController

    web = WebServerController(app, host, port)

    # Build wake-word listener (no-op if disabled or deps missing)
    from helpers.wakeword import WakeWordListener

    wakeword = WakeWordListener(employer)

    if (audio_mode or wakeword._enabled) and Config.get("models.preload", False):
        from helpers.audio import preload_tts
        from helpers.recognizer import preload_model

        preload_model()
        preload_tts()

    # Build controller
    from helpers.assistant_controller import AssistantController

    controller = AssistantController(employer, web, wakeword)

    # Build tray icon
    icon_image = _load_icon_image()
    assistant_name = Config.get("assistant.name", "Wony")

    # Forward references for closures
    _icon_ref: typing.List[typing.Any] = [None]
    _current_state: typing.List[str] = ["idle"]

    # Defined early (before the menu, which references it) so both the tray's
    # own exit path and the push-to-talk worker below can call it.
    def _tray_exit_hook() -> None:
        if _icon_ref[0] is not None:
            _icon_ref[0].stop()

    Employer.set_exit_hook(_tray_exit_hook)

    # ── Push-to-talk: tray "Listen now" menu item + global hotkey ───────────
    from helpers.push_to_talk import do_speak, hotkey_label, start_hotkey, stop_hotkey

    def _do_listen_now() -> None:
        do_speak(employer, wakeword, _tray_exit_hook, "listen_now")

    def _on_listen_now(icon, item) -> None:
        threading.Thread(target=_do_listen_now, daemon=True, name="listen-now").start()

    _hotkey_listener_ref: typing.List[typing.Any] = [None]

    def _start_hotkey() -> None:
        def _fire() -> None:
            threading.Thread(
                target=_do_listen_now, daemon=True, name="listen-now-hotkey"
            ).start()

        _hotkey_listener_ref[0] = start_hotkey(_fire)

    def _stop_hotkey() -> None:
        stop_hotkey(_hotkey_listener_ref[0])
        _hotkey_listener_ref[0] = None

    def _open_web() -> None:
        import webbrowser

        controller.ensure_web()
        webbrowser.open(f"http://{host}:{port}")

    def _on_open_web(icon, item) -> None:
        _open_web()

    def _on_settings(icon, item) -> None:
        # Settings live on the web page; the tray menu is just the shortcut.
        _open_web()

    def _on_check_updates(icon, item) -> None:
        def _check() -> None:
            from helpers.updates import check

            try:
                message = check()
            except Exception as e:
                message = f"Update check failed: {e}"
            try:
                icon.notify(message[:250], title=f"{assistant_name} — updates")
            except Exception:
                print(message)

        threading.Thread(target=_check, daemon=True, name="update-check").start()

    def _on_toggle(icon, item) -> None:
        if controller.is_running():
            controller.stop()
        else:
            controller.start()
        icon.update_menu()

    def _on_stop_speaking(icon, item) -> None:
        from helpers.events import request_cancel

        request_cancel()

    def _on_mute_toggle(icon, item) -> None:
        from helpers.cache import Cache

        Cache.set_audio(not Cache.get_audio())
        icon.update_menu()

    def _toggle_label(item) -> str:
        return "Pause assistant" if controller.is_running() else "Resume assistant"

    def _mute_label(item) -> str:
        from helpers.cache import Cache

        return "Mute" if Cache.get_audio() else "Unmute"

    def _wakeword_visible(item) -> bool:
        return wakeword._enabled

    def _wakeword_label(item) -> str:
        return "Wake word: On" if wakeword.is_running() else "Wake word: Off"

    def _on_wakeword_toggle(icon, item) -> None:
        if wakeword.is_running():
            wakeword.stop()
        else:
            wakeword.start()
        icon.update_menu()

    def _on_exit(icon, item) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open in web", _on_open_web, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Listen now", _on_listen_now),
        pystray.MenuItem("Stop speaking", _on_stop_speaking),
        pystray.MenuItem(_mute_label, _on_mute_toggle),
        pystray.MenuItem(
            _wakeword_label, _on_wakeword_toggle, visible=_wakeword_visible
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings", _on_settings),
        pystray.MenuItem("Check for updates", _on_check_updates),
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

    # Colour the icon by state, and surface proactive messages as Windows
    # toasts — a timer that fires with the browser closed and the speaker muted
    # was otherwise only visible to someone who went looking for the bell.
    def _on_event(payload: dict) -> None:
        kind = payload.get("type")
        if kind == "state":
            state = payload.get("state", "idle")
            _current_state[0] = state
            if _icon_ref[0] is not None:
                _icon_ref[0].icon = _make_icon_image(state)
        elif kind == "notification":
            _toast(payload.get("text", ""), payload.get("source", ""))

    def _toast(text: str, source: str) -> None:
        icon_obj = _icon_ref[0]
        if not text or icon_obj is None:
            return
        try:
            icon_obj.notify(text[:250], title=f"{assistant_name} · {source or 'notice'}")
        except Exception:
            pass  # some shells have no balloon support; the bell still has it

    from helpers.events import subscribe, unsubscribe

    subscribe(_on_event)

    # Ensure icon.stop() fires on process exit (e.g., sys.exit from a thread)
    atexit.register(lambda: _icon_ref[0].stop() if _icon_ref[0] else None)

    # Start everything
    controller.start()
    _start_hotkey()

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

    print(
        f"{assistant_name} is running in the system tray.\n"
        f"  Web UI:    http://{host}:{port}\n"
        f"  {hotkey_label()}:  push-to-talk from anywhere\n"
        f"  Tray icon: right-click for menu (listen now, mute, pause, exit)"
    )

    # Block main thread on the tray icon (pystray requirement on Windows)
    icon.run()

    # icon.run() returned — Exit was clicked (or _tray_exit_hook fired).
    # Run cleanup on the main thread, then force-exit. os._exit bypasses
    # atexit/gc finalizers that can block on audio/C-extension threads.
    unsubscribe(_on_event)
    _stop_hotkey()
    controller.shutdown()
    # os._exit below bypasses atexit — resume paused media explicitly first.
    from helpers.media_pause import resume_all

    resume_all()
    import os as _os

    _os._exit(0)


if __name__ == "__main__":
    run_tray()
