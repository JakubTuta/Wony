"""Marking text that someone other than the user wrote.

Email bodies, web pages, invites and shared documents reach the model next to
tools that can send mail and change files. Anything in them that reads like an
instruction is an attempt at one, so it travels inside a fence the system
prompt tells the model to treat as data (modules/ai.py).
"""

OPEN = "<<<untrusted"
CLOSE = ">>>"


def wrap(text: str, source: str) -> str:
    """Fence `text` as third-party data. Empty text stays empty."""
    if not text or not text.strip():
        return text
    from helpers import turn_context

    turn_context.mark_untrusted_read()
    # A fence the content can close itself is no fence.
    body = text.replace(CLOSE, "> > >").replace(OPEN, "< < <untrusted")
    return f'{OPEN} source="{source}">>>\n{body}\n{CLOSE}'


def truncate(text: str, limit: int) -> str:
    """Cut `text` to `limit` characters, re-closing any fence the cut would
    otherwise leave open — history that drops the closing `>>>` lets
    everything after it keep reading as untrusted data, or worse, as the
    model's own text once nothing marks where "data" was supposed to end.

    A header line (`<<<untrusted source="...">>>`) ends in `>>>` too, so a
    plain OPEN-vs-CLOSE count is one short for every complete block — each
    header contributes one CLOSE-shaped substring that isn't a real close.
    Subtracting one per header (one per OPEN) corrects for that.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    headers = cut.count(OPEN)
    real_closes = cut.count(CLOSE) - headers
    closer = f"\n{CLOSE}" if real_closes < headers else ""
    return f"{cut}{closer}…"
