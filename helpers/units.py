"""Which units to answer in, without asking the user to configure it.

The country's own convention (from the device's locale) decides, and a
spoken preference remembered as the `preferred_units` fact wins over that.
"""
import locale
import typing

# Countries that use Fahrenheit and miles. Everywhere else is metric, except
# the UK, which uses Celsius but measures roads in miles.
_FAHRENHEIT_AND_MILES = {"US", "LR", "MM"}
_CELSIUS_AND_MILES = {"GB"}


class Units(typing.NamedTuple):
    fahrenheit: bool
    miles: bool


def region_country() -> str:
    """Two-letter country code of this device's locale, or "" if unknown."""
    name = locale.getlocale()[0] or ""
    # "en_US" / "English_United States" — only the first form carries a code.
    _, _, country = name.partition("_")
    return country.upper() if len(country) == 2 else ""


def for_country(country: str) -> Units:
    country = country.upper()
    if country in _FAHRENHEIT_AND_MILES:
        return Units(fahrenheit=True, miles=True)
    if country in _CELSIUS_AND_MILES:
        return Units(fahrenheit=False, miles=True)
    return Units(fahrenheit=False, miles=False)


def _from_preference(text: str, fallback: Units) -> Units:
    """Read a remembered preference like "imperial", "Fahrenheit" or "km"."""
    words = text.lower()
    fahrenheit, miles = fallback
    if "imperial" in words:
        return Units(True, True)
    if "metric" in words:
        return Units(False, False)
    if "fahrenheit" in words:
        fahrenheit = True
    if "celsius" in words or "centigrade" in words:
        fahrenheit = False
    if "mile" in words:
        miles = True
    if "km" in words or "kilomet" in words:
        miles = False
    return Units(fahrenheit, miles)


def current() -> Units:
    regional = for_country(region_country())
    try:
        from helpers.profile import Profile

        preference = Profile.get("preferred_units")
    except Exception:
        preference = None
    return _from_preference(preference, regional) if preference else regional
