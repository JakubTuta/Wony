import os
import subprocess
import typing
from datetime import datetime, timedelta

from helpers.config import Config
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import ServiceRegistry, register_job
from helpers.timeutil import now_local


# --- clock ---


@register_job(module_name="basics", summary="Tell the current time")
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


@register_job(module_name="basics", summary="Tell today's date")
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


# --- system ---


def _run_power_command(verb: str, systemctl_action: str) -> str:
    """Shared body of power_off and reboot.

    The gate is a config key rather than a typed confirmation: there is no
    console on this device, and a touch screen cannot answer input(). The UI
    is expected to confirm before it ever gets here.
    """
    if not bool(Config.get("modules.basics.allow_power_off", False)):
        logger.log_system_event(f"{systemctl_action}_refused", "Power control is disabled.")
        return (
            f"Power control is off. Set modules.basics.allow_power_off: true in "
            f"config.yaml to let me {verb} this device."
        )

    logger.log_system_event(systemctl_action, f"Running systemctl {systemctl_action}.")
    try:
        result = subprocess.run(
            ["systemctl", systemctl_action],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return "Can't find systemctl — this job only works on a systemd Linux system."
    except subprocess.TimeoutExpired:
        # systemctl normally returns immediately and the machine goes down
        # afterwards, so a timeout means the request is stuck, not succeeding.
        return f"The {verb} request timed out."

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return f"Couldn't {verb}: {detail or f'systemctl exited {result.returncode}'}"

    return f"{verb.capitalize()}ing now. o7"


@register_job(module_name="basics", summary="Power off this device")
@capture_response
def power_off() -> str:
    """
    [SYSTEM CONTROL JOB] Shuts down this device.

    Use this job when the user wants to:
    - Power down the device
    - Turn the machine off completely

    Keywords: shut down, power off, turn off, shutdown, power down, switch off

    Args:
        None

    Returns:
        str: Confirmation, or why the shutdown did not happen.
    """
    return _run_power_command("shut down", "poweroff")


@register_job(module_name="basics", summary="Restart this device")
@capture_response
def reboot() -> str:
    """
    [SYSTEM CONTROL JOB] Restarts this device.

    Use this job when the user wants to:
    - Reboot or restart the machine
    - Power-cycle the device to clear a problem

    Keywords: reboot, restart, restart the device, reboot the system, power cycle

    Args:
        None

    Returns:
        str: Confirmation, or why the restart did not happen.
    """
    return _run_power_command("restart", "reboot")


# --- greeting ---


@register_job(module_name="basics", summary="Greet with daily briefing")
@capture_response
def greeting() -> str:
    """
    [GREETING JOB] Provides a personalized time-of-day greeting with a daily briefing.

    Includes owner name, full date and time, and conditionally appends current weather,
    unread email summary with deduplicated senders, and today's calendar meetings depending
    on which modules are enabled.

    Use this job when the user wants to:
    - Start a conversation with a greeting
    - Get a daily morning or evening briefing
    - Hear the current time, date, weather, emails, and meetings at once

    Keywords: hello, hi, hey, hey there, good morning, good afternoon, good evening,
             greet, greeting, morning, what's up, daily briefing, morning briefing,
             status update, how are you, what do I have today

    Args:
        None

    Returns:
        str: Personalized greeting with time, date, and optional contextual info.
    """
    now = datetime.now()
    owner = Config.get("assistant.owner_name", "there")

    hour = now.hour
    if 5 <= hour < 12:
        phrase = "Good morning"
    elif 12 <= hour < 17:
        phrase = "Good afternoon"
    elif 17 <= hour < 21:
        phrase = "Good evening"
    else:
        phrase = "Hello"

    full_dt = now.strftime("%A, %B %d, %Y at %H:%M")
    parts: typing.List[str] = [f"{phrase}, {owner}! It's {full_dt}."]

    if Config.is_module_enabled("weather"):
        line = _weather_line()
        if line:
            parts.append(line)

    if Config.is_module_enabled("gmail"):
        line = _email_line()
        if line:
            parts.append(line)

    if Config.is_module_enabled("calendar"):
        line = _calendar_line()
        if line:
            parts.append(line)

    parts.append("What would you like me to do?")
    return "\n".join(parts)


def _weather_line() -> typing.Optional[str]:
    try:
        import geocoder
        from modules.weather import _get_weather_for_coordinates, temperature_symbol

        api_key = os.environ.get("WEATHER_API_KEY")
        if not api_key:
            return None

        g = geocoder.ip("me")
        if not g.latlng:
            return None

        lat, lon = g.latlng
        data = _get_weather_for_coordinates(lat, lon, api_key)
        if not data:
            return None

        desc = data["weather"][0]["description"]
        temp = round(data["main"]["temp"])
        city = g.city or "your location"
        return f"Weather in {city}: {desc}, {temp}{temperature_symbol()}."
    except Exception:
        return None


def _email_line() -> typing.Optional[str]:
    try:
        gmail = ServiceRegistry.get_service_instance("gmail")
        if not gmail:
            return None

        work_end = int(Config.get("modules.calendar.work_end_hour", 18))
        cutoff = (datetime.now() - timedelta(days=1)).replace(
            hour=work_end, minute=0, second=0, microsecond=0
        )
        date_str = cutoff.strftime("%Y/%m/%d")

        msgs = gmail._search(f"is:unread after:{date_str}")

        if not msgs:
            return "You have no new unread emails since yesterday."

        senders = dict.fromkeys(
            gmail._format_sender(m.sender) for m in msgs if m.sender
        )
        return f"You have {len(msgs)} unread email(s) from: {', '.join(senders)}."
    except Exception as e:
        logger.log_error(str(e), "greeting.email_line")
        return None


def _calendar_line() -> typing.Optional[str]:
    try:
        cal = ServiceRegistry.get_service_instance("calendar")
        if not cal:
            return None

        # Local, not UTC — _fetch_events_for_day stamps local tz on the date parts.
        events = cal._fetch_events_for_day(now_local())

        if not events:
            return "You have no meetings today."

        lines = [f"You have {len(events)} meeting(s) today:"]
        for e in events:
            title = e.get("summary", "Untitled")
            start_raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
            when = cal._format_time(start_raw)
            lines.append(f"  - {title} at {when}")
        return "\n".join(lines)
    except Exception as e:
        logger.log_error(str(e), "greeting.calendar_line")
        return None
