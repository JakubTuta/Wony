"""Whether the code running now was started by the user.

A spoken or typed request, or a click on the web page, has someone watching.
A trigger, a scheduled action or a background poll does not — and must not
open a Google consent window or follow a link nobody asked for.
"""
import contextlib
import threading
import typing

_local = threading.local()


@contextlib.contextmanager
def _scope(present: bool, text: str) -> typing.Iterator[None]:
    previous = (
        getattr(_local, "present", False),
        getattr(_local, "text", ""),
        getattr(_local, "untrusted", False),
    )
    _local.present, _local.text, _local.untrusted = present, text, False
    try:
        yield
    finally:
        _local.present, _local.text, _local.untrusted = previous


def user_request(text: str = "") -> typing.ContextManager[None]:
    """Mark everything inside as started by the user, saying `text`."""
    return _scope(True, text)


def unattended() -> typing.ContextManager[None]:
    """A turn nobody asked for (a trigger, a timer). Nobody is present, and what
    it reads does not stay marked on the thread for the next one."""
    return _scope(False, "")


def capture() -> typing.Tuple[typing.Any, ...]:
    """This thread's turn state, to carry onto a worker thread (helpers/agent.py
    runs independent tool calls side by side)."""
    return (
        getattr(_local, "present", False),
        getattr(_local, "text", ""),
        getattr(_local, "untrusted", False),
    )


@contextlib.contextmanager
def carried(state: typing.Tuple[typing.Any, ...]) -> typing.Iterator[typing.Dict[str, typing.Any]]:
    """Run on a worker thread as the turn that captured `state`. Yields a dict
    that holds, afterwards, what the work marked — hand it to absorb() on the
    turn's own thread, or an email read there would not count as read."""
    seen: typing.Dict[str, typing.Any] = {}
    with _scope(state[0], state[1]):
        _local.untrusted = state[2]
        try:
            yield seen
        finally:
            seen["untrusted"] = _local.untrusted


def absorb(seen: typing.Dict[str, typing.Any]) -> None:
    if seen.get("untrusted"):
        mark_untrusted_read()


def user_present() -> bool:
    return getattr(_local, "present", False)


def user_text() -> str:
    """What the user said this turn ("" for a click or no user at all)."""
    return getattr(_local, "text", "")


def mark_untrusted_read() -> None:
    """Record that this turn has read text someone other than the user
    wrote (helpers/untrusted.py). Read back by helpers/confirm.py so a save,
    an add, or a watcher turned on right after can be asked about instead of
    silently acting on an instruction smuggled in there."""
    _local.untrusted = True


def untrusted_read() -> bool:
    return getattr(_local, "untrusted", False)

