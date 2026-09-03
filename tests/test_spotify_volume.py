"""Spotify volume: the device it targets, and whether the change actually landed.

These all failed silently before — the job returned "Volume set to 70%" while
the write went to a device nobody was listening to, or to one that ignores
volume entirely. Nothing but a test notices that.

Run directly: python tests/test_spotify_volume.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _device(device_id="live-device", volume=50, name="Laptop", supports_volume=True):
    return {
        "id": device_id,
        "name": name,
        "volume_percent": volume,
        "supports_volume": supports_volume,
    }


class TestSpotifyVolume(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from helpers.decorators import set_agent_active

        # Same switch the agent loop uses: stops capture_response echoing every
        # job's return value into the test output.
        set_agent_active(True)

    @classmethod
    def tearDownClass(cls) -> None:
        from helpers.decorators import set_agent_active

        set_agent_active(False)

    def setUp(self) -> None:
        from modules.spotify import Spotify

        # __new__, not __init__: the constructor runs OAuth, and none of the
        # volume logic touches anything it sets up beyond device_id.
        self.spotify = Spotify.__new__(Spotify)
        self.spotify.device_id = None
        self.spotify._VOLUME_CONFIRM_DELAY = 0  # no real sleeping in tests
        self.writes: list = []
        self.device = _device()

        self.spotify._get_playback_state = lambda: {"device": dict(self.device)}

        def _write(method, url, **kwargs):
            self.writes.append((method, url))
            # Spotify applies the write; later state reads see the new level.
            if "volume_percent=" in url:
                value = url.split("volume_percent=")[1].split("&")[0]
                self.device["volume_percent"] = int(value)
            return None

        self.spotify._make_spotify_request = _write

    # ── the device the write goes to ────────────────────────────────────

    def test_relative_change_targets_the_live_device_not_the_cached_one(self):
        """The regression: device_id is cached for the session, so after playback
        moves to another device a read/write split sent the new level to the old
        device — a 204, and nothing gets louder."""
        self.spotify.device_id = "stale-device-from-an-hour-ago"

        self.spotify.set_volume(direction="up")

        self.assertEqual(len(self.writes), 1)
        _method, url = self.writes[0]
        self.assertIn("device_id=live-device", url)
        self.assertNotIn("stale-device", url)
        self.assertIn("volume_percent=60", url)
        self.assertEqual(self.spotify.device_id, "live-device")

    def test_absolute_level_also_pins_the_live_device(self):
        self.spotify.device_id = "stale-device-from-an-hour-ago"

        self.spotify.set_volume(level=25)

        _method, url = self.writes[0]
        self.assertIn("device_id=live-device", url)
        self.assertIn("volume_percent=25", url)

    def test_relative_change_reads_the_level_fresh_every_call(self):
        """Volume moved in the Spotify app between two 'louder's: the second one
        steps from what the app reports now, not from what we set last time."""
        self.spotify.set_volume(direction="up")
        self.device["volume_percent"] = 20  # user dragged the slider down

        result = self.spotify.set_volume(direction="up")

        self.assertIn("volume_percent=30", self.writes[-1][1])
        self.assertEqual(result, "Volume set to 30%.")

    # ── writes that do not land ─────────────────────────────────────────

    def test_device_that_ignores_volume_is_reported_not_claimed_as_done(self):
        self.device = _device(name="Kitchen speaker", supports_volume=False)

        result = self.spotify.set_volume(level=80)

        self.assertEqual(self.writes, [])
        self.assertIn("Kitchen speaker", result)
        self.assertIn("does not accept volume changes", result)

    def test_volume_that_does_not_move_is_an_error_not_a_success(self):
        self.spotify._make_spotify_request = lambda method, url, **kw: self.writes.append(
            (method, url)
        )  # Spotify accepts the write and ignores it

        result = self.spotify.set_volume(level=80)

        self.assertIn("would not change the volume", result)
        self.assertIn("still at 50%", result)

    def test_device_snapping_to_its_own_steps_reports_where_it_landed(self):
        def _write(method, url, **kwargs):
            self.writes.append((method, url))
            self.device["volume_percent"] = 75  # speaker rounds to steps of 5

        self.spotify._make_spotify_request = _write

        result = self.spotify.set_volume(level=77)

        self.assertEqual(result, "Volume set to 75%.")

    def test_nothing_playing_says_so(self):
        self.spotify._get_playback_state = lambda: None

        result = self.spotify.set_volume(level=40)

        self.assertEqual(self.writes, [])
        self.assertIn("Nothing is playing", result)

    # ── reporting the current volume ────────────────────────────────────

    def test_get_reports_the_live_volume_without_writing(self):
        self.device["volume_percent"] = 63

        result = self.spotify.set_volume(direction="get")

        self.assertEqual(self.writes, [])
        self.assertEqual(result, "Spotify volume is 63% on Laptop.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
