"""Local-timezone helpers using the system's local timezone."""
import typing
from datetime import datetime, timezone, tzinfo

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def local_tz() -> tzinfo:
    """Return the system-local timezone."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def now_local() -> datetime:
    """Return the current datetime in the system-local timezone."""
    return datetime.now(local_tz())


def parse_when(
    text: str,
    prefer: str = "future",
    base: typing.Optional[datetime] = None,
) -> typing.Optional[datetime]:
    """A spoken date or time ("friday", "next monday", "14.30") as a local
    aware datetime, or None when it cannot be read.

    dateparser reads "next monday" and "last tuesday" as nothing at all, so a
    leading next/last before a weekday becomes the direction to look in.
    """
    import dateparser

    words = (text or "").strip().lower()
    if not words:
        return None
    first, _, rest = words.partition(" ")
    if rest.split(" ", 1)[0] in _WEEKDAYS:
        if first in ("next", "this", "coming"):
            words, prefer = rest, "future"
        elif first in ("last", "previous"):
            words, prefer = rest, "past"

    reference = (base or now_local()).replace(tzinfo=None)
    parsed = dateparser.parse(
        words,
        settings={
            "PREFER_DATES_FROM": prefer,
            "RELATIVE_BASE": reference,
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    return parsed.replace(tzinfo=local_tz()) if parsed else None
