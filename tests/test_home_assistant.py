"""Home Assistant entity resolution, service mapping, and the lock safety gate.

All of it is pure logic over a device index, so it runs without a Home
Assistant to talk to. The lock gate is the reason this file exists: nothing
else would notice if a refactor let 'turn off the hallway' start unlocking the
front door.

Run directly: python tests/test_home_assistant.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _index(ha):
    E = ha._Entity
    return [
        E("light.kitchen_ceiling", "Ceiling", "Kitchen", "off", ""),
        E("light.kitchen_counter", "Counter Lights", "Kitchen", "on", ""),
        E("light.bedroom_lamp", "Bedroom Lamp", "Bedroom", "off", ""),
        E("sensor.kitchen_temp", "Temperature", "Kitchen", "21.5", "temperature"),
        E("binary_sensor.kitchen_motion", "Motion", "Kitchen", "off", "motion"),
        E("cover.garage_door", "Garage Door", "Garage", "closed", "garage"),
        E("cover.living_blinds", "Blinds", "Living Room", "open", "blind"),
        E("lock.front_door", "Front Door", "Hallway", "locked", ""),
        E("climate.thermostat", "Thermostat", "Hallway", "heat", ""),
        E("scene.movie_night", "Movie Night", "", "unknown", ""),
    ]


class TestHomeAssistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("HOME_ASSISTANT_TOKEN", "test-token")
        from helpers.config import Config

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))

        import modules.home_assistant as ha
        from helpers.decorators import set_agent_active

        # Same switch the agent loop uses: stops capture_response echoing every
        # job's return value into the test output.
        set_agent_active(True)

        cls.ha = ha
        cls.index = _index(ha)
        cls.calls: list = []

        ha._fetch_index = lambda: cls.index
        ha._call_service = lambda domain, service, ids, extra: cls.calls.append(
            (domain, service, sorted(ids), extra)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        from helpers.decorators import set_agent_active

        set_agent_active(False)

    def setUp(self) -> None:
        self.calls.clear()

    def _ids(self, **kwargs) -> list:
        return sorted(e.entity_id for e in self.ha._filtered(self.index, **kwargs))

    # ── resolution ───────────────────────────────────────────────────────

    def test_plural_and_area_tokens_match(self) -> None:
        """'kitchen lights' has to reach a light named 'Ceiling' in area Kitchen."""
        self.assertEqual(
            self._ids(query="kitchen lights", area="", domain="light"),
            ["light.kitchen_ceiling", "light.kitchen_counter"],
        )

    def test_area_filter_without_query(self) -> None:
        self.assertEqual(
            self._ids(query="", area="kitchen", domain=""),
            ["binary_sensor.kitchen_motion", "light.kitchen_ceiling",
             "light.kitchen_counter", "sensor.kitchen_temp"],
        )

    def test_unknown_target_matches_nothing(self) -> None:
        self.assertEqual(self._ids(query="spaceship", area="", domain=""), [])

    # ── service mapping ──────────────────────────────────────────────────

    def test_domain_specific_verbs(self) -> None:
        for domain, action, service in [
            ("light", "on", "turn_on"),
            ("cover", "off", "close_cover"),
            ("cover", "open", "open_cover"),
            ("lock", "unlock", "unlock"),
            ("alarm_control_panel", "disarm", "alarm_disarm"),
            ("button", "on", "press"),
            ("scene", "on", "turn_on"),
            ("light", "open", ""),
        ]:
            with self.subTest(domain=domain, action=action):
                self.assertEqual(self.ha._service_for(domain, action), service)

    def test_setting_a_value_uses_its_own_service(self) -> None:
        self.assertEqual(
            self.ha._resolve_service("cover", "on", {"position": 50}), "set_cover_position"
        )
        self.assertEqual(
            self.ha._resolve_service("climate", "on", {"temperature": 21.0}), "set_temperature"
        )
        # Brightness is the exception — it rides along on turn_on.
        self.assertEqual(
            self.ha._resolve_service("light", "on", {"brightness_pct": 30}), "turn_on"
        )

    # ── control ──────────────────────────────────────────────────────────

    def test_dimming_sends_brightness(self) -> None:
        self.ha.control_home_device(target="bedroom lamp", brightness_percent=30)
        self.assertEqual(
            self.calls, [("light", "turn_on", ["light.bedroom_lamp"], {"brightness_pct": 30})]
        )

    def test_sensors_are_never_controlled(self) -> None:
        self.ha.control_home_device(target="kitchen motion", action="on")
        self.assertEqual(self.calls, [])

    def test_vague_command_is_refused(self) -> None:
        result = self.ha.control_home_device()
        self.assertEqual(self.calls, [])
        self.assertIn("which device", result)

    # ── safety gate ──────────────────────────────────────────────────────

    def test_locks_refused_by_default(self) -> None:
        for target in ("front door", "garage"):
            with self.subTest(target=target):
                self.calls.clear()
                result = self.ha.control_home_device(target=target, action="open")
                self.assertEqual(self.calls, [])
                self.assertIn("allow_locks", result)

    def test_incidental_lock_is_skipped_not_fatal(self) -> None:
        """A lock in the room must not veto the rest of the command."""
        self.ha.control_home_device(area="hallway", action="off")
        self.assertEqual(
            self.calls, [("climate", "turn_off", ["climate.thermostat"], {})]
        )

    def test_locks_work_once_allowed(self) -> None:
        original = self.ha._locks_allowed
        self.ha._locks_allowed = lambda: True
        try:
            self.ha.control_home_device(target="front door", action="unlock")
        finally:
            self.ha._locks_allowed = original
        self.assertEqual(self.calls, [("lock", "unlock", ["lock.front_door"], {})])

    def test_mass_change_is_capped(self) -> None:
        many = [
            self.ha._Entity(f"light.bulb_{i}", f"Bulb {i}", "Hall", "off", "")
            for i in range(self.ha._MAX_CONTROL_TARGETS + 1)
        ]
        original = self.index
        type(self).index = many
        try:
            result = self.ha.control_home_device(area="hall", action="off")
        finally:
            type(self).index = original
        self.assertEqual(self.calls, [])
        self.assertIn("too many", result)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
