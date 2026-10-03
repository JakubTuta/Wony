"""Where this device is, for local weather.

Best source first: the home address from Settings, then a guess from the
internet connection, which is only good to roughly the city.
"""
import threading
import time
import typing

_INTERNET_TTL_SECONDS = 6 * 3600.0

_lock = threading.Lock()
_cache: typing.Dict[str, typing.Tuple[float, typing.Any]] = {}


class Place(typing.NamedTuple):
    lat: float
    lon: float
    label: str  # "" when the source gives no name for it
    source: str  # "home" or "internet"

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
    """This device's location from the best source available, or None."""
    return _home() or _internet()

