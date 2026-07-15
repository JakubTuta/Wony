"""In-process pub/sub for broadcasting events. Decouples conversation/diagnostics from the web layer."""
import threading
import typing

_lock = threading.Lock()
_listeners: typing.List[typing.Callable[[typing.Dict], None]] = []


def subscribe(fn: typing.Callable[[typing.Dict], None]) -> None:
    with _lock:
        _listeners.append(fn)


def unsubscribe(fn: typing.Callable[[typing.Dict], None]) -> None:
    with _lock:
        try:
            _listeners.remove(fn)
        except ValueError:
            pass


def emit(payload: typing.Dict) -> None:
    """Broadcast any payload dict to all subscribers."""
    with _lock:
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(payload)
        except Exception:
            pass


def emit_turn(turn: typing.Dict) -> None:
    """Broadcast a conversation turn (tags payload with type='turn')."""
    tagged = dict(turn)
    tagged.setdefault("type", "turn")
    emit(tagged)


def emit_state(state: str) -> None:
    """Broadcast assistant state change: 'idle' | 'listening' | 'thinking' | 'speaking'."""
    emit({"type": "state", "state": state})


# ── Global session cancel ──────────────────────────────────────────────────
# A single deliberate "stop everything" signal (tray "Stop" / web `stop`),
# distinct from barge-in interruption (a new utterance stopping playback so
# the assistant can listen — that stays a private per-stream Event). Cancel
# aborts capture, in-flight agent turns, and speech all at once; a prior
# "stop speaking" only touched playback, which is why a stuck capture/agent
# turn used to survive it.
session_cancel = threading.Event()


def request_cancel() -> None:
    """Signal a deliberate stop: aborts capture, the agent turn, and speech."""
    session_cancel.set()
    try:
        from helpers.audio import interrupt_current_speech
        interrupt_current_speech()
    except Exception:
        pass
    emit({"type": "cancel"})


def clear_cancel() -> None:
    """Reset the cancel signal. Call at the start of a new session (wake
    detection, push-to-talk) — never mid-capture, so a cancel issued during
    the "Yes?" ack still aborts the capture that follows it."""
    session_cancel.clear()
