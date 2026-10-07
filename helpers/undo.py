"""Undo instead of "are you sure?" for changes that are easy to reverse.

A light switched off, an item on a list, a song in a playlist: asking first
turns one sentence into two, and the change itself is cheap to take back. A job
that makes one records how to reverse it here, and "undo" reverses the latest.
Changes that are hard to take back — a sent email, a deleted file — keep their
confirm gate (helpers/confirm.py).
"""
import threading
import time
import typing

# How long a change stays undoable. "Undo" an hour later is more likely about
# something else than about the light switched off before lunch.
_TTL_SECONDS = 900.0
_MAX_ENTRIES = 10


class _Entry(typing.NamedTuple):
    what: str  # "turned the kitchen light off", for "Undid: ..."
    revert: typing.Callable[[], str]
    at: float


_lock = threading.Lock()
_entries: typing.List[_Entry] = []


def push(what: str, revert: typing.Callable[[], str]) -> None:
    """Record how to take back a change the user just asked for.

    Only from a user's request: a timer or a trigger acting alone is not
    something "undo" should be heard as referring to.
    """
    from helpers import turn_context

    if not turn_context.user_present():
        return
    with _lock:
        _entries.append(_Entry(what, revert, time.monotonic()))
        del _entries[:-_MAX_ENTRIES]


def undo() -> str:
    """Reverse the latest change still undoable, and say what happened."""
    now = time.monotonic()
    with _lock:
        while _entries and now - _entries[-1].at > _TTL_SECONDS:
            _entries.pop()
        if not _entries:
            return "There's nothing recent to undo."
        entry = _entries.pop()
    try:
        result = entry.revert()
    except Exception as e:
        return f"I couldn't undo that ({entry.what}): {e}"
    return f"Undid: {entry.what}. {result}".strip()


def reset() -> None:
    with _lock:
        _entries.clear()
