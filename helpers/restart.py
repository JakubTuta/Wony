"""Restart the running app from the web page.

Only the tray process knows how to relaunch itself (tray_app.py), so it
registers that here. A web server started on its own (`wony.py web`) registers
nothing, and the page then offers no Restart button instead of one that fails.
"""
import threading
import time
import typing

_handler: typing.Optional[typing.Callable[[], None]] = None


def set_handler(handler: typing.Callable[[], None]) -> None:
    global _handler
    _handler = handler


def available() -> bool:
    return _handler is not None


def request() -> bool:
    """Start the restart on its own thread — it tears down the web server
    that is answering this very request. False when nothing can restart."""
    handler = _handler
    if handler is None:
        return False

    def _after_reply() -> None:
        time.sleep(0.5)  # let this request's response leave before the server goes
        handler()

    threading.Thread(target=_after_reply, daemon=True, name="web-restart").start()
    return True
