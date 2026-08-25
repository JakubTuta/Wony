import os
import typing
from datetime import datetime, timedelta

from helpers.audio import Audio
from helpers.cache import Cache
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


@register_job(module_name="basics")
@capture_response
def close_computer() -> str:
    """
    [SYSTEM CONTROL JOB] Immediately shuts down the entire computer system.
    This is a critical system operation that forcefully terminates all processes
    and powers off the machine. Use with extreme caution as it will close all applications.

    Use this job when the user wants to:
    - Completely power down the computer
    - Shut down the system via voice command
    - Emergency system shutdown
    - End the computing session entirely

    Keywords: close computer, shut down, power off, turn off, exit, close system, shutdown, power down,
             restart computer, shut down pc, power down system, close everything

    Args:
        None

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
