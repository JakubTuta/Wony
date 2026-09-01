"""
Proactive messages: things Wony says without being asked.

A timer firing, the Gmail poller finding mail, a background job crashing. On a
device with a speaker these were spoken and then gone. Here they land on a
screen that nobody is necessarily looking at, so each one is written to the
database first and pushed to connected clients second. A reminder that fired
while the room was empty is still waiting when someone walks up to it.
"""

import typing

# Kinds a client may style differently. Not a config key — adding one is a
# change to both this file and the UI that renders it.
KINDS = ("info", "reminder", "alert", "error")


def notify(
    text: typing.Union[str, typing.List[str]],
    kind: str = "info",
    source: str = "",
) -> None:
    """Record a proactive message and push it to every connected screen.

    text: one message, or several that belong together (joined into one).
    kind: one of KINDS — how the UI should present it.
    source: which module raised it ("scheduler", "gmail", ...), for the UI.

    Never raises: a poller must not die because the screen is unreachable.
    """
    if isinstance(text, (list, tuple)):
        combined = " ".join(str(t).strip() for t in text if t)
    else:
        combined = str(text or "").strip()

    if not combined:
        return

    if kind not in KINDS:
        kind = "info"

    try:
        from helpers.memory_db import insert_notification

        record = insert_notification(combined, kind=kind, source=source)
    except Exception:
        # The DB is unavailable (locked, disk full). Still try to put the
        # message on screen — a live client is better than nothing at all.
        record = {"id": None, "kind": kind, "source": source, "text": combined}

    try:
        from helpers.events import emit_notification

        emit_notification(record)
    except Exception:
        pass

    try:
        from helpers.logger import logger

        logger.log_system_event("notification", f"[{source or kind}] {combined}")
    except Exception:
        pass
