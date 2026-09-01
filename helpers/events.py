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
    """Broadcast assistant state change: 'idle' | 'thinking'."""
    emit({"type": "state", "state": state})


def emit_notification(notification: typing.Dict) -> None:
    """Broadcast a proactive message (tags payload with type='notification')."""
    tagged = dict(notification)
    tagged.setdefault("type", "notification")
    emit(tagged)


# ── Global session cancel ──────────────────────────────────────────────────
# A single deliberate "stop everything" signal, driven by the UI's Stop
# button. Aborts the in-flight agent turn between steps.
session_cancel = threading.Event()


def request_cancel() -> None:
    """Signal a deliberate stop: aborts the in-flight agent turn."""
    session_cancel.set()
    emit({"type": "cancel"})


def clear_cancel() -> None:
    """Reset the cancel signal. Called at the start of a new turn, inside the
    agent lock, so a cancel aimed at the previous turn cannot leak into it."""
    session_cancel.clear()
