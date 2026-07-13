"""
Shared push-to-talk implementation for the Ctrl+L hotkey / tray "Listen now"
item. wony.py's voice mode and tray_app.py both need the same
voice_session/ducking/wake-word-pause handshake around a manual conversation
turn — this module is the single copy instead of two near-identical ones.
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
    from helpers.ducking import duck_others
    from helpers.logger import logger

    if not mic.voice_session.acquire(blocking=False):
        import helpers.diagnostics
        helpers.diagnostics.add("info", "PushToTalk", f"{log_label} skipped — mic already in use.")
        return
    try:
        logger.log_system_event("push_to_talk", log_label)
        if wakeword_listener is not None:
            wakeword_listener.pause()
        try:
            with duck_others():
                employer.speak()
        except SystemExit:
            on_exit()
        finally:
            if wakeword_listener is not None:
                wakeword_listener.resume()
    finally:
        mic.voice_session.release()


def start_hotkey(fire: typing.Callable[[], None]) -> typing.Optional[typing.Any]:
    """Register the global Ctrl+L hotkey. `fire` runs on a fresh daemon thread
    per press. Returns the listener (None if pynput isn't installed) — pass
    it to stop_hotkey() to unregister."""
    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError:
        import helpers.diagnostics
        helpers.diagnostics.add(
            "info", "PushToTalk", "Ctrl+L hotkey unavailable — pynput not installed.",
            hint="pip install -r requirements/voice.txt",
        )
        return None

    def _fire() -> None:
        threading.Thread(target=fire, daemon=True, name="push-to-talk-hotkey").start()

    listener = pynput_keyboard.GlobalHotKeys({"<ctrl>+l": _fire})
    listener.start()
    return listener


def stop_hotkey(listener: typing.Optional[typing.Any]) -> None:
    if listener is not None:
        try:
            listener.stop()
        except Exception:
            pass
