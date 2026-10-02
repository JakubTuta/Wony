"""Places near you and how long it takes to get somewhere.

OpenStreetMap answers by default and needs no account. A Google Maps key
(GOOGLE_MAPS_API_KEY in .env) adds ratings, opening hours, live traffic and
public transport. Google bills per request beyond a free monthly allowance, so
Wony counts its own requests and goes back to OpenStreetMap before the
allowance runs out.
"""

import math
import os
import typing
import urllib.parse
from datetime import datetime

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.untrusted import wrap

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Google's free monthly allowance per SKU, and the share of it Wony will use.
# Past that share it answers from OpenStreetMap until the month turns.
_FREE_PER_MONTH = {"essentials": 10000, "pro": 5000, "enterprise": 1000}
_SAFE_SHARE = 0.9

# What each Text Search field mask costs: names and addresses are "Pro";
# rating, open-now and price are "Enterprise".
_PRO_FIELDS = [
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.googleMapsUri",
]
_ENTERPRISE_FIELDS = [
    "places.rating",
    "places.userRatingCount",
    "places.currentOpeningHours.openNow",
    "places.priceLevel",
]
_ROUTE_FIELDS = "routes.duration,routes.distanceMeters,routes.description"

# "Near me" means walking-ish distance first, a short drive if that finds little.
_NEAR_RADII_METRES = (1500, 5000)
_GOOGLE_BIAS_METRES = 5000.0
_MAX_PLACES = 10

_PRICE = {
    "PRICE_LEVEL_FREE": "free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}

# Words people say -> the OpenStreetMap tags that mean them. A category search
# finds every pharmacy; a name search ("Lidl") goes to Nominatim instead.
_OSM_CATEGORIES: typing.Dict[str, str] = {
    "pharmacy": '["amenity"="pharmacy"]',
    "chemist": '["amenity"="pharmacy"]',
    "restaurant": '["amenity"="restaurant"]',
    "food": '["amenity"~"^(restaurant|fast_food)$"]',
    "pizza": '["amenity"~"^(restaurant|fast_food)$"]["cuisine"~"pizza"]',
    "sushi": '["amenity"~"^(restaurant|fast_food)$"]["cuisine"~"sushi"]',
    "burger": '["amenity"~"^(restaurant|fast_food)$"]["cuisine"~"burger"]',
    "kebab": '["amenity"~"^(restaurant|fast_food)$"]["cuisine"~"kebab"]',
    "fast food": '["amenity"="fast_food"]',
    "cafe": '["amenity"="cafe"]',
    "coffee": '["amenity"="cafe"]',
    "bar": '["amenity"="bar"]',
    "pub": '["amenity"="pub"]',
    "supermarket": '["shop"="supermarket"]',
    "grocery": '["shop"~"^(supermarket|convenience)$"]',
    "bakery": '["shop"="bakery"]',
    "atm": '["amenity"="atm"]',
    "cash machine": '["amenity"="atm"]',
    "bank": '["amenity"="bank"]',
    "gas station": '["amenity"="fuel"]',
    "petrol": '["amenity"="fuel"]',
    "fuel": '["amenity"="fuel"]',
    "charging": '["amenity"="charging_station"]',
    "hospital": '["amenity"="hospital"]',
    "doctor": '["amenity"="doctors"]',
    "dentist": '["amenity"="dentist"]',
    "vet": '["amenity"="veterinary"]',
    "parking": '["amenity"="parking"]',
    "hotel": '["tourism"="hotel"]',
    "post office": '["amenity"="post_office"]',
    "library": '["amenity"="library"]',
    "gym": '["leisure"="fitness_centre"]',
    "park": '["leisure"="park"]',
    "playground": '["leisure"="playground"]',
    "cinema": '["amenity"="cinema"]',
    "museum": '["tourism"="museum"]',
    "police": '["amenity"="police"]',
    "toilet": '["amenity"="toilets"]',
    "bus stop": '["highway"="bus_stop"]',
    "train station": '["railway"="station"]',
    "hairdresser": '["shop"="hairdresser"]',
}

# Spoken travel modes -> one of car / transit / walk / bike.
_MODES = {
    "car": "car",
    "drive": "car",
    "driving": "car",
    "transit": "transit",
    "public transport": "transit",
    "bus": "transit",
    "train": "transit",
    "walk": "walk",
    "walking": "walk",
    "foot": "walk",
    "bike": "bike",
    "cycling": "bike",
    "bicycle": "bike",
}
_OSM_PROFILE = {"car": "car", "walk": "foot", "bike": "bike"}
_GOOGLE_MODE = {"car": "DRIVE", "transit": "TRANSIT", "walk": "WALK", "bike": "BICYCLE"}
_MAPS_LINK_MODE = {
    "car": "driving",
    "transit": "transit",
    "walk": "walking",
    "bike": "bicycling",
}
_MODE_WORDS = {
    "car": "by car",
    "transit": "by public transport",
    "walk": "on foot",
    "bike": "by bike",
}


@register_job(module_name="maps", summary="Find places nearby")
@capture_response
def find_places(
    query: str, near: str = "", open_now: bool = False, limit: int = 5
) -> str:
    """
    [MAPS JOB] Finds places by type or by name — restaurants, a pharmacy, the nearest
    Lidl — near this computer or near a place the user names, with address and
    distance (and rating, price and open-now when Google Maps is set up).

    Args:
        query (str): What to look for, e.g. "pizza", "pharmacy", "Lidl". (required)
        near (str): Where to look around, e.g. "Kraków main square". Empty means near me.
        open_now (bool): Only places that are open right now.
        limit (int): How many to return (default 5).

    Returns:
        str: The places found, nearest or best first.
    """
    if not query.strip():
        return "Error: What kind of place should I look for?"
    count = max(1, min(int(limit or 5), _MAX_PLACES))

    center, where, approximate = _search_center(near)
    if center is None and not near:
        return (
            "I don't know where this computer is. Turn on Windows location, or set "
            "your home address in Settings."
        )

    note = ""
    if _google_key():
        try:
            places = _google_places(query, near, center, open_now, count)
            if places is not None:
                return _render_places(places, query, where, approximate, osm=False)
            note = "Google's free monthly allowance is nearly used up, so this is from OpenStreetMap."
        except _GoogleError as e:
            note = f"Google Maps failed ({e}), so this is from OpenStreetMap."

    if center is None:
        return f"I couldn't find '{near}' on the map."
    from helpers import osm

    try:
        places = _osm_places(query, center, count)
    except osm.OsmError as e:
        return str(e)
    text = _render_places(places, query, where, approximate, osm=True)
    if open_now:
        text += "\nOpenStreetMap can't tell what is open right now; the hours shown are what mappers recorded."
    return f"{note}\n{text}" if note else text


@register_job(module_name="maps", summary="Travel time and route to a place")
@capture_response
def directions(
    destination: str,
    origin: str = "",
    mode: typing.Literal["", "car", "transit", "walk", "bike"] = "",
    depart_at: str = "",
    arrive_by: str = "",
    open_map: bool = False,
) -> str:
    """
    [MAPS JOB] How far it is and how long it takes to get somewhere, with a Google
    Maps link for the route. Answers "how long to drive to Warsaw", "how do I get
    to the airport by bus", "how far is the station on foot".

    Args:
        destination (str): Where to go — an address, a place or a city. (required)
        origin (str): Where from. Empty means from here.
        mode (str): "car", "transit", "walk" or "bike". Empty uses the user's usual way
            of getting around.
        depart_at (str): When leaving, e.g. "8am tomorrow". Empty means now.
        arrive_by (str): When they need to be there (public transport only).
        open_map (bool): Also open the route in the browser.

    Returns:
        str: Duration and distance, and a link to the route.
    """
    if not destination.strip():
        return "Error: Where to?"
    how = _travel_mode(mode)
    link = _directions_link(origin, destination, how)
    if open_map:
        import webbrowser

        webbrowser.open(link)

    start = None
    if not origin:
        start = _here_or_none()
        if start is None:
            return (
                "I don't know where this computer is, so tell me where you're starting "
                f"from. The route in Google Maps: {link}"
            )

    note = ""
    if _google_key():
        try:
            answer = _google_route(
                origin, start, destination, how, depart_at, arrive_by
            )
            if answer is not None:
                return f"{answer}\nRoute: {link}"
            note = "Google's free monthly allowance is nearly used up, so this is from OpenStreetMap."
        except _GoogleError as e:
            note = f"Google Maps failed ({e}), so this is from OpenStreetMap."

    answer = _osm_route(origin, start, destination, how)
    parts = [p for p in (note, answer, f"Route: {link}") if p]
    return "\n".join(parts)


# ------------------------------------------------------------------ shared


def _google_key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def _language() -> str:
    from helpers.config import Config

    return str(Config.get("assistant.language", "en") or "en")


def _here_or_none() -> typing.Optional[typing.Tuple[float, float]]:
    from helpers.location import here

    place = here()
    return (place.lat, place.lon) if place else None


def _search_center(
    near: str,
) -> typing.Tuple[typing.Optional[typing.Tuple[float, float]], str, bool]:
    """(lat, lon) to search around, how to describe it, and whether it is a rough guess."""
    if near:
        from helpers import osm

        try:
            hits = osm.geocode(near, language=_language())
        except osm.OsmError:
            hits = []
        if hits:
            return (float(hits[0]["lat"]), float(hits[0]["lon"])), f"near {near}", False
        return None, f"near {near}", False

    from helpers.location import here

    place = here()
    if place is None:
        return None, "near you", False
    return (place.lat, place.lon), "near you", place.approximate


def _travel_mode(spoken: str) -> str:
    from helpers.config import Config

    wanted = (
        (spoken or str(Config.get("modules.maps.travel_mode", "car"))).strip().lower()
    )
    return _MODES.get(wanted, "car")


def _metres_between(
    a: typing.Tuple[float, float], b: typing.Tuple[float, float]
) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def _distance(metres: float) -> str:
    from helpers.units import current

    if current().miles:
        miles = metres / 1609.344
        return (
            f"{round(metres * 3.28084, -1):.0f} ft"
            if miles < 0.2
            else f"{miles:.1f} mi"
        )
    return f"{round(metres, -1):.0f} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def _duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def _directions_link(origin: str, destination: str, how: str) -> str:
    params = {
        "api": "1",
        "destination": destination,
        "travelmode": _MAPS_LINK_MODE[how],
    }
    if origin:
        params["origin"] = origin
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params)


def _place_link(name: str, lat: float, lon: float) -> str:
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": f"{name} {lat:.6f},{lon:.6f}"}
    )


def _render_places(
    places: typing.List[typing.Dict[str, typing.Any]],
    query: str,
    where: str,
    approximate: bool,
    osm: bool,
) -> str:
    from helpers import osm as osm_mod

    if not places:
        text = f"I found no '{query}' {where}."
        return f"{text} {osm_mod.ATTRIBUTION}." if osm else text

    lines = []
    for i, place in enumerate(places, 1):
        bits = [place["name"]]
        if place.get("address"):
            bits.append(place["address"])
        if place.get("metres") is not None:
            bits.append(_distance(place["metres"]))
        if place.get("rating"):
            bits.append(f"rated {place['rating']} ({place.get('ratings', 0)} reviews)")
        if place.get("open_now") is not None:
            bits.append("open now" if place["open_now"] else "closed now")
        if place.get("price"):
            bits.append(place["price"])
        if place.get("hours"):
            bits.append(f"hours: {place['hours']}")
        lines.append(f"{i}. " + " — ".join(bits) + f"\n   {place['url']}")

    header = (
        f"'{query}' {where}"
        + (" (your location is approximate)" if approximate else "")
        + ":"
    )
    # Names and addresses are written by businesses and mappers, not the user.
    text = header + "\n" + wrap("\n".join(lines), "maps")
    return f"{text}\n{osm_mod.ATTRIBUTION}." if osm else text


# ------------------------------------------------------------------ OpenStreetMap


def _osm_category(query: str) -> typing.Optional[str]:
    words = query.lower()
    matches = [key for key in _OSM_CATEGORIES if key in words]
    return _OSM_CATEGORIES[max(matches, key=len)] if matches else None


def _osm_places(
    query: str, center: typing.Tuple[float, float], count: int
) -> typing.List[typing.Dict[str, typing.Any]]:
    from helpers import osm

    tags = _osm_category(query)
    if tags is None:
        hits = osm.geocode(query, near=center, limit=count, language=_language())
        places = [
            {
                "name": hit.get("name") or hit.get("display_name", "").split(",")[0],
                "address": ", ".join(hit.get("display_name", "").split(", ")[1:4]),
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
            }
            for hit in hits
        ]
    else:
        places = []
        for radius in _NEAR_RADII_METRES:
            elements = osm.overpass(
                f'[out:json][timeout:25];nwr{tags}["name"](around:{radius},{center[0]},{center[1]});'
                f"out center tags {count * 4};"
            )
            places = [_osm_element(e) for e in elements]
            places = [p for p in places if p]
            if len(places) >= count:
                break

    for place in places:
        place["metres"] = _metres_between(center, (place["lat"], place["lon"]))
        place["url"] = _place_link(place["name"], place["lat"], place["lon"])
    places.sort(key=lambda p: p["metres"])
    return places[:count]


def _osm_element(
    element: typing.Dict[str, typing.Any],
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    tags = element.get("tags") or {}
    point = element if "lat" in element else element.get("center") or {}
    if not tags.get("name") or "lat" not in point:
        return None
    street = " ".join(
        p for p in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if p
    )
    address = ", ".join(p for p in (street, tags.get("addr:city", "")) if p)
    return {
        "name": tags["name"],
        "address": address,
        "lat": float(point["lat"]),
        "lon": float(point["lon"]),
        "hours": tags.get("opening_hours", ""),
    }


def _osm_route(
    origin: str,
    start: typing.Optional[typing.Tuple[float, float]],
    destination: str,
    how: str,
) -> str:
    from helpers import osm

    if how == "transit":
        return (
            "OpenStreetMap has no public transport timetables. A Google Maps key adds "
            "them; until then, the link below has the trip."
        )
    try:
        frm = start or _osm_point(origin)
        to = _osm_point(destination)
        if frm is None:
            return f"I couldn't find '{origin}' on the map."
        if to is None:
            return f"I couldn't find '{destination}' on the map."
        trip = osm.route(frm, to, _OSM_PROFILE[how])
    except osm.OsmError as e:
        return str(e)
    line = f"About {_duration(trip['seconds'])} {_MODE_WORDS[how]} ({_distance(trip['meters'])})."
    if how == "car":
        line += " That assumes empty roads — OpenStreetMap has no live traffic."
    return f"{line} {osm.ATTRIBUTION}."


def _osm_point(text: str) -> typing.Optional[typing.Tuple[float, float]]:
    from helpers import osm

    hits = osm.geocode(text, near=_here_or_none(), language=_language()) or osm.geocode(
        text, language=_language()
    )
    return (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None


# ------------------------------------------------------------------ Google


class _GoogleError(Exception):
    pass


def _month() -> str:
    return datetime.now().strftime("%Y-%m")


def _within_allowance(api: str, tier: str) -> bool:
    from helpers.memory_db import get_kv

    used = int(get_kv(f"maps.billing.{_month()}.{api}.{tier}", "0") or 0)
    return used < _FREE_PER_MONTH[tier] * _SAFE_SHARE


def _count_request(api: str, tier: str) -> None:
    from helpers.memory_db import get_kv, set_kv

    key = f"maps.billing.{_month()}.{api}.{tier}"
    used = int(get_kv(key, "0") or 0) + 1
    set_kv(key, str(used))
    if used == int(_FREE_PER_MONTH[tier] * _SAFE_SHARE):
        from helpers.notify import notify

        notify(
            f"Google Maps {api} has used 90% of this month's free allowance, so I'll "
            "use OpenStreetMap for it until next month.",
            kind="alert",
            source="maps",
        )


def usage_this_month() -> typing.Dict[str, int]:
    """Requests counted per API and tier this month, for doctor."""
    from helpers.memory_db import get_kv

    out = {}
    for api in ("places", "routes"):
        for tier in _FREE_PER_MONTH:
            used = int(get_kv(f"maps.billing.{_month()}.{api}.{tier}", "0") or 0)
            if used:
                out[f"{api} {tier}"] = used
    return out


def _google_post(
    url: str, body: typing.Dict[str, typing.Any], fields: str
) -> typing.Dict[str, typing.Any]:
    from helpers import net

    headers = {"X-Goog-Api-Key": _google_key(), "X-Goog-FieldMask": fields}
    try:
        response = net.post(url, json=body, headers=headers)
    except Exception as e:
        raise _GoogleError(f"no answer: {e}") from e
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = f"HTTP {response.status_code}"
        logger.log_error(message, "maps.google")
        raise _GoogleError(message)
    return response.json()


def _google_places(
    query: str,
    near: str,
    center: typing.Optional[typing.Tuple[float, float]],
    open_now: bool,
    count: int,
) -> typing.Optional[typing.List[typing.Dict[str, typing.Any]]]:
    """Places from Google, or None when this month's allowance is spent."""
    if _within_allowance("places", "enterprise"):
        tier, fields = "enterprise", _PRO_FIELDS + _ENTERPRISE_FIELDS
    elif _within_allowance("places", "pro"):
        tier, fields = "pro", _PRO_FIELDS
    else:
        return None

    body: typing.Dict[str, typing.Any] = {
        "textQuery": f"{query} near {near}" if near else query,
        "pageSize": count,
        "languageCode": _language(),
    }
    if center and not near:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": center[0], "longitude": center[1]},
                "radius": _GOOGLE_BIAS_METRES,
            }
        }
    if open_now:
        body["openNow"] = True

    data = _google_post(_PLACES_URL, body, ",".join(fields))
    _count_request("places", tier)
    places = []
    for item in data.get("places", []):
        point = item.get("location") or {}
        place = {
            "name": (item.get("displayName") or {}).get("text", ""),
            "address": item.get("formattedAddress", ""),
            "lat": point.get("latitude", 0.0),
            "lon": point.get("longitude", 0.0),
            "url": item.get("googleMapsUri", ""),
            "rating": item.get("rating"),
            "ratings": item.get("userRatingCount", 0),
            "open_now": (item.get("currentOpeningHours") or {}).get("openNow"),
            "price": _PRICE.get(item.get("priceLevel", ""), ""),
        }
        if center:
            place["metres"] = _metres_between(center, (place["lat"], place["lon"]))
        places.append(place)
    return places


def _google_route(
    origin: str,
    start: typing.Optional[typing.Tuple[float, float]],
    destination: str,
    how: str,
    depart_at: str,
    arrive_by: str,
) -> typing.Optional[str]:
    """A route summary from Google, or None when this month's allowance is spent."""
    from helpers.timeutil import parse_when
    from helpers.units import current

    traffic = how == "car" and _within_allowance("routes", "pro")
    tier = "pro" if traffic else "essentials"
    if not _within_allowance("routes", tier):
        return None

    def waypoint(
        text: str, point: typing.Optional[typing.Tuple[float, float]]
    ) -> typing.Dict[str, typing.Any]:
        if point:
            return {
                "location": {"latLng": {"latitude": point[0], "longitude": point[1]}}
            }
        return {"address": text}

    body: typing.Dict[str, typing.Any] = {
        "origin": waypoint(origin, start),
        "destination": waypoint(destination, None),
        "travelMode": _GOOGLE_MODE[how],
        "languageCode": _language(),
        "units": "IMPERIAL" if current().miles else "METRIC",
    }
    if traffic:
        body["routingPreference"] = "TRAFFIC_AWARE"
    note = ""
    if depart_at:
        when = parse_when(depart_at)
        if when is None:
            return f"I couldn't understand the time '{depart_at}'."
        body["departureTime"] = when.isoformat()
    if arrive_by:
        when = parse_when(arrive_by)
        if when is None:
            return f"I couldn't understand the time '{arrive_by}'."
        if how == "transit":
            body["arrivalTime"] = when.isoformat()
        else:
            note = " (Arrival times only work for public transport; this is for leaving now.)"

    data = _google_post(_ROUTES_URL, body, _ROUTE_FIELDS)
    _count_request("routes", tier)
    routes = data.get("routes") or []
    if not routes:
        return "Google Maps found no route between those places."
    best = routes[0]
    seconds = float(str(best.get("duration", "0s")).rstrip("s") or 0)
    line = f"About {_duration(seconds)} {_MODE_WORDS[how]} ({_distance(float(best.get('distanceMeters', 0)))})"
    if best.get("description"):
        line += f", via {best['description']}"
    line += "."
    if traffic:
        line += " That includes current traffic."
    return line + note
