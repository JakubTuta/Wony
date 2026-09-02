"""Proactive messages: things Wony says without being asked.

A timer firing, the Gmail poller finding mail, a background job crashing. These
were spoken and then gone — and `Audio.notify` is a no-op when audio is off, so
with the speaker muted they vanished entirely. Each one is now written to the
database first, pushed to connected clients second, and spoken last, so one
that fired while nobody was at the machine is still waiting afterwards.
"""

import typing

# Kinds a client may style differently. Adding one is a change here and in the
# UI that renders it.
KINDS = ("info", "reminder", "alert", "error")


def notify(
    text: typing.Union[str, typing.List[str]],
    kind: str = "info",
    source: str = "",
) -> None:
    """Record a proactive message, push it to the UI, and speak it.

    text: one message, or several that belong together (joined into one).
    kind: one of KINDS.
    source: which module raised it ("scheduler", "gmail", ...).

    Never raises: a poller must not die because the UI or the speaker is gone.
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
        # DB unavailable (locked, disk full). Still show and say it.
        record = {"id": None, "kind": kind, "source": source, "text": combined}

    try:
        from helpers.events import emit_notification

        emit_notification(record)
    except Exception:
        pass

    try:
        from helpers.audio import Audio

        Audio.notify(combined)
    except Exception:
        pass

    try:
        from helpers.logger import logger

        logger.log_system_event("notification", f"[{source or kind}] {combined}")
    except Exception:
        pass
