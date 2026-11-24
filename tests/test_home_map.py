"""The Smart home map: one floor plan and where devices sit on it.

Everything a caller can send ends up in wony.db, so the checks here are the
whole defence: what counts as an image, how big, and what a placement may say.

Run directly: python tests/test_home_map.py
"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from PIL import Image  # noqa: E402


def _load_app():
    from fastapi.testclient import TestClient

    from helpers.config import Config

    Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
    import modules  # noqa: F401  (import triggers discover_services)
    from helpers.web_app import build_app

    return TestClient(build_app(), base_url="http://127.0.0.1:8123")


def _png(width: int = 40, height: int = 20) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


class TestHomeMapEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import helpers.memory_db as db

        cls.db = db
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._real_db_file = db._DB_FILE
        db.close()
        db._DB_FILE = os.path.join(cls._tmpdir.name, "test.db")
        cls.client = _load_app()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.db._DB_FILE = cls._real_db_file
        cls._tmpdir.cleanup()

    def setUp(self) -> None:
        from helpers import home_map
        from helpers.config import Config

        self.home_map = home_map
        patcher = mock.patch.object(Config, "enabled_modules", return_value={"home_assistant"})
        patcher.start()
        self.addCleanup(patcher.stop)
        home_map.delete()

    def _upload(self, data: bytes):
        return self.client.put(
            "/api/devices/map/image", content=data, headers={"Content-Type": "application/octet-stream"}
        )

    def _place(self, placements):
        return self.client.put("/api/devices/map/placements", json={"placements": placements})

    # ── gate ─────────────────────────────────────────────────────────────

    def test_every_route_is_refused_while_home_assistant_is_off(self) -> None:
        from helpers.config import Config

        with mock.patch.object(Config, "enabled_modules", return_value=set()):
            self.assertEqual(self.client.get("/api/devices/map").status_code, 503)
            self.assertEqual(self._upload(_png()).status_code, 503)
            self.assertEqual(self.client.get("/api/devices/map/image").status_code, 503)
            self.assertEqual(self._place([]).status_code, 503)
            self.assertEqual(self.client.delete("/api/devices/map").status_code, 503)

    # ── image ────────────────────────────────────────────────────────────

    def test_there_is_no_map_until_one_is_uploaded(self) -> None:
        self.assertEqual(self.client.get("/api/devices/map").json(), {"image": None, "placements": []})
        self.assertEqual(self.client.get("/api/devices/map/image").status_code, 404)

    def test_an_upload_is_stored_and_served_back(self) -> None:
        resp = self._upload(_png(40, 20))
        self.assertEqual(resp.status_code, 200)
        image = resp.json()["image"]
        self.assertEqual((image["width"], image["height"]), (40, 20))

        served = self.client.get(image["url"])
        self.assertEqual(served.headers["content-type"], "image/webp")
        self.assertEqual(served.headers["x-content-type-options"], "nosniff")
        self.assertEqual(Image.open(io.BytesIO(served.content)).size, (40, 20))

    def test_a_huge_picture_is_shrunk(self) -> None:
        image = self._upload(_png(3000, 1000)).json()["image"]
        self.assertEqual((image["width"], image["height"]), (2400, 800))

    def test_a_phone_photo_is_turned_upright_and_loses_its_exif(self) -> None:
        """Orientation 6 is a sideways picture plus a rotate flag; the GPS and
        make/model in the same block must not be kept."""
        exif = Image.Exif()
        exif[0x010F] = "SecretPhone"
        exif[0x0112] = 6
        photo = io.BytesIO()
        Image.new("RGB", (40, 20), "white").save(photo, "JPEG", exif=exif)

        image = self._upload(photo.getvalue()).json()["image"]
        self.assertEqual((image["width"], image["height"]), (20, 40))

        stored = self.client.get(image["url"]).content
        self.assertEqual(len(Image.open(io.BytesIO(stored)).getexif()), 0)
        self.assertNotIn(b"SecretPhone", stored)

    def test_what_is_not_a_png_jpg_or_webp_is_refused(self) -> None:
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        for data in (b"hello", b"", svg):
            with self.subTest(data=data[:12]):
                resp = self._upload(data)
                self.assertEqual(resp.status_code, 422)
                self.assertIn("PNG, JPG or WebP", resp.json()["detail"])
        self.assertIsNone(self.client.get("/api/devices/map").json()["image"])

    def test_a_gif_is_refused_too(self) -> None:
        gif = io.BytesIO()
        Image.new("RGB", (4, 4)).save(gif, "GIF")
        self.assertEqual(self._upload(gif.getvalue()).status_code, 422)

    def test_a_picture_with_too_many_pixels_is_refused(self) -> None:
        with mock.patch.object(self.home_map, "_MAX_PIXELS", 100):
            resp = self._upload(_png(40, 20))
        self.assertEqual(resp.status_code, 422)
        self.assertIn("too large", resp.json()["detail"])

    def test_an_oversize_body_is_refused_before_it_is_read(self) -> None:
        with mock.patch.object(self.home_map, "MAX_UPLOAD_BYTES", 100):
            resp = self._upload(b"x" * 200)
        self.assertEqual(resp.status_code, 413)

    # ── placements ───────────────────────────────────────────────────────

    def test_placements_need_a_map_first(self) -> None:
        resp = self._place([{"entity_id": "light.lamp", "x": 0.5, "y": 0.5}])
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Upload a map image first", resp.json()["detail"])

    def test_placements_round_trip(self) -> None:
        self._upload(_png())
        placements = [
            {"entity_id": "light.lamp", "x": 0.25, "y": 0.75},
            {"entity_id": "switch.kettle", "x": 0.5, "y": 0.5},
        ]
        self.assertEqual(self._place(placements).status_code, 200)
        self.assertEqual(self.client.get("/api/devices/map").json()["placements"], placements)

    def test_a_position_off_the_picture_is_pulled_back_onto_it(self) -> None:
        self._upload(_png())
        self._place([{"entity_id": "light.lamp", "x": 1.5, "y": -2}])
        placed = self.client.get("/api/devices/map").json()["placements"]
        self.assertEqual((placed[0]["x"], placed[0]["y"]), (1.0, 0.0))

    def test_a_device_cannot_be_in_two_places(self) -> None:
        self._upload(_png())
        self._place([
            {"entity_id": "light.lamp", "x": 0.1, "y": 0.1},
            {"entity_id": "light.lamp", "x": 0.9, "y": 0.9},
        ])
        placed = self.client.get("/api/devices/map").json()["placements"]
        self.assertEqual(placed, [{"entity_id": "light.lamp", "x": 0.9, "y": 0.9}])

    def test_anything_that_is_not_a_device_id_is_refused(self) -> None:
        self._upload(_png())
        for bad in ("Light.Lamp", "lamp", "light.", "light.a b", "../etc/passwd", "light.x" + "y" * 200):
            with self.subTest(entity_id=bad):
                self.assertEqual(self._place([{"entity_id": bad, "x": 0.5, "y": 0.5}]).status_code, 422)

    def test_the_number_of_devices_is_capped(self) -> None:
        self._upload(_png())
        many = [{"entity_id": f"light.l{i}", "x": 0.5, "y": 0.5} for i in range(201)]
        self.assertEqual(self._place(many).status_code, 422)

    def test_a_position_must_be_a_real_number(self) -> None:
        self._upload(_png())
        for bad in (float("nan"), float("inf"), True, "0.5", None):
            with self.subTest(x=bad):
                with self.assertRaises(ValueError):
                    self.home_map.save_placements([{"entity_id": "light.lamp", "x": bad, "y": 0.5}])

    # ── lifecycle ────────────────────────────────────────────────────────

    def test_replacing_the_picture_keeps_the_placements(self) -> None:
        self._upload(_png())
        placements = [{"entity_id": "light.lamp", "x": 0.3, "y": 0.6}]
        self._place(placements)

        again = self._upload(_png(80, 40)).json()
        self.assertEqual(again["placements"], placements)
        self.assertEqual(again["image"]["width"], 80)

    def test_removing_the_map_removes_both(self) -> None:
        self._upload(_png())
        self._place([{"entity_id": "light.lamp", "x": 0.3, "y": 0.6}])
        self.assertEqual(self.client.delete("/api/devices/map").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/devices/map").json(), {"image": None, "placements": []})


    # ── the devices panel the page reads ─────────────────────────────────

    def test_the_devices_panel_carries_readings_over_http(self) -> None:
        """The list shows what a device reports from this payload alone."""
        from modules import home_assistant as ha

        entity = ha._Entity
        index = [
            entity("vacuum.robot", "Robot", "Utility", "docked", "", "", "", "Robot"),
            entity("sensor.robot_battery", "Robot Battery", "Utility", "79", "battery", "", "", "Robot", unit="%"),
        ]
        with mock.patch.object(ha, "_fetch_index", return_value=index):
            body = self.client.get("/api/panel/devices").json()

        device = body["areas"][0]["devices"][0]
        self.assertEqual(device["readings"], [{"name": "Battery", "value": "79 %"}])


class TestHomeMapWipe(unittest.TestCase):
    def test_wipe_removes_the_floor_plan(self) -> None:
        """A floor plan is the layout of a home. Wipe has to mean it."""
        from helpers import memory_db

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        memory_db._init_schema(conn)

        with mock.patch.object(memory_db, "_conn", conn):
            memory_db.save_home_map_image(b"x", "image/webp", 1, 1)
            memory_db.wipe_all()
            self.assertIsNone(memory_db.get_home_map())


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
