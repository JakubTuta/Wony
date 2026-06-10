"""Lightweight in-process pub/sub for broadcasting conversation turns.

Decouples conversation.py from the web layer to avoid circular imports.
"""
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


def emit_turn(turn: typing.Dict) -> None:
    with _lock:
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(turn)
        except Exception:
            pass
