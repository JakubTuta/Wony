import subprocess
import sys
import threading
import typing
from datetime import datetime

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job

# Seconds before a shutdown or restart, so the spoken reply finishes and other
# apps get Windows' normal chance to save.
_SHUTDOWN_DELAY_SECONDS = 10
# Sleep cuts the reply off mid-word without a short pause first.
_SLEEP_DELAY_SECONDS = 3


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


@register_job(module_name="basics", confirms={"shutdown", "restart"})
@capture_response
def power(action: typing.Literal["shutdown", "restart", "sleep", "lock"]) -> str:
    """
    [SYSTEM CONTROL JOB] Shuts down, restarts, puts to sleep or locks this computer.

    Args:
        action (str): "shutdown", "restart", "sleep" or "lock". (required)

    Returns:
        str: What is about to happen.
    """
    if sys.platform != "win32":
        return "Power control only works on Windows."

    wanted = (action or "").strip().lower()
    logger.log_system_event("power", wanted)

    if wanted == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", str(_SHUTDOWN_DELAY_SECONDS)], check=False)
        return f"Shutting down in {_SHUTDOWN_DELAY_SECONDS} seconds."
    if wanted == "restart":
        subprocess.run(["shutdown", "/r", "/t", str(_SHUTDOWN_DELAY_SECONDS)], check=False)
        return f"Restarting in {_SHUTDOWN_DELAY_SECONDS} seconds."
    if wanted == "lock":
        import ctypes

        ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
        return "Locked."
    if wanted == "sleep":
        threading.Timer(_SLEEP_DELAY_SECONDS, _sleep_now).start()
        return "Going to sleep."
    return f"Unknown action '{action}'. Use shutdown, restart, sleep or lock."


def _sleep_now() -> None:
    import ctypes

    # (hibernate=False, force=False, disable_wake_events=False)
    ctypes.windll.PowrProf.SetSuspendState(0, 0, 0)  # type: ignore[attr-defined]
