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
import sys
import threading
import typing

from helpers import instance

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


def _relaunch_self() -> None:
    """Spawn a fresh Wony process with this one's own launch command, so
    Restart works the same whether this instance is running under wony.py,
    tray_app.py, Wony.exe or pythonw.exe directly."""
    import subprocess

    argv = list(sys.argv)
    argv[0] = os.path.abspath(argv[0])
    kwargs: typing.Dict[str, typing.Any] = {
        "cwd": os.path.dirname(os.path.abspath(__file__)),
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen([sys.executable] + argv, **kwargs)


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
    if not instance.acquire():
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
    from helpers import server_address
    from helpers.web_runner import WebServerController

    web = WebServerController(app, server_address.HOST, server_address.pick_port())
    web_url = web.url

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
        webbrowser.open(web_url)

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
                icon.update_menu()  # shows Update now
            except Exception:
                print(message)

        threading.Thread(target=_check, daemon=True, name="update-check").start()

    def _update_visible(item) -> bool:
        from helpers.updates import available

        return available()

    def _on_update(icon, item) -> None:
        def _update() -> None:
            from helpers.updates import apply

            _toast("Updating — this can take a few minutes. Wony restarts when it is done.", "update")
            worked, message = apply()
            _toast(message, "update")
            if worked:
                _do_restart()
            else:
                icon.update_menu()

        threading.Thread(target=_update, daemon=True, name="update").start()

    def _accounts_needing_sign_in() -> typing.List[str]:
        try:
            from helpers import google_auth
            from helpers.accounts import GoogleAccounts

            return [n for n in GoogleAccounts.list_accounts() if google_auth.status(n)["needs_sign_in"]]
        except Exception:
            return []  # no Google set up

    def _google_sign_in_visible(item) -> bool:
        return bool(_accounts_needing_sign_in())

    def _on_google_sign_in(icon, item) -> None:
        def _sign_in() -> None:
            from helpers import google_auth
            from helpers.turn_context import user_request

            for name in _accounts_needing_sign_in():
                try:
                    with user_request():
                        google_auth.sign_in(name)
                except Exception as e:
                    _toast(f"Google sign-in for '{name}' did not finish: {e}", "google")
            icon.update_menu()

        threading.Thread(target=_sign_in, daemon=True, name="google-sign-in").start()

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

    def _do_restart() -> None:
        # Full teardown *before* spawning the new process — it binds the same
        # web port, and starting it while this one still holds that port (or
        # the instance lock) would just lose the race and quit right
        # back out. icon.stop() at the end runs the normal exit path's own
        # (idempotent) cleanup and os._exit — no need to repeat it here.
        _stop_hotkey()
        controller.shutdown()
        from helpers.media_pause import resume_all

        resume_all()
        instance.release()
        _relaunch_self()
        if _icon_ref[0] is not None:
            _icon_ref[0].stop()

    def _on_restart(icon, item) -> None:
        threading.Thread(target=_do_restart, daemon=True, name="restart").start()

    from helpers import restart as _web_restart

    _web_restart.set_handler(_do_restart)

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
        pystray.MenuItem("Sign in to Google again", _on_google_sign_in, visible=_google_sign_in_visible),
        pystray.MenuItem("Settings", _on_settings),
        pystray.MenuItem("Check for updates", _on_check_updates),
        pystray.MenuItem("Update now", _on_update, visible=_update_visible),
        pystray.MenuItem(_toggle_label, _on_toggle),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart", _on_restart),
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

    # The very first launch has nothing but a small tray icon to show for
    # itself, which a new user reads as "nothing happened". Open the page once;
    # after that the user's own open_browser_on_start choice decides.
    first_run = False
    try:
        from helpers.memory_db import get_kv, recent_turns, set_kv

        if not get_kv("first_run_browser_opened", ""):
            set_kv("first_run_browser_opened", "1")
            # An install that already has conversations is not a first run —
            # this flag is new, so it would otherwise fire once on every update.
            first_run = not recent_turns(1)
    except Exception:
        pass

    if notify_on_ready:
        try:
            icon.notify(
                f"{assistant_name} is running. Right-click this icon, near the clock, "
                "and choose Open in web.",
                title=assistant_name,
            )
        except Exception:
            pass

    if open_browser_on_start or first_run:
        try:
            import webbrowser

            webbrowser.open(web_url)
        except Exception:
            pass

    print(
        f"{assistant_name} is running in the system tray.\n"
        f"  Web UI:    {web_url}\n"
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
