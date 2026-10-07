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
def _scope(present: bool, at_machine: bool, text: str) -> typing.Iterator[None]:
    previous = (
        getattr(_local, "present", False),
        getattr(_local, "at_machine", False),
        getattr(_local, "text", ""),
        getattr(_local, "untrusted", False),
        getattr(_local, "search_hrefs", None),
    )
    _local.present, _local.at_machine = present, at_machine
    _local.text, _local.untrusted, _local.search_hrefs = text, False, set()
    try:
        yield
    finally:
        (
            _local.present, _local.at_machine, _local.text,
            _local.untrusted, _local.search_hrefs,
        ) = previous


def user_request(text: str = "", at_machine: bool = True) -> typing.ContextManager[None]:
    """Mark everything inside as started by the user, saying `text`.

    at_machine=False for a request that arrived from a phone: the user is
    there to answer questions, but nobody is sitting at the PC.
    """
    return _scope(True, at_machine, text)


def unattended() -> typing.ContextManager[None]:
    """A turn nobody asked for (a trigger, a timer). Nobody is present, and what
    it reads does not stay marked on the thread for the next one."""
    return _scope(False, False, "")


def capture() -> typing.Tuple[typing.Any, ...]:
    """This thread's turn state, to carry onto a worker thread (helpers/agent.py
    runs independent tool calls side by side)."""
    return (
        getattr(_local, "present", False),
        getattr(_local, "at_machine", False),
        getattr(_local, "text", ""),
        getattr(_local, "untrusted", False),
        set(getattr(_local, "search_hrefs", None) or ()),
    )


@contextlib.contextmanager
def carried(state: typing.Tuple[typing.Any, ...]) -> typing.Iterator[typing.Dict[str, typing.Any]]:
    """Run on a worker thread as the turn that captured `state`. Yields a dict
    that holds, afterwards, what the work marked — hand it to absorb() on the
    turn's own thread, or an email read there would not count as read."""
    seen: typing.Dict[str, typing.Any] = {}
    with _scope(state[0], state[1], state[2]):
        _local.untrusted, _local.search_hrefs = state[3], set(state[4])
        try:
            yield seen
        finally:
            seen["untrusted"], seen["search_hrefs"] = _local.untrusted, set(_local.search_hrefs)


def absorb(seen: typing.Dict[str, typing.Any]) -> None:
    if seen.get("untrusted"):
        mark_untrusted_read()
    if seen.get("search_hrefs"):
        record_search_hrefs(seen["search_hrefs"])


def user_present() -> bool:
    return getattr(_local, "present", False)


def at_machine() -> bool:
    """Whether the user is in front of this computer — false for a remote
    chat. A sign-in window or a click would land on an empty desk."""
    return user_present() and getattr(_local, "at_machine", False)


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


def record_search_hrefs(hrefs: typing.Iterable[str]) -> None:
    """Remember the links a web_search call returned this turn, so a browse
    call that only visits one of them can skip the "did the user ask for this
    site" check — the search itself was the user's request."""
    existing = getattr(_local, "search_hrefs", None) or set()
    _local.search_hrefs = existing | set(hrefs)


def search_hrefs() -> typing.Set[str]:
    return getattr(_local, "search_hrefs", None) or set()
