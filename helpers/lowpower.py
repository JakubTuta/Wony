"""Deep sleep, for a device that has no sleep.

A Raspberry Pi cannot suspend to RAM, so "power it off for the night without
ending the processes" has to be assembled out of the parts that do exist:

  the panel goes dark      helpers/display.py, whichever backend works here
  the pollers stop         BackgroundJobs.suspend_all(), restarted on wake
  everything else stays    the agent, the web server, the reminder scheduler

That last line is the point. A timer set for 6am still fires at 6am, the socket
stays connected, and waking is a repaint rather than a boot — nothing has to be
loaded again because nothing was unloaded.

Two things end it, and the reason is carried through to the log so a screen
that woke on its own can be explained afterwards:

  a tap        the touchscreen keeps working with the panel dark, so the page
               is still there to catch the touch and ask us to wake up
  the clock    a wake time set when sleep began, held by a timer thread

Notably not a third: an arriving message never wakes the screen. Sleep is for
not being disturbed, and everything that happened overnight is still in the
notification list in the morning.

State lives here rather than in the database on purpose: a restart cannot leave
the device asleep, because reset_on_start() turns the panel back on before
anything else runs. The one thing that is persisted is last night's wake time,
so tonight's answer is already filled in.
"""

import datetime
import threading
import typing

from helpers.cache import Cache
from helpers.timeutil import now_local

# Last night's answer, so the sleep screen opens on it instead of on nothing.
# "" is a real answer, meaning "until I touch the screen"; absent means the
# question has never been asked, and nothing is chosen on the user's behalf.
_LAST_WAKE_KEY = "sleep_wake_at"

_lock = threading.RLock()

_asleep: bool = False
_since: typing.Optional[datetime.datetime] = None
_wake_at: typing.Optional[datetime.datetime] = None
_display_method: str = ""
_timer: typing.Optional[threading.Timer] = None
_paused_jobs: typing.List[str] = []


class WakeTimeError(ValueError):
    """A wake time that cannot be understood."""


def parse_wake_time(when: str) -> typing.Optional[datetime.datetime]:
    """Turn a wake time into a local datetime in the future, or None.

    Accepts a clock time ("07:00" — the next time it is that), a duration
    ("8h", "90m"), or a full ISO datetime. Empty means no scheduled wake: the
    screen sleeps until someone touches it.
    """
    text = (when or "").strip().lower()
    if not text:
        return None

    now = now_local()

    if text.endswith(("m", "h")) and text[:-1].strip().replace(".", "", 1).isdigit():
        amount = float(text[:-1].strip())
        delta = (
            datetime.timedelta(hours=amount)
            if text.endswith("h")
            else datetime.timedelta(minutes=amount)
        )
        if delta <= datetime.timedelta(0):
            raise WakeTimeError("A wake time has to be in the future.")
        return now + delta

    parts = text.split(":")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
        hour, minute = int(parts[0]), int(parts[1])
        if hour > 23 or minute > 59:
            raise WakeTimeError(f"'{when}' is not a time of day.")
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # The usual case is "sleep at 23:00, wake at 07:00", so a time that has
        # already been today means tomorrow, not an hour ago.
        if target <= now:
            target += datetime.timedelta(days=1)
        return target

    try:
        parsed = datetime.datetime.fromisoformat(when.strip())
    except ValueError:
        raise WakeTimeError(
            f"Can't read '{when}' as a wake time. Use HH:MM, or something like 8h."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    if parsed <= now:
        raise WakeTimeError("A wake time has to be in the future.")
    return parsed


def status() -> typing.Dict[str, typing.Any]:
    """What the screen and the doctor both ask for."""
    with _lock:
        return {
            "asleep": _asleep,
            "since": _since.isoformat(timespec="seconds") if _since else None,
            "wake_at": _wake_at.isoformat(timespec="seconds") if _wake_at else None,
            "display": _display_method,
            "paused_jobs": list(_paused_jobs),
            "last_wake": Cache.get_value(_LAST_WAKE_KEY, None),
        }


def _emit() -> None:
    from helpers.events import emit

    emit({"type": "sleep", **status()})


def _cancel_timer() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None


def enter(
    wake_at: str = "",
    reason: str = "screen",
) -> typing.Dict[str, typing.Any]:
    """Go to sleep. Raises WakeTimeError if wake_at cannot be read.

    Parsing happens before anything is switched off, so a typo leaves the
    device exactly as it was rather than dark with no wake time.
    """
    global _asleep, _since, _wake_at, _display_method, _timer, _paused_jobs

    target = parse_wake_time(wake_at)

    from helpers.logger import logger

    # Only after it parsed: remembering a rejected answer would hand the same
    # error straight back tomorrow night.
    try:
        Cache.set_value(_LAST_WAKE_KEY, (wake_at or "").strip())
    except OSError:
        pass  # A read-only disk is no reason not to go to sleep.

    with _lock:
        if _asleep:
            # Already asleep. Re-arm the timer rather than refusing: the second
            # request is likely a correction to the wake time.
            _cancel_timer()
            _wake_at = target
            _arm_locked()
            _emit()
            return status()

        from helpers.jobs import BackgroundJobs

        # The pollers are the only thing here that costs anything while nobody
        # is looking, and stopping them is the whole "low maintenance" part.
        # Reminders are not touched: a 6am alarm is still a 6am alarm.
        _paused_jobs = BackgroundJobs.suspend_all()

        worked, how = _display_off()

        _asleep = True
        _since = now_local()
        _wake_at = target
        _display_method = how if worked else f"screen stayed on: {how}"
        _arm_locked()

    logger.log_system_event(
        "sleep",
        f"[{reason}] display: {_display_method}"
        + (f", waking at {target.strftime('%H:%M')}" if target else ", waking on touch")
        + (f", paused {len(_paused_jobs)} job(s)" if _paused_jobs else ""),
    )
    _emit()
    return status()


def _display_off() -> typing.Tuple[bool, str]:
    from helpers import display

    return display.off()


def _arm_locked() -> None:
    """Schedule the wake. Caller holds the lock."""
    global _timer

    if _wake_at is None:
        return
    seconds = (_wake_at - now_local()).total_seconds()
    if seconds <= 0:
        seconds = 0.1
    _timer = threading.Timer(seconds, _timer_fired)
    _timer.daemon = True
    _timer.name = "sleep-wake"
    _timer.start()


def _timer_fired() -> None:
    wake(reason="scheduled")


def wake(reason: str = "touch") -> typing.Dict[str, typing.Any]:
    """Come back. Safe to call when already awake — the screen calls it on any
    touch rather than tracking whether it was needed."""
    global _asleep, _since, _wake_at, _display_method, _paused_jobs

    from helpers.logger import logger

    with _lock:
        if not _asleep:
            return status()

        _cancel_timer()
        worked, how = _display_on()

        resumed: typing.List[str] = []
        if _paused_jobs:
            from helpers.jobs import BackgroundJobs

            resumed = BackgroundJobs.resume_suspended()

        _asleep = False
        _since = None
        _wake_at = None
        _display_method = ""
        _paused_jobs = []

    logger.log_system_event(
        "wake",
        f"[{reason}] display: {how if worked else 'not switched: ' + how}"
        + (f", resumed {len(resumed)} job(s)" if resumed else ""),
    )
    _emit()
    return status()


def _display_on() -> typing.Tuple[bool, str]:
    from helpers import display

    return display.on()


def is_asleep() -> bool:
    with _lock:
        return _asleep


def reset_on_start() -> None:
    """Undo any sleep a previous run left behind.

    Nothing here persists sleep across a restart, but the *display* does: a
    crash, a `systemctl restart`, or a power cut mid-sleep can leave the panel
    switched off with the new process having no idea. Turning it on
    unconditionally at startup is cheap and is the only thing standing between
    a user and a device that looks bricked.
    """
    global _asleep, _since, _wake_at, _display_method, _paused_jobs

    with _lock:
        _cancel_timer()
        _asleep = False
        _since = None
        _wake_at = None
        _display_method = ""
        _paused_jobs = []

    try:
        from helpers import display

        display.on()
    except Exception:
        pass
