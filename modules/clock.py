from datetime import datetime

from helpers.decorators import capture_response
from helpers.registry import register_job


@register_job(module_name="clock", summary="Tell the current time")
@capture_response
def get_time() -> str:
    """
    [CLOCK JOB] Tells the current local time.

    Use this job when the user wants to:
    - Know what time it is
    - Check the current time

    Keywords: time, what time, current time, what's the time, tell me the time, clock

    Args:
        None

    Returns:
        str: Current time as a human-readable string.
    """
    now = datetime.now()
    return f"It's {now.strftime('%H:%M')}."


@register_job(module_name="clock", summary="Tell today's date")
@capture_response
def get_date() -> str:
    """
    [CLOCK JOB] Tells today's date.

    Use this job when the user wants to:
    - Know today's date
    - Check the current date

    Keywords: date, today, what's today, what day is it, current date, today's date

    Args:
        None

    Returns:
        str: Today's date as a human-readable string.
    """
    now = datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."
