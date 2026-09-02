import os
import typing

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement


@register_job(
    module_name="weather",
    requires=Requirement(
        env_vars=["WEATHER_API_KEY"],
        pip_modules=["geocoder", "requests"],
        setup_hint=(
            "Add WEATHER_API_KEY to .env (free key at openweathermap.org/api). "
            "pip install -r requirements/weather.txt"
        ),
    ),
)
@capture_response
def weather(city: str) -> str:
    """
    [STANDALONE JOB] Retrieves and provides real-time weather information for any city worldwide.
    This is an independent task that fetches weather data from external APIs and provides
    complete weather reports including temperature, conditions, and location details.

    Use this job when the user wants to:
    - Get current weather conditions for any location
    - Check temperature and weather descriptions
    - Obtain weather information using geolocation if no city is specified
    - Access meteorological data for planning activities

    Keywords: weather, forecast, current weather, get weather, check weather, city weather, location weather,
             temperature, conditions, meteorology, climate, outside weather

    Args:
        city (str): The name of the city for which to retrieve the weather.
                   If no city is specified by user the variable is set to empty string ("")
                   and the user's current geolocation is used.

    Returns:
        str: Complete weather report with city, conditions, and temperature information.
    """
    data = snapshot(city)
    if data["error"]:
        return f"Error: {data['error']}"

    return (
        f"The weather for {data['city']} is {data['description']} "
        f"with {data['temperature']}{data['unit']}."
    )


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
        "error": None,
    }

    api_key = os.environ.get("WEATHER_API_KEY")
    if not api_key:
        return {**empty, "error": "Weather API key not configured."}

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
        # The station's own town beats whatever was typed or the IP guessed.
        "city": data.get("name") or city,
        "description": conditions.get("description", ""),
        "temperature": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind": (data.get("wind") or {}).get("speed"),
        "icon": conditions.get("icon", ""),
        "condition": conditions.get("id", 0),
        "sunrise": (data.get("sys") or {}).get("sunrise"),
        "sunset": (data.get("sys") or {}).get("sunset"),
    }


def _here() -> typing.Tuple[
    typing.Optional[float], typing.Optional[float], str
]:
    """Where this device is, by IP. Rough, but it needs no setup from the user."""
    import geocoder

    try:
        located = geocoder.ip("me")
        lat, lon = located.latlng or (None, None)
        return lat, lon, located.city or "your location"
    except Exception as e:
        logger.log_error(str(e), "weather_geolocate")
        return None, None, "your location"


def units() -> str:
    """OpenWeatherMap units name from modules.weather.default_units."""
    from helpers.config import Config

    configured = str(Config.get("modules.weather.default_units", "metric")).lower()
    return configured if configured in ("metric", "imperial", "standard") else "metric"


def temperature_symbol() -> str:
    return {"metric": "°C", "imperial": "°F", "standard": "K"}[units()]


def _wind_unit() -> str:
    """OpenWeatherMap reports mph only for imperial; metric and standard are m/s."""
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
                "lang": "en",
            },
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.log_error(str(e), "get_weather_for_coordinates")
        return None
