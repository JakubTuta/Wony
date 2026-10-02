"""Where this device is, for local weather.

Best source first: the home address from Settings, then a guess from the
internet connection, which is only good to roughly the city. (Windows' location
service is tried first on a PC; on the Pi it is simply absent.)
"""
import threading
import time
import typing

# Windows reports how sure it is. A desktop without Wi-Fi often gets a fix good
# only to several kilometres; past this a typed home address is better.
_PRECISE_METRES = 1000.0
_WINDOWS_TIMEOUT_SECONDS = 6.0
# A desktop does not move; a laptop that does is right again within minutes.
_WINDOWS_TTL_SECONDS = 600.0
_INTERNET_TTL_SECONDS = 6 * 3600.0

_lock = threading.Lock()
_cache: typing.Dict[str, typing.Tuple[float, typing.Any]] = {}


class Place(typing.NamedTuple):
    lat: float
    lon: float
    label: str  # "" when the source gives no name for it
    source: str  # "windows", "home" or "internet"

    @property
    def approximate(self) -> bool:
        return self.source == "internet"


def _remember(key: str, ttl: float, fetch: typing.Callable[[], typing.Any]) -> typing.Any:
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    place = fetch()
    with _lock:
        _cache[key] = (time.time(), place)
    return place


def _windows_fix() -> typing.Optional[typing.Tuple[Place, float]]:
    """(place, accuracy in metres) from Windows, or None when it is off or denied."""
    try:
        import asyncio

        from winrt.windows.devices.geolocation import GeolocationAccessStatus, Geolocator
    except ImportError:
        return None

    async def ask() -> typing.Optional[typing.Tuple[Place, float]]:
        if await Geolocator.request_access_async() != GeolocationAccessStatus.ALLOWED:
            return None
        position = await asyncio.wait_for(Geolocator().get_geoposition_async(), _WINDOWS_TIMEOUT_SECONDS)
        point = position.coordinate.point.position
        return Place(point.latitude, point.longitude, "", "windows"), float(position.coordinate.accuracy)

    try:
        return asyncio.run(ask())
    except Exception:
        return None  # location service off, timed out, or no positioning hardware


def windows_status() -> str:
    """One line for doctor and setup: is Windows location usable?"""
    fix = _windows_fix()
    if fix is None:
        return "off or not allowed for desktop apps"
    return f"on (accurate to about {round(fix[1])} m)"


def _home() -> typing.Optional[Place]:
    from helpers.config import Config

    address = str(Config.get("assistant.home_address", "") or "").strip()
    if not address:
        return None

    def geocode() -> typing.Optional[Place]:
        from helpers import osm

        try:
            hits = osm.geocode(address)
        except osm.OsmError:
            return None
        if not hits:
            return None
        return Place(float(hits[0]["lat"]), float(hits[0]["lon"]), address, "home")

    return _remember(f"home|{address}", float("inf"), geocode)


def _internet() -> typing.Optional[Place]:
    def lookup() -> typing.Optional[Place]:
        from helpers import net

        try:
            data = net.get("https://ipinfo.io/json").json()
            lat, lon = (float(x) for x in data["loc"].split(","))
        except Exception:
            return None
        return Place(lat, lon, data.get("city", ""), "internet")

    return _remember("internet", _INTERNET_TTL_SECONDS, lookup)


def here() -> typing.Optional[Place]:
    """This computer's location from the best source available, or None."""
    fix = _remember("windows", _WINDOWS_TTL_SECONDS, _windows_fix)
    if fix and fix[1] <= _PRECISE_METRES:
        return fix[0]
    home = _home()
    if home:
        return home
    if fix:
        return fix[0]
    return _internet()

