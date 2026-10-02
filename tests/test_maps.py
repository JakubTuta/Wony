"""Maps answers from OpenStreetMap by default and from Google when a key is
set — but Google bills past a free monthly allowance, so Wony must count its
own requests and switch back before that allowance runs out. No network here:
every server answer is recorded.

Run directly: python tests/test_maps.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

_HERE = (50.0619, 19.9369)  # Kraków main square

_OVERPASS_PHARMACIES = [
    {"type": "node", "lat": 50.0625, "lon": 19.9370,
     "tags": {"name": "Apteka Rynek", "addr:street": "Rynek", "addr:housenumber": "1", "opening_hours": "24/7"}},
    {"type": "way", "center": {"lat": 50.0700, "lon": 19.9400}, "tags": {"name": "Dr. Max"}},
    {"type": "node", "lat": 50.0620, "lon": 19.9369, "tags": {}},  # unnamed: skipped
]

_GOOGLE_PLACES = {"places": [{
    "displayName": {"text": "Pizzeria Roma"}, "formattedAddress": "Floriańska 1, Kraków",
    "location": {"latitude": 50.0630, "longitude": 19.9390}, "googleMapsUri": "https://maps.google.com/?cid=1",
    "rating": 4.6, "userRatingCount": 812, "currentOpeningHours": {"openNow": True},
    "priceLevel": "PRICE_LEVEL_MODERATE",
}]}


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


class MapsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        import helpers.memory_db as db

        self._tmpdir = tempfile.TemporaryDirectory()
        self._real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(self._tmpdir.name, "test.db")
        from helpers.location import Place

        for target, value in (
            ("helpers.location.here", Place(*_HERE, "", "windows")),
            ("helpers.units.region_country", "PL"),
            ("helpers.profile.Profile.get", None),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        import helpers.memory_db as db

        db.close()
        db._DB_FILE = self._real_db_file
        self._tmpdir.cleanup()


class TestOpenStreetMap(MapsTestCase):
    def test_category_search_goes_to_overpass_nearest_first(self) -> None:
        from modules import maps

        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}), \
                mock.patch("helpers.osm.overpass", return_value=_OVERPASS_PHARMACIES) as overpass:
            out = maps.find_places("pharmacy open late", limit=2)
        self.assertIn('"amenity"="pharmacy"', overpass.call_args[0][0])
        self.assertLess(out.index("Apteka Rynek"), out.index("Dr. Max"))
        self.assertIn("hours: 24/7", out)
        self.assertIn("OpenStreetMap contributors", out)  # attribution is required
        self.assertIn('<<<untrusted source="maps">>>', out)

    def test_open_now_without_google_says_it_cannot_tell(self) -> None:
        from modules import maps

        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}), \
                mock.patch("helpers.osm.overpass", return_value=_OVERPASS_PHARMACIES):
            out = maps.find_places("pharmacy", open_now=True)
        self.assertIn("can't tell what is open", out)

    def test_driving_time_warns_about_traffic_and_transit_is_honest(self) -> None:
        from modules import maps

        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}), \
                mock.patch("helpers.osm.geocode", return_value=[{"lat": "52.23", "lon": "21.01"}]), \
                mock.patch("helpers.osm.route", return_value={"seconds": 12000.0, "meters": 296000.0}):
            car = maps.directions("Warsaw", mode="car")
            transit = maps.directions("Warsaw", mode="transit")
        self.assertIn("3 h 20 min", car)
        self.assertIn("296.0 km", car)
        self.assertIn("no live traffic", car)
        self.assertIn("no public transport", transit)
        self.assertIn("travelmode=transit", transit)


class TestGoogle(MapsTestCase):
    def test_places_carry_rating_price_and_open_now(self) -> None:
        from modules import maps

        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}), \
                mock.patch("helpers.net.post", return_value=_Response(_GOOGLE_PLACES)) as post:
            out = maps.find_places("pizza", open_now=True)
        body = post.call_args.kwargs["json"]
        self.assertTrue(body["openNow"])
        self.assertIn("locationBias", body)
        self.assertIn("places.rating", post.call_args.kwargs["headers"]["X-Goog-FieldMask"])
        for expected in ("Pizzeria Roma", "rated 4.6 (812 reviews)", "open now", "$$"):
            self.assertIn(expected, out)
        self.assertNotIn("OpenStreetMap", out)

    def test_allowance_steps_down_then_hands_over_to_openstreetmap(self) -> None:
        """At 90% of a free tier Wony drops the costly fields, then Google."""
        from helpers.memory_db import set_kv
        from modules import maps

        month = maps._month()
        set_kv(f"maps.billing.{month}.places.enterprise", "900")
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}), \
                mock.patch("helpers.net.post", return_value=_Response(_GOOGLE_PLACES)) as post:
            maps.find_places("pizza")
        self.assertNotIn("places.rating", post.call_args.kwargs["headers"]["X-Goog-FieldMask"])

        set_kv(f"maps.billing.{month}.places.pro", "4500")
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}), \
                mock.patch("helpers.net.post") as post, \
                mock.patch("helpers.osm.overpass", return_value=_OVERPASS_PHARMACIES):
            out = maps.find_places("pharmacy")
        post.assert_not_called()
        self.assertIn("allowance", out)
        self.assertIn("OpenStreetMap contributors", out)

    def test_a_rejected_key_falls_back_and_says_why(self) -> None:
        from modules import maps

        refused = _Response({"error": {"message": "API key not valid."}}, status=400)
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "bad"}), \
                mock.patch("helpers.net.post", return_value=refused), \
                mock.patch("helpers.osm.overpass", return_value=_OVERPASS_PHARMACIES):
            out = maps.find_places("pharmacy")
        self.assertIn("API key not valid", out)
        self.assertIn("Apteka Rynek", out)

    def test_driving_uses_traffic_and_counts_as_pro(self) -> None:
        from helpers.memory_db import get_kv
        from modules import maps

        route = {"routes": [{"duration": "3700s", "distanceMeters": 52000, "description": "A4"}]}
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}), \
                mock.patch("helpers.net.post", return_value=_Response(route)) as post:
            out = maps.directions("Katowice", mode="car")
        self.assertEqual(post.call_args.kwargs["json"]["routingPreference"], "TRAFFIC_AWARE")
        self.assertIn("1 h 2 min", out)
        self.assertIn("current traffic", out)
        self.assertEqual(get_kv(f"maps.billing.{maps._month()}.routes.pro"), "1")


class TestLocationOrder(unittest.TestCase):
    """A precise Windows fix wins; a typed home address beats a coarse one;
    the internet guess is the last resort."""

    def _here(self, fix, home, internet):
        from helpers import location
        from helpers.location import Place

        location._cache.clear()
        home_place = Place(1.0, 1.0, "Home St 1", "home") if home else None
        net_place = Place(2.0, 2.0, "Kraków", "internet") if internet else None
        with mock.patch.object(location, "_windows_fix", return_value=fix), \
                mock.patch.object(location, "_home", return_value=home_place), \
                mock.patch.object(location, "_internet", return_value=net_place):
            place = location.here()
        location._cache.clear()
        return place.source if place else None

    def test_order(self) -> None:
        from helpers.location import Place

        precise = (Place(3.0, 3.0, "", "windows"), 30.0)
        coarse = (Place(3.0, 3.0, "", "windows"), 7000.0)
        self.assertEqual(self._here(precise, home=True, internet=True), "windows")
        self.assertEqual(self._here(coarse, home=True, internet=True), "home")
        self.assertEqual(self._here(coarse, home=False, internet=True), "windows")
        self.assertEqual(self._here(None, home=False, internet=True), "internet")
        self.assertIsNone(self._here(None, home=False, internet=False))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
