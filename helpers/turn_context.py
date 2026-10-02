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
def user_request(text: str = "") -> typing.Iterator[None]:
    """Mark everything inside as started by the user, saying `text`."""
    previous = (getattr(_local, "present", False), getattr(_local, "text", ""))
    _local.present, _local.text = True, text
    try:
        yield
    finally:
        _local.present, _local.text = previous


def user_present() -> bool:
    return getattr(_local, "present", False)


def user_text() -> str:
    """What the user said this turn ("" for a click or no user at all)."""
    return getattr(_local, "text", "")
