import os
import typing

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
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
    import geocoder

    api_key = os.environ.get("WEATHER_API_KEY")
    if not api_key:
        return "Error: Weather API key not configured."

    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Getting weather...")
    print("Getting weather...")

    if city == "":
        my_geolocation = geocoder.ip("me")
        city = my_geolocation.city
        lat, lon = my_geolocation.latlng
    else:
        lat, lon = _get_coordinates_for_city_name(city, api_key)

    if lat is None or lon is None:
        return "Error: Could not retrieve coordinates for the given city."

    weather_data = _get_weather_for_coordinates(lat, lon, api_key)

    if weather_data is None:
        return "Error: Could not retrieve weather information."

    return f"The weather for {city} is {weather_data['weather'][0]['description']} with {weather_data['main']['temp']}°C."


def _get_coordinates_for_city_name(
    city_name: str, api_key: str
) -> typing.Tuple[typing.Optional[float], typing.Optional[float]]:
    """Get coordinates for a city name."""
    import requests

    try:
        response = requests.get(
            f"http://api.openweathermap.org/geo/1.0/direct?q={city_name}&appid={api_key}&limit=1"
        )
        data = response.json()

        if len(data) == 0:
            return None, None

        city = data[0]
        return city["lat"], city["lon"]

    except requests.exceptions.RequestException as e:
        print(f"Error fetching coordinates: {e}")
        return None, None


def _get_weather_for_coordinates(
    lat: float, lon: float, api_key: str
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    """Get weather data for coordinates."""
    import requests

    try:
        response = requests.get(
            f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=en"
        )
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None
