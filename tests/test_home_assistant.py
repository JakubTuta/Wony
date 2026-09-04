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
        E("light.zarowka", "Żarówka", "Salon", "off", ""),
        # A robot vacuum and the entities that come with it: the shape every
        # third-party integration ships, and none of it is turn_on/turn_off.
        E("vacuum.robot", "Robot", "Utility", "docked", "", "", "", "Robot"),
        E("select.robot_suction", "Robot Suction", "Utility", "Turbo", "",
          "", ha._OPTION_SEP.join(["Quiet", "Standard", "Turbo", "Max"]), "Robot"),
        E("number.robot_volume", "Robot Volume", "Utility", "4", "", "", "", "Robot"),
        E("sensor.robot_battery", "Robot Battery", "Utility", "79", "battery",
          "", "", "Robot"),
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
        # Stands in for Home Assistant's service registry, which is only read
        # for verbs the tables do not name.
        ha._known_services = lambda: {"vacuum.clean_spot", "select.select_next"}

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

    def test_separators_survive_splitlines(self) -> None:
        """str.splitlines() breaks on \\x1c-\\x1e too, which would cut a row in
        half and leave every option list holding only its first entry."""
        for sep in (self.ha._SEP, self.ha._OPTION_SEP):
            with self.subTest(sep=repr(sep)):
                self.assertEqual(f"a{sep}b".splitlines(), [f"a{sep}b"])

    def test_accented_names_match_unaccented_speech(self) -> None:
        """Home Assistant names are written properly; nobody dictates them that way."""
        self.assertEqual(self._ids(query="zarowka", area="", domain=""), ["light.zarowka"])

    def test_unknown_target_matches_nothing(self) -> None:
        self.assertEqual(self._ids(query="spaceship", area="", domain=""), [])

    # ── service mapping ──────────────────────────────────────────────────

    def test_domain_specific_verbs(self) -> None:
        for entity_id, state, action, service in [
            ("light.x", "off", "on", "turn_on"),
            ("cover.x", "open", "off", "close_cover"),
            ("cover.x", "closed", "open", "open_cover"),
            ("lock.x", "locked", "unlock", "unlock"),
            ("alarm_control_panel.x", "armed_away", "disarm", "alarm_disarm"),
            ("button.x", "unknown", "on", "press"),
            ("scene.x", "unknown", "on", "turn_on"),
            ("light.x", "off", "open", ""),
            # The regression this file exists for: Home Assistant has no
            # vacuum.turn_on, so 'on' has to mean start and 'off' go home.
            ("vacuum.x", "docked", "on", "start"),
            ("vacuum.x", "cleaning", "off", "return_to_base"),
            ("vacuum.x", "cleaning", "pause", "pause"),
            ("lawn_mower.x", "docked", "on", "start_mowing"),
            # Set-only entities have nothing to switch.
            ("select.x", "Turbo", "on", ""),
        ]:
            with self.subTest(entity_id=entity_id, action=action):
                entity = self.ha._Entity(entity_id, "X", "", state, "")
                self.assertEqual(self.ha._service_for(entity, action), service)

    def test_toggle_falls_back_to_state(self) -> None:
        """A vacuum has no toggle service, but the panel's switch still works."""
        docked = self.ha._Entity("vacuum.a", "A", "", "docked", "")
        cleaning = self.ha._Entity("vacuum.a", "A", "", "cleaning", "")
        self.assertEqual(self.ha._service_for(docked, "toggle"), "start")
        self.assertEqual(self.ha._service_for(cleaning, "toggle"), "return_to_base")

    def test_unknown_verb_falls_through_to_home_assistant(self) -> None:
        """Integration-specific services stay reachable without a code change."""
        entity = self.ha._Entity("vacuum.a", "A", "", "docked", "")
        self.assertEqual(self.ha._service_for(entity, "clean_spot"), "clean_spot")
        self.assertEqual(self.ha._service_for(entity, "not_a_service"), "")
        # Never a path segment of someone else's choosing.
        self.assertEqual(self.ha._service_for(entity, "../../states"), "")

    def test_setting_a_value_uses_its_own_service(self) -> None:
        Change = self.ha._Change
        for entity_id, change, service, data in [
            ("cover.x", Change(value=50), "set_cover_position", {"position": 50.0}),
            ("climate.x", Change(temperature=21.0), "set_temperature", {"temperature": 21.0}),
            # A bare number at a thermostat is degrees, and must not be
            # clamped to a percentage on the way through.
            ("climate.x", Change(value=210), "set_temperature", {"temperature": 210.0}),
            # Brightness is the exception — it rides along on turn_on.
            ("light.x", Change(value=30), "turn_on", {"brightness_pct": 30.0}),
            ("fan.x", Change(value=40), "set_percentage", {"percentage": 40.0}),
            ("number.x", Change(value=7), "set_value", {"value": 7.0}),
            ("media_player.x", Change(value=30), "volume_set", {"volume_level": 0.3}),
            ("vacuum.x", Change(option="Max"), "set_fan_speed", {"fan_speed": "Max"}),
        ]:
            with self.subTest(entity_id=entity_id):
                entity = self.ha._Entity(entity_id, "X", "", "on", "")
                self.assertEqual(self.ha._plan(entity, "on", change), (service, data))

    # ── control ──────────────────────────────────────────────────────────

    def test_dimming_sends_brightness(self) -> None:
        self.ha.control_home_device(target="bedroom lamp", value=30)
        self.assertEqual(
            self.calls, [("light", "turn_on", ["light.bedroom_lamp"], {"brightness_pct": 30.0})]
        )

    def test_vacuum_starts_and_docks(self) -> None:
        self.ha.control_home_device(target="robot", action="on")
        self.ha.control_home_device(target="robot", action="dock")
        self.assertEqual(
            self.calls,
            [
                ("vacuum", "start", ["vacuum.robot"], {}),
                ("vacuum", "return_to_base", ["vacuum.robot"], {}),
            ],
        )

    def test_named_option_is_matched_case_insensitively(self) -> None:
        """Speech does not carry case, and Home Assistant matches exactly."""
        self.ha.control_home_device(target="robot suction", option="turbo")
        self.assertEqual(
            self.calls,
            [("select", "select_option", ["select.robot_suction"], {"option": "Turbo"})],
        )

    def test_number_entity_takes_a_plain_value(self) -> None:
        self.ha.control_home_device(target="robot volume", value=7)
        self.assertEqual(
            self.calls, [("number", "set_value", ["number.robot_volume"], {"value": 7.0})]
        )

    def test_a_bare_number_picks_the_likeliest_domain(self) -> None:
        """'Set the kitchen to 30' is the lights, not the thermostat."""
        self.ha.control_home_device(area="kitchen", value=30)
        self.assertEqual(
            self.calls,
            [
                (
                    "light",
                    "turn_on",
                    ["light.kitchen_ceiling", "light.kitchen_counter"],
                    {"brightness_pct": 30.0},
                )
            ],
        )

    def test_a_bare_number_still_reaches_a_blind(self) -> None:
        self.ha.control_home_device(target="blinds", value=40)
        self.assertEqual(
            self.calls,
            [("cover", "set_cover_position", ["cover.living_blinds"], {"position": 40.0})],
        )

    def test_refusal_says_what_the_device_takes(self) -> None:
        """The dead end that started this: 'unsupported' with no way forward."""
        result = self.ha.control_home_device(target="robot", action="fly")
        self.assertEqual(self.calls, [])
        self.assertIn("accepts start", result)

    def test_listing_shows_actions_and_options(self) -> None:
        listing = self.ha.list_home_devices(query="robot suction")
        self.assertIn("options Quiet, Standard, Turbo, Max", listing)

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

    def _bulbs(self, count: int) -> list:
        return [
            self.ha._Entity(f"light.bulb_{i}", f"Bulb {i}", "Hall", "off", "")
            for i in range(count)
        ]

    def _against(self, index: list, **kwargs) -> str:
        original = type(self).index
        type(self).index = index
        try:
            return self.ha.control_home_device(**kwargs)
        finally:
            type(self).index = original

    def test_a_vague_target_cannot_sweep_the_house(self) -> None:
        result = self._against(
            self._bulbs(self.ha._MAX_VAGUE_TARGETS + 1), target="bulb", action="off"
        )
        self.assertEqual(self.calls, [])
        self.assertIn("too many", result)

    def test_naming_a_room_or_a_type_allows_the_whole_lot(self) -> None:
        """'Turn all the lights off' is a normal thing to ask a house."""
        count = self.ha._MAX_VAGUE_TARGETS + 8
        for scope in ({"area": "hall"}, {"domain": "light"}):
            with self.subTest(scope=scope):
                self.calls.clear()
                self._against(self._bulbs(count), action="off", **scope)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(len(self.calls[0][2]), count)

    def test_even_a_named_scope_has_a_ceiling(self) -> None:
        result = self._against(
            self._bulbs(self.ha._MAX_SCOPED_TARGETS + 1), domain="light", action="off"
        )
        self.assertEqual(self.calls, [])
        self.assertIn("too many", result)

    # ── listing ──────────────────────────────────────────────────────────

    def test_hidden_entities_never_reach_the_index(self) -> None:
        """Hiding an entity in Home Assistant means 'do not show me this'."""
        def row(entity_id: str, hidden: bool) -> str:
            return self.ha._SEP.join(
                [entity_id, "A", "Hall", "off", "", "", "", "Lamp", str(hidden)]
            )

        parsed = self.ha._parse_index("\n".join([row("light.a", False), row("light.b", True)]))
        self.assertEqual([e.entity_id for e in parsed], ["light.a"])
        self.assertEqual(parsed[0].device, "Lamp")

    def test_a_whole_house_listing_is_one_line_per_device(self) -> None:
        """Four entities of one vacuum must not read as four devices."""
        listing = self.ha.list_home_devices()
        self.assertIn("Robot (Utility): docked", listing)
        self.assertNotIn("Robot Suction", listing)
        self.assertNotIn("Robot Battery", listing)

    def test_naming_a_device_shows_what_is_under_it(self) -> None:
        listing = self.ha.list_home_devices(query="robot")
        self.assertIn("Robot (Utility): docked", listing)
        # Named under their device, so the device's own name is not repeated.
        self.assertIn("  Suction: Turbo [options Quiet, Standard, Turbo, Max]", listing)
        self.assertIn("Battery: 79", listing)

    # ── panel ────────────────────────────────────────────────────────────

    def _cards(self) -> dict:
        panel = self.ha.snapshot()
        return {d["name"]: d for area in panel["areas"] for d in area["devices"]}

    def test_the_panel_is_one_card_per_device(self) -> None:
        """A vacuum is a vacuum with a suction setting, not four switches."""
        robot = self._cards()["Robot"]
        self.assertEqual(robot["primary"]["entity_id"], "vacuum.robot")
        self.assertTrue(robot["primary"]["toggle"])
        self.assertEqual([e["name"] for e in robot["extras"]], ["Suction", "Volume"])
        self.assertEqual(robot["extras"][0]["options"][0], "Quiet")
        self.assertTrue(robot["extras"][1]["number"])

    def test_the_panel_leaves_out_what_cannot_be_controlled(self) -> None:
        ids = {
            control["entity_id"]
            for card in self._cards().values()
            for control in [card["primary"], *card["extras"]]
        }
        self.assertNotIn("sensor.robot_battery", ids)
        self.assertNotIn("binary_sensor.kitchen_motion", ids)

    def test_a_scene_is_a_button_not_a_switch(self) -> None:
        """Nothing turns a scene off again, so a switch would be a lie."""
        scene = self._cards()["Movie Night"]["primary"]
        self.assertTrue(scene["press"])
        self.assertFalse(scene["toggle"])

    def test_naming_a_sensor_does_not_drag_in_its_siblings(self) -> None:
        listing = self.ha.list_home_devices(query="robot battery")
        self.assertIn("79", listing)
        self.assertNotIn("Suction", listing)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
