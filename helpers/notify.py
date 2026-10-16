"""
Proactive messages: things Wony says without being asked.

A timer firing, the Gmail poller finding mail, a background job crashing. On a
device with a speaker these were spoken and then gone. Here they land on a
screen that nobody is necessarily looking at, so each one is kept first (the
database, and the conversation the model reads) and pushed to connected
clients second. A reminder that fired while the room was empty is still
waiting when someone walks up to it, and a question about it has an answer.
"""

import typing

# Kinds a client may style differently. Not a config key — adding one is a
# change to both this file and the UI that renders it.
KINDS = ("info", "reminder", "alert", "error")


def notify(
    text: typing.Union[str, typing.List[str]],
    kind: str = "info",
    source: str = "",
    private: bool = False,
    untrusted: bool = False,
) -> None:
    """Record a proactive message and push it to every connected screen.

    text: one message, or several that belong together (joined into one).
    kind: one of KINDS — how the UI should present it.
    source: which module raised it ("scheduler", "gmail", ...), for the UI.
    private: the AI must never see it (a pairing code). Everything else joins
        the conversation history.
    untrusted: it retells words someone else wrote (an email subject, an
        invite), so the conversation keeps it fenced (helpers/untrusted.py).

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

    # Into the history the next turn reads, so "what time is that?" has
    # something to refer to. Before it goes out: a reply from the phone can be
    # back in seconds.
    if not private:
        try:
            from helpers.conversation import Conversation
            from helpers.untrusted import wrap

            label = source or kind
            Conversation.record_notice(wrap(combined, label) if untrusted else combined, label)
        except Exception:
            pass

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

    # Nothing here wakes a sleeping screen. A message that arrives overnight is
    # recorded, pushed to a client that is painting itself black, and still
    # waiting in the list in the morning — which is the point of sleeping.
