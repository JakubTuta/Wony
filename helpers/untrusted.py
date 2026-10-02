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
    # A fence the content can close itself is no fence.
    body = text.replace(CLOSE, "> > >").replace(OPEN, "< < <untrusted")
    return f'{OPEN} source="{source}">>>\n{body}\n{CLOSE}'
