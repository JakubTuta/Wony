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
