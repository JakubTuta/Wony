"""Only the tools a turn needs go to the model, and nothing it needs is lost.

Run directly: python tests/test_toolset.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _job(name: str, doc: str):
    def job(query: str = "") -> str:
        return f"{name} ran"

    job.__name__ = name
    job.__doc__ = doc
    return job


def _registry():
    """A house with plenty of features: weather, music, mail, lights, plus filler."""
    jobs, modules = {}, {}
    for name, module, doc in [
        ("recall", "ai", "Searches past conversations."),
        ("routine", "routines", "Runs one of the user's named routines."),
        ("web_search", "web", "Searches the web."),
        ("weather", "weather", "Current weather and the forecast for a city."),
        ("play_songs", "spotify", "Plays music: a song, an artist or a playlist."),
        ("find_emails", "gmail", "Finds and reads email in the inbox."),
        ("control_home_device", "home_assistant", "Turns lights and switches on or off."),
    ]:
        jobs[name], modules[name] = _job(name, doc), module
    for i in range(30):
        name = f"filler_{i}"
        jobs[name], modules[name] = _job(name, "Does something unrelated with spreadsheets."), f"filler{i}"
    return jobs, modules


class TestPick(unittest.TestCase):
    def setUp(self) -> None:
        from helpers.registry import ServiceRegistry

        jobs, modules = _registry()
        for patcher in (
            mock.patch.object(ServiceRegistry, "_jobs", jobs),
            mock.patch.object(ServiceRegistry, "_job_modules", modules),
            mock.patch("helpers.semantic.is_available", return_value=False),
            mock.patch("helpers.semantic.ready", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_request_gets_its_feature_and_the_always_sent_ones(self) -> None:
        from helpers import toolset

        picked = toolset.pick("what's the weather in Oslo")
        self.assertIn("weather", picked)
        self.assertIn("recall", picked)
        self.assertIn("web_search", picked)
        self.assertNotIn("play_songs", picked)
        self.assertLess(len(picked), 10)

    def test_a_follow_up_keeps_what_the_last_turns_used(self) -> None:
        from helpers import toolset

        picked = toolset.pick("yes", recent_jobs=["find_emails"])
        self.assertIn("find_emails", picked)

    def test_a_small_install_sends_everything(self) -> None:
        from helpers import toolset

        with mock.patch.object(toolset, "_SELECT_ABOVE", 1000):
            self.assertEqual(len(toolset.pick("weather")), 37)


class TestWidening(unittest.TestCase):
    def test_a_job_named_but_not_sent_still_runs(self) -> None:
        from helpers import agent

        lamp = _job("control_home_device", "Turns lights on.")
        steps = iter([
            ("", [{"id": "1", "name": "control_home_device", "args": {}}]),
            ("Done.", []),
        ])
        seen = []

        def step(**kwargs):
            seen.append({f.__name__ for f in kwargs["available_tools"]})
            return next(steps)

        with mock.patch("helpers.model.stream_agent_step", side_effect=step):
            result = agent.run_agent(
                client=None, user_input="lights off", available_jobs={},
                system_instructions="", on_text=lambda _c: None, isolated=True,
                more_jobs=lambda name, _r: {"control_home_device": lamp} if name == "control_home_device" else {},
            )
        self.assertEqual(result.calls[0]["result"], "control_home_device ran")
        self.assertIn("control_home_device", seen[1])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
