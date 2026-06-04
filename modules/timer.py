import time

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.registry import register_job


def _timer_worker(minutes: float, label: str) -> None:
    time.sleep(minutes * 60)
    msg = f"Timer done: {label}." if label else f"{int(minutes)}-minute timer is done."
    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech(msg)
    print(msg)


@register_job(module_name="timer", summary="Set a countdown timer")
@capture_response
def set_timer(minutes: float, label: str = "") -> str:
    """
    [TIMER JOB] Sets a background countdown timer that announces when time is up.

    Use this job when the user wants to:
    - Set a timer for N minutes
    - Get a reminder after a delay
    - Count down to an event

    Keywords: timer, set timer, countdown, remind me, alarm, set alarm, in N minutes,
             reminder, minutes timer, alert

    Args:
        minutes (float): Number of minutes to count down.
        label (str): Optional label/description for the timer.

    Returns:
        str: Confirmation that the timer was started.
    """
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return "Invalid duration. Provide a number of minutes, e.g. 'set timer 5'."

    if minutes <= 0:
        return "Timer duration must be greater than zero."

    job_name = f"timer_{label or int(minutes)}"
    if BackgroundJobs.is_running(job_name):
        return f"A timer called '{job_name}' is already running."

    BackgroundJobs.start(job_name, lambda: _timer_worker(minutes, label))

    display = f"{minutes:g} minute{'s' if minutes != 1 else ''}"
    return f"Timer set for {display}" + (f": {label}" if label else "") + "."


@register_job(module_name="timer", summary="List active timers")
@capture_response
def list_timers() -> str:
    """
    [TIMER JOB] Lists all active countdown timers.

    Use this job when the user wants to:
    - See what timers are running
    - Check active timers

    Keywords: list timers, show timers, active timers, what timers, running timers

    Args:
        None

    Returns:
        str: Active timer names or a message if none are running.
    """
    timers = [n for n in BackgroundJobs.list_jobs() if n.startswith("timer_")]
    if timers:
        return f"Active timers: {', '.join(t.replace('timer_', '', 1) for t in timers)}."
    return "No timers are currently running."


@register_job(module_name="timer", summary="Cancel all timers")
@capture_response
def cancel_timers() -> str:
    """
    [TIMER JOB] Cancels all active countdown timers.

    Use this job when the user wants to:
    - Cancel all timers
    - Stop countdown timers

    Keywords: cancel timers, stop timers, cancel all timers, clear timers, remove timers

    Args:
        None

    Returns:
        str: Confirmation of cancelled timers.
    """
    timers = [n for n in BackgroundJobs.list_jobs() if n.startswith("timer_")]
    for name in timers:
        BackgroundJobs.stop(name)

    if timers:
        return f"Cancelled {len(timers)} timer(s)."
    return "No timers were running."
