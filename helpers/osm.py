"""OpenStreetMap's free public services: Nominatim (addresses), Overpass
(places by type) and the FOSSGIS OSRM servers (routes).

They are run by volunteers and each asks for the same courtesy: an honest
User-Agent, at most one request per second, and repeated questions answered
from a cache instead of asked again. Every answer built from them carries
ATTRIBUTION.
"""
import threading
import time
import typing

from helpers import net

ATTRIBUTION = "Map data © OpenStreetMap contributors"

_USER_AGENT = "Wony/1.0 (personal assistant; one user, low volume)"
_NOMINATIM = "https://nominatim.openstreetmap.org"
_OVERPASS = "https://overpass-api.de/api/interpreter"
_OSRM = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{coords}"

# The policy each of these servers states is one request per second.
_MIN_INTERVAL_SECONDS = 1.0
# Overpass queries can take a while on a busy server.
_OVERPASS_TIMEOUT = (5.0, 30.0)
_CACHE_SECONDS = 24 * 3600
_CACHE_MAX = 256

_last_call: typing.Dict[str, float] = {}
_throttle_lock = threading.Lock()
_cache: typing.Dict[str, typing.Tuple[float, typing.Any]] = {}


class OsmError(Exception):
    """A public server refused or failed; the message is fit to say aloud."""


def _wait_turn(host: str) -> None:
    with _throttle_lock:
        wait = _last_call.get(host, 0.0) + _MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def _cached(key: str, fetch: typing.Callable[[], typing.Any]) -> typing.Any:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    value = fetch()
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.time(), value)
    return value


def _get(host: str, url: str, **kwargs: typing.Any) -> typing.Any:
    _wait_turn(host)
    headers = {"User-Agent": _USER_AGENT, **kwargs.pop("headers", {})}
    try:
        response = net.get(url, headers=headers, **kwargs)
    except Exception as e:
        raise OsmError(f"OpenStreetMap's {host} server did not answer ({e}).") from e
    if response.status_code == 429:
        raise OsmError(f"OpenStreetMap's {host} server is busy — try again in a minute.")
    if response.status_code >= 400:
        raise OsmError(f"OpenStreetMap's {host} server said HTTP {response.status_code}.")
    return response.json()


def geocode(
    query: str,
    near: typing.Optional[typing.Tuple[float, float]] = None,
    limit: int = 1,
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Places matching `query` (an address or a name), nearest `near` first when given."""
    params: typing.Dict[str, typing.Any] = {
        "q": query, "format": "jsonv2", "limit": limit, "addressdetails": 0,
    }
    if near:
        lat, lon = near
        # About ±10 km: a "near me" search, not a search of the whole country.
        params["viewbox"] = f"{lon - 0.15},{lat + 0.1},{lon + 0.15},{lat - 0.1}"
        params["bounded"] = 1
    key = f"geocode|{query}|{near}|{limit}"
    return _cached(key, lambda: _get(
        "nominatim", f"{_NOMINATIM}/search", params=params,
        headers={"Accept-Language": "en"},
    ))


def overpass(query: str) -> typing.List[typing.Dict[str, typing.Any]]:
    """Elements for an Overpass QL query."""
    return _cached(f"overpass|{query}", lambda: _get(
        "overpass", _OVERPASS, params={"data": query}, timeout=_OVERPASS_TIMEOUT,
    ).get("elements", []))


def route(
    origin: typing.Tuple[float, float],
    destination: typing.Tuple[float, float],
    profile: str,
) -> typing.Dict[str, float]:
    """{"seconds", "meters"} for a car / bike / foot route between two points."""
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    url = _OSRM.format(profile=profile, coords=coords)
    data = _cached(f"route|{url}", lambda: _get("routing", url, params={"overview": "false"}))
    routes = data.get("routes") or []
    if data.get("code") != "Ok" or not routes:
        raise OsmError("OpenStreetMap could not find a route between those places.")
    return {"seconds": float(routes[0]["duration"]), "meters": float(routes[0]["distance"])}
