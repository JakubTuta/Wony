import os
import typing
from datetime import datetime

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job


# --- clock ---


@register_job(module_name="basics", summary="Tell the current time and date")
@capture_response
def get_datetime(part: typing.Literal["time", "date", "both"] = "both") -> str:
    """
    [CLOCK JOB] Tells the current local time, today's date, or both.

    Args:
        part (str): "time" for the clock, "date" for the day, "both" (the default)
            for one sentence carrying each.

    Returns:
        str: The current time and/or date.
    """
    now = datetime.now()
    wanted = (part or "both").strip().lower()
    if wanted == "time":
        return f"It's {now.strftime('%H:%M')}."
    if wanted == "date":
        return f"Today is {now.strftime('%A, %B %d, %Y')}."
    return f"It's {now.strftime('%H:%M')} on {now.strftime('%A, %B %d, %Y')}."


# --- system ---


@register_job(module_name="basics", confirms=True)
@capture_response
def close_computer() -> str:
    """
    [SYSTEM CONTROL JOB] Immediately shuts down the entire computer system.
    This is a critical system operation that forcefully terminates all processes
    and powers off the machine. Use with extreme caution as it will close all applications.

    Returns:
        str: Confirmation of shutdown, cancellation, or why it couldn't be confirmed.
    """
    try:
        confirmation = input("Shut down the computer? Type 'yes' to confirm: ").strip().lower()
    except (EOFError, RuntimeError):
        # No console attached (tray/pythonw mode) — input() can't prompt at all.
        # Refuse rather than either hanging forever or shutting down unconfirmed.
        logger.log_system_event("shutdown_refused", "No console available to confirm shutdown.")
        return "Can't confirm a shutdown without a console — run 'wony.py text' or 'wony.py voice' to do this."

    if confirmation != "yes":
        logger.log_system_event("shutdown_cancelled", "User did not confirm shutdown.")
        return "Shutdown cancelled."

    audio = Cache.get_audio()
    if audio:
        Audio.play_cached("Closing computer. o7")
    logger.log_system_event("shutdown", "Shutting down computer.")
    os.system("shutdown /s /f /t 0")
    return "Shutting down now."
