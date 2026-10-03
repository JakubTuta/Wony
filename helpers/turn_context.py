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
def user_request(text: str = "", at_machine: bool = True) -> typing.Iterator[None]:
    """Mark everything inside as started by the user, saying `text`.

    at_machine=False for a request that arrived from a phone: the user is
    there to answer questions, but nobody is sitting at the PC.
    """
    previous = (
        getattr(_local, "present", False),
        getattr(_local, "at_machine", False),
        getattr(_local, "text", ""),
        getattr(_local, "untrusted", False),
        getattr(_local, "search_hrefs", None),
    )
    _local.present, _local.at_machine = True, at_machine
    _local.text, _local.untrusted, _local.search_hrefs = text, False, set()
    try:
        yield
    finally:
        (
            _local.present, _local.at_machine, _local.text,
            _local.untrusted, _local.search_hrefs,
        ) = previous


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
