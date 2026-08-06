"""
Shared push-to-talk implementation for the global hotkey / tray "Listen now"
item. wony.py's voice mode and tray_app.py both need the same
voice_session/media-pause/wake-word-pause handshake around a manual
conversation turn — this module is the single copy instead of two
near-identical ones.
"""
import threading
import typing


def do_speak(
    employer: typing.Any,
    wakeword_listener: typing.Optional[typing.Any],
    on_exit: typing.Callable[[], None],
    log_label: str,
) -> None:
    """Acquire the mic, pause wake-word detection, run one manual speak turn.

    wakeword_listener may be None (no wake word configured) — pause()/resume()
    are only called when it's present (WakeWordListener already no-ops
    internally when disabled, but callers that never construct one pass None).
    on_exit() runs if the conversation raised SystemExit (an "exit"/"close
    computer" command was spoken).
    """
    from helpers import mic
    from helpers.audio import acknowledge_wake
    from helpers.events import clear_cancel
    from helpers.logger import logger
    from helpers.media_pause import pause_media

    if not mic.voice_session.acquire(blocking=False):
        import helpers.diagnostics
        helpers.diagnostics.add("info", "PushToTalk", f"{log_label} skipped — mic already in use.")
        return
    try:
        clear_cancel()  # new session — a cancel from a prior turn must not leak in
        logger.log_system_event("push_to_talk", log_label)
        if wakeword_listener is not None:
            wakeword_listener.pause()
        try:
            with pause_media():
                # Same ack the wake word gives. Without it this path pauses the
                # user's media and listens in silence, which reads as a bug.
                acknowledge_wake()
                employer.speak()
        except SystemExit:
            on_exit()
        finally:
            if wakeword_listener is not None:
                wakeword_listener.resume()
    finally:
        mic.voice_session.release()


def hotkey_binding() -> str:
    """The configured push-to-talk combination ("" when disabled)."""
    from helpers.config import Config

    return str(Config.get("voice.hotkeys.push_to_talk", "") or "").strip()


def hotkey_label() -> str:
    """The configured combination in a form worth showing a user."""
    binding = hotkey_binding()
    if not binding:
        return "disabled"
    return "+".join(part.strip("<>").capitalize() for part in binding.split("+"))


def start_hotkey(fire: typing.Callable[[], None]) -> typing.Optional[typing.Any]:
    """Register the global push-to-talk hotkey (voice.hotkeys.push_to_talk).

    `fire` runs on a fresh daemon thread per press. Returns the listener, or
    None when pynput is missing, the binding is disabled, or the combination
    string doesn't parse — pass it to stop_hotkey() to unregister.

    This is a system-wide, non-suppressing hook: it fires no matter which app
    has focus, and the keystroke still reaches that app. It is also looser than
    it looks — pynput's HotKey only tracks the keys named in the combination and
    ignores any other modifier held at the same time, so "<ctrl>+l" also fires on
    ctrl+shift+l and ctrl+alt+l. Pick a binding no other app wants; the default
    is three keys for exactly that reason.
    """
    import helpers.diagnostics

    binding = hotkey_binding()
    if not binding:
        helpers.diagnostics.add("info", "PushToTalk", "Push-to-talk hotkey disabled (voice.hotkeys.push_to_talk).")
        return None

    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError:
        helpers.diagnostics.add(
            "info", "PushToTalk", "Push-to-talk hotkey unavailable — pynput not installed.",
            hint="pip install -r requirements/voice.txt",
        )
        return None

    # Validate before registering: GlobalHotKeys raises on a malformed
    # combination, which would otherwise take down whatever started it.
    try:
        pynput_keyboard.HotKey.parse(binding)
    except ValueError:
        helpers.diagnostics.add(
            "warning", "PushToTalk",
            f"Ignoring unparseable hotkey '{binding}' — push-to-talk is off.",
            hint='Use pynput syntax, e.g. "<ctrl>+<alt>+w". Set null to disable deliberately.',
        )
        return None

    def _fire() -> None:
        threading.Thread(target=fire, daemon=True, name="push-to-talk-hotkey").start()

    try:
        listener = pynput_keyboard.GlobalHotKeys({binding: _fire})
        listener.start()
    except Exception as e:
        helpers.diagnostics.add("warning", "PushToTalk", f"Couldn't register hotkey '{binding}': {e}")
        return None

    helpers.diagnostics.add("info", "PushToTalk", f"Push-to-talk hotkey: {hotkey_label()}")
    return listener


def stop_hotkey(listener: typing.Optional[typing.Any]) -> None:
    if listener is not None:
        try:
            listener.stop()
        except Exception:
            pass
