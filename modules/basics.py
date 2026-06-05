import os
import time
import typing
from datetime import datetime, timedelta, timezone

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.registry import ServiceRegistry, register_job


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


# --- timer ---


def _timer_worker(minutes: float, label: str) -> None:
    time.sleep(minutes * 60)
    msg = f"Timer done: {label}." if label else f"{int(minutes)}-minute timer is done."
    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech(msg)
    print(msg)


@register_job(module_name="basics", summary="Set a countdown timer")
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


@register_job(module_name="basics", summary="List active timers")
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


@register_job(module_name="basics", summary="Cancel all timers")
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


# --- system ---


@register_job(module_name="basics")
def close_computer() -> None:
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
        None: System will shut down immediately after execution.
    """
    confirmation = input("Shut down the computer? Type 'yes' to confirm: ").strip().lower()
    if confirmation != "yes":
        print("Shutdown cancelled.")
        return

    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Closing computer. o7")
    print("Closing computer. o7")

    os.system("shutdown /s /f /t 0")


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
        from modules.weather import _get_weather_for_coordinates

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
        return f"Weather in {city}: {desc}, {temp}°C."
    except Exception:
        return None


def _email_line() -> typing.Optional[str]:
    try:
        gmail = ServiceRegistry.get_service_instance("gmail")
        if not gmail:
            return None

        work_end = int(Config.get("calendar.work_end_hour", 18))
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
        print(f"[greeting] email line failed: {e}")
        return None


def _calendar_line() -> typing.Optional[str]:
    try:
        cal = ServiceRegistry.get_service_instance("calendar")
        if not cal:
            return None

        today = datetime.now(timezone.utc)
        events = cal._fetch_events_for_day(today)

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
        print(f"[greeting] calendar line failed: {e}")
        return None
