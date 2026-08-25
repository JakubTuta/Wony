"""Local-timezone helpers using the system's local timezone."""
from datetime import datetime, timezone, tzinfo


def local_tz() -> tzinfo:
    """Return the system-local timezone."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def now_local() -> datetime:
    """Return the current datetime in the system-local timezone."""
    return datetime.now(local_tz())
