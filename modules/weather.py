import os
import typing

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement

# Forecast entries are 3 hours apart; this is the free plan's whole window.
_FORECAST_DAYS = 5


@register_job(
    module_name="weather",
    requires=Requirement(
        env_vars=["WEATHER_API_KEY"],
        pip_modules=["requests"],
        setup_hint="Add WEATHER_API_KEY to .env (free key at openweathermap.org/api).",
    ),
)
@capture_response
def weather(city: str = "", when: str = "now") -> str:
    """
    [WEATHER JOB] Reports the weather for any city, or for wherever this computer is:
    conditions right now, or the forecast for today, tomorrow or the next few days.

    Args:
        city (str): The city to report on. Leave empty for wherever this computer is.
        when (str): "now" (the default) for current conditions, or "today",
            "tomorrow" or "week" for the forecast.

    Returns:
        str: The weather report.
    """
    wanted = (when or "now").strip().lower()
    if wanted in ("now", "current", "today's weather", ""):
        return _now_report(city)
    if wanted in ("today", "tomorrow", "week", "forecast"):
        return _forecast_report(city, "week" if wanted == "forecast" else wanted)
    return f"Unknown option '{when}'. Use now, today, tomorrow or week."


def _now_report(city: str) -> str:
    data = snapshot(city)
    if data["error"]:
        return f"Error: {data['error']}"

    unit = data["unit"]
    line = (
        f"The weather in {data['city']} is {data['description']} "
        f"with {round(data['temperature'])}{unit}"
    )
    feels = data.get("feels_like")
    if feels is not None and round(feels) != round(data["temperature"]):
        line += f", feeling like {round(feels)}{unit}"
    line += "."

    if data.get("humidity") is not None:
        line += f" Humidity {data['humidity']}%"
        if data.get("wind") is not None:
            line += f", wind {data['wind']} {data['wind_unit']}"
        line += "."

    sun = _sun_line(data)
    if sun:
        line += f" {sun}"
    return line


def _sun_line(data: typing.Dict[str, typing.Any]) -> str:
    """Sunrise/sunset were in snapshot() for the panel and nothing could say them."""
    from datetime import datetime, timedelta, timezone

    sunrise, sunset = data.get("sunrise"), data.get("sunset")
    if not sunrise or not sunset:
        return ""
    # In the reported city's clock, not this machine's — Tokyo's sunrise read
    # back as 22:15 when it was rendered against a European desktop.
    there = timezone(timedelta(seconds=int(data.get("utc_offset", 0) or 0)))
    try:
        up = datetime.fromtimestamp(sunrise, tz=there).strftime("%H:%M")
        down = datetime.fromtimestamp(sunset, tz=there).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return ""
    return f"Sunrise {up}, sunset {down}."


def snapshot(city: str = "") -> typing.Dict[str, typing.Any]:
    """Current conditions as data, for the weather panel.

    Not a job: weather() describes this in a sentence, which has nowhere to put
    a humidity readout or an icon. Same request, structure kept. Errors come
    back in "error" because every caller wants to show them, not handle them.
    """
    empty = {
        "city": city or "your location",
        "description": "",
        "temperature": None,
        "feels_like": None,
        "unit": temperature_symbol(),
        "humidity": None,
        "wind": None,
        "wind_unit": _wind_unit(),
        "icon": "",
        "condition": 0,
        "sunrise": None,
        "sunset": None,
        # Seconds from UTC at the place reported on, so sunrise for a city on
        # the other side of the world reads in that city's clock and not this
        # machine's.
        "utc_offset": 0,
        "error": None,
    }

    api_key = os.environ.get("WEATHER_API_KEY")
    if not api_key:
        return {**empty, "error": "Weather API key not configured."}

    requested = city
    if city == "":
        lat, lon, city = _here()
        if lat is None:
            return {**empty, "error": "Could not work out where this device is."}
    else:
        lat, lon = _get_coordinates_for_city_name(city, api_key)

    if lat is None or lon is None:
        return {**empty, "error": "Could not retrieve coordinates for the given city."}

    data = _get_weather_for_coordinates(lat, lon, api_key)
    if data is None:
        return {**empty, "error": "Could not retrieve weather information."}

    conditions = (data.get("weather") or [{}])[0]
    main = data.get("main") or {}
    return {
        **empty,
        # A city the user named is echoed back as they said it; the station's
        # own name is the nearest reporting point, which is the best answer for
        # an IP guess and the wrong one for a request — "what's it like in
        # Tokyo" came back as "the weather in Japan".
        "city": requested or data.get("name") or city,
        "description": conditions.get("description", ""),
        "temperature": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind": (data.get("wind") or {}).get("speed"),
        "icon": conditions.get("icon", ""),
        "condition": conditions.get("id", 0),
        "sunrise": (data.get("sys") or {}).get("sunrise"),
        "sunset": (data.get("sys") or {}).get("sunset"),
        "utc_offset": int(data.get("timezone", 0) or 0),
    }


def forecast(city: str = "") -> typing.Dict[str, typing.Any]:
    """The next few days in 3-hour steps, grouped by local date.

    {"city": str, "days": [{"date", "label", "low", "high", "description"}],
     "unit": str, "error": str|None}
    """
    from datetime import datetime, timedelta, timezone

    empty: typing.Dict[str, typing.Any] = {
        "city": city or "your location",
        "days": [],
        # What day it is where the forecast is for. "Tomorrow in Tokyo" is
        # tomorrow in Tokyo, which is not always tomorrow at this desk.
        "today": "",
        "unit": temperature_symbol(),
        "error": None,
    }

    api_key = os.environ.get("WEATHER_API_KEY")
    if not api_key:
        return {**empty, "error": "Weather API key not configured."}

    requested = city
    if city == "":
        lat, lon, city = _here()
        if lat is None:
            return {**empty, "error": "Could not work out where this device is."}
    else:
        lat, lon = _get_coordinates_for_city_name(city, api_key)

    if lat is None or lon is None:
        return {**empty, "error": "Could not retrieve coordinates for the given city."}

    data = _get_forecast_for_coordinates(lat, lon, api_key)
    if data is None:
        return {**empty, "error": "Could not retrieve the forecast."}

    offset = timedelta(seconds=int((data.get("city") or {}).get("timezone", 0) or 0))
    return {
        **empty,
        "city": requested or (data.get("city") or {}).get("name") or city,
        "today": (datetime.now(timezone.utc) + offset).date().isoformat(),
        "days": _group_by_day(data),
    }


def _group_by_day(data: typing.Dict[str, typing.Any]) -> typing.List[typing.Dict]:
    """Collapse the 3-hourly entries into one line per local day."""
    from datetime import datetime, timedelta, timezone

    # Entries are UTC; the city's own offset is what decides which day a 23:00
    # reading belongs to.
    offset = timedelta(seconds=int((data.get("city") or {}).get("timezone", 0)))

    days: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    for entry in data.get("list", []):
        try:
            when = datetime.fromtimestamp(entry["dt"], tz=timezone.utc) + offset
            temp = float(entry["main"]["temp"])
        except (KeyError, TypeError, ValueError):
            continue

        key = when.date().isoformat()
        day = days.setdefault(key, {
            "date": key,
            "label": when.strftime("%A"),
            "low": temp,
            "high": temp,
            # Whatever it is doing in the middle of the day is the day's
            # headline; the 03:00 entry is not what anyone means.
            "description": "",
            "_midday_gap": 24,
        })
        day["low"] = min(day["low"], temp)
        day["high"] = max(day["high"], temp)
        gap = abs(when.hour - 13)
        if gap < day["_midday_gap"]:
            day["_midday_gap"] = gap
            day["description"] = (entry.get("weather") or [{}])[0].get("description", "")

    out = []
    for key in sorted(days):
        day = days.pop(key)
        day.pop("_midday_gap", None)
        day["low"] = round(day["low"])
        day["high"] = round(day["high"])
        out.append(day)
    return out[:_FORECAST_DAYS]


def _forecast_report(city: str, when: str) -> str:
    from datetime import date, timedelta

    data = forecast(city)
    if data["error"]:
        return f"Error: {data['error']}"
    if not data["days"]:
        return f"No forecast available for {data['city']}."

    unit = data["unit"]
    if when in ("today", "tomorrow"):
        there = date.fromisoformat(data["today"]) if data["today"] else date.today()
        wanted = (there + timedelta(days=1 if when == "tomorrow" else 0)).isoformat()
        day = next((d for d in data["days"] if d["date"] == wanted), None)
        if day is None:
            # The 5-day window always covers tomorrow; today drops off it once
            # the last entry for today has passed.
            return f"I don't have a forecast for {when} in {data['city']} any more."
        return (
            f"{when.capitalize()} in {data['city']}: {day['description']}, "
            f"{day['low']} to {day['high']}{unit}."
        )

    lines = [f"Forecast for {data['city']}:"]
    for day in data["days"]:
        lines.append(f"  {day['label']}: {day['description']}, {day['low']}–{day['high']}{unit}")
    return "\n".join(lines)


def _here() -> typing.Tuple[
    typing.Optional[float], typing.Optional[float], str
]:
    """Where this device is (helpers/location.py)."""
    from helpers.location import here

    place = here()
    if place is None:
        return None, None, "your location"
    return place.lat, place.lon, place.label or "your location"


def units() -> str:
    """OpenWeatherMap units name: the country's convention or the user's preference."""
    from helpers import units as unit_rules

    return "imperial" if unit_rules.current().fahrenheit else "metric"


def temperature_symbol() -> str:
    return "°F" if units() == "imperial" else "°C"


def _wind_unit() -> str:
    """OpenWeatherMap reports mph only for imperial; metric is m/s."""
    return "mph" if units() == "imperial" else "m/s"


def _get_coordinates_for_city_name(
    city_name: str, api_key: str
) -> typing.Tuple[typing.Optional[float], typing.Optional[float]]:
    import requests

    from helpers import net

    try:
        # https, not http: the API key travels in the query string, so a plain
        # request puts it on the wire in cleartext.
        response = net.get(
            "https://api.openweathermap.org/geo/1.0/direct",
            params={"q": city_name, "appid": api_key, "limit": 1},
        )
        response.raise_for_status()
        data = response.json()
        if len(data) == 0:
            return None, None
        city = data[0]
        return city["lat"], city["lon"]
    except requests.exceptions.RequestException as e:
        logger.log_error(str(e), "get_coordinates_for_city_name")
        return None, None


def _get_weather_for_coordinates(
    lat: float, lon: float, api_key: str
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    import requests

    from helpers import net

    try:
        response = net.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": lat,
                "lon": lon,
                "appid": api_key,
                "units": units(),
            },
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.log_error(str(e), "get_weather_for_coordinates")
        return None


def _get_forecast_for_coordinates(
    lat: float, lon: float, api_key: str
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    import requests

    from helpers import net

    try:
        response = net.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "lat": lat,
                "lon": lon,
                "appid": api_key,
                "units": units(),
            },
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.log_error(str(e), "get_forecast_for_coordinates")
        return None
