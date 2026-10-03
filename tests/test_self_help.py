"""Wony answers questions about itself from its live settings, the registry and
the README. None of that may leak a key, and none of it may be kept as a second
copy in code, where it would drift from what the screen and the guide say.

Run directly: python tests/test_self_help.py
"""
import glob
import importlib
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from helpers import guide, lookup, settings  # noqa: E402
from helpers.config import Config  # noqa: E402


def _load_every_module() -> None:
    """The app imports every module at startup, so only then is every feature
    and its requirement in the registry."""
    for path in glob.glob(os.path.join(_REPO_ROOT, "modules", "*.py")):
        name = os.path.splitext(os.path.basename(path))[0]
        if name != "__init__":
            importlib.import_module(f"modules.{name}")


def _every_field() -> list:
    return [(title, field) for title, fields in settings._FIELDS for field in fields]


class TestLookup(unittest.TestCase):
    def setUp(self) -> None:
        Config.load()

    def test_keywords_drop_short_words_filler_and_repeats(self) -> None:
        self.assertEqual(lookup.keywords("How do I set up my Gmail, gmail?"), ["set", "gmail"])
        self.assertEqual(lookup.keywords("what is the weather"), ["weather"])
        self.assertEqual(lookup.keywords(""), [])
        self.assertEqual(lookup.keywords(None), [])

    def test_a_huge_query_is_cut_down(self) -> None:
        """The job takes any argument from the web API; matching cost grows with
        the number of words."""
        words = lookup.keywords(" ".join(f"word{n}" for n in range(100000)))
        self.assertEqual(len(words), lookup._MAX_KEYWORDS)
        self.assertEqual(words[0], "word0")

    def test_the_assistants_own_name_is_not_a_keyword(self) -> None:
        with mock.patch.object(Config, "get", return_value="Jarvis"):
            self.assertEqual(lookup.keywords("install Jarvis"), ["install"])

    def test_a_word_matches_the_start_of_a_word_not_the_middle(self) -> None:
        self.assertTrue(lookup.has("install", "installing and installed"))
        self.assertFalse(lookup.has("set", "reset the offset"))
        self.assertTrue(lookup.has("idle", "kiosk.idle_minutes"))


class TestExplain(unittest.TestCase):
    def setUp(self) -> None:
        Config.load()

    def test_a_setting_comes_with_its_value_limits_and_place(self) -> None:
        text = settings.explain(lookup.keywords("go to the clock after"))
        self.assertIn("Go to the clock after", text)
        self.assertIn(f"now {Config.get('kiosk.idle_minutes')}", text)
        self.assertIn("1 to 240", text)
        self.assertIn("Settings → This device", text)

    def test_every_setting_can_be_found_by_its_own_label(self) -> None:
        """A setting the lookup cannot find is one the assistant will make up an
        answer for, and nothing fails when that happens."""
        for _, field in _every_field():
            with self.subTest(key=field.key):
                self.assertIn(field.label, settings.explain(lookup.keywords(field.label)))

    def test_a_feature_says_whether_it_works(self) -> None:
        text = settings.explain(lookup.keywords("spotify"))
        self.assertIn("Spotify: Play, pause, skip", text)
        self.assertRegex(text, r"It is (on|off|switched on)")

    def test_nothing_matching_is_empty(self) -> None:
        self.assertEqual(settings.explain(lookup.keywords("zzzqqq")), "")
        self.assertEqual(settings.explain([]), "")

    def test_a_broad_word_is_capped_and_says_so(self) -> None:
        with mock.patch.object(settings, "_MAX_EXPLAINED", 3):
            text = settings.explain(["modules"])  # in the key of seven settings, the label of none
        self.assertEqual(text.count("Under Settings →"), 3)
        self.assertRegex(text, r"\d+ more match")

    def test_a_word_in_a_label_beats_the_same_word_in_a_key(self) -> None:
        text = settings.explain(["calendar"])
        self.assertIn("- Change my calendar: now", text)
        self.assertNotIn("Working day starts", text)

    def test_a_common_word_does_not_drown_the_subject(self) -> None:
        """"set up weather" is about the weather; "set" is in half the help text."""
        text = settings.explain(lookup.keywords("how do I set up weather"))
        self.assertIn("- Weather: Now and the next few days", text)
        self.assertNotIn("Change my mailbox", text)
        self.assertNotIn("Spotify", text)

    def test_it_says_it_cannot_change_anything(self) -> None:
        text = settings.explain(["calendar"])
        self.assertIn("I cannot change either myself", text)
        self.assertIn("Settings screen", text)


class TestNoKeyLeaks(unittest.TestCase):
    def setUp(self) -> None:
        Config.load()
        _load_every_module()

    def _everything_it_can_say(self) -> list:
        said = [settings.overview(), guide.answer(""), guide.answer("api key")]
        for _, field in _every_field():
            said.append(settings.explain(lookup.keywords(field.label)))
            said.append(settings.explain(lookup.keywords(field.key.replace(".", " "))))
        for key, label, _ in settings.MODULES:
            said.append(guide.answer(f"{key} {label}"))
        return said

    def test_no_key_value_reaches_the_assistant(self) -> None:
        """Keys live in .env, so the settings never hold one — but a feature's state
        names the variable it is waiting for, and that must stay a name."""
        from helpers.registry import ServiceRegistry

        names = {"ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
        for requirement in ServiceRegistry.get_module_requirements().values():
            names |= set(requirement.env_vars)
        self.assertIn("SPOTIFY_CLIENT_SECRET", names)
        secrets = {name: f"SECRET-{name}-VALUE" for name in names}

        with mock.patch.dict(os.environ, secrets):
            said = "\n".join(self._everything_it_can_say())
        for name, value in secrets.items():
            with self.subTest(name=name):
                self.assertNotIn(value, said)

    def test_a_private_value_is_only_ever_set_or_not(self) -> None:
        assistant = Config._settings.assistant
        self.addCleanup(setattr, assistant, "home_address", assistant.home_address)
        assistant.home_address = "12 Hidden Lane"

        said = "\n".join(self._everything_it_can_say() + [settings.explain(["home", "address"])])
        self.assertNotIn("Hidden Lane", said)
        self.assertIn("Home address: now set", said)

    def test_the_screen_still_shows_a_private_value(self) -> None:
        """Private is about what the assistant is told. The screen is the user's own."""
        assistant = Config._settings.assistant
        self.addCleanup(setattr, assistant, "home_address", assistant.home_address)
        assistant.home_address = "12 Hidden Lane"
        shown = {
            field["key"]: field["value"]
            for section in settings.describe()["sections"]
            for field in section["fields"]
        }
        self.assertEqual(shown["assistant.home_address"], "12 Hidden Lane")


class TestFeatureState(unittest.TestCase):
    """What a feature is waiting for, said from the registry — never a list kept here."""

    def _state(self, enabled: set, status: dict, requirements: dict, hints: dict = None) -> str:
        from helpers.registry import ServiceRegistry

        with mock.patch.object(ServiceRegistry, "get_module_status", return_value=status), \
                mock.patch.object(ServiceRegistry, "get_module_hints", return_value=hints or {}), \
                mock.patch.object(ServiceRegistry, "get_module_requirements", return_value=requirements):
            return settings._feature_state("demo", enabled)

    def test_working(self) -> None:
        self.assertEqual(self._state({"demo"}, {"demo": ("enabled", "")}, {}), "on and working.")

    def test_on_but_broken_gives_the_reason_and_the_fix(self) -> None:
        text = self._state(
            {"demo"}, {"demo": ("misconfigured", "missing env: DEMO_KEY")}, {}, {"demo": "Add the key."}
        )
        self.assertIn("missing env: DEMO_KEY", text)
        self.assertIn("Add the key.", text)

    def test_switched_on_but_not_started_yet_says_to_restart(self) -> None:
        self.assertIn("restarts", self._state({"demo"}, {"demo": ("disabled", "not in enabled_modules")}, {}))

    def test_off_and_missing_something_says_what_and_how(self) -> None:
        from helpers.requirements import Requirement

        needs = Requirement(env_vars=["WONY_TEST_NO_SUCH_VAR"], setup_hint="Run setup again.")
        text = self._state(set(), {}, {"demo": needs})
        self.assertIn("missing env: WONY_TEST_NO_SUCH_VAR", text)
        self.assertIn("Run setup again.", text)

    def test_off_and_ready_says_nothing_else_is_needed(self) -> None:
        from helpers.requirements import Requirement

        self.assertIn("already here", self._state(set(), {}, {"demo": Requirement()}))


class TestWhere(unittest.TestCase):
    def test_names_the_label_and_the_section(self) -> None:
        self.assertEqual(
            settings.where("modules.gmail.allow_write"),
            "'Change my mailbox' under Settings → What Wony may do on its own",
        )

    def test_an_unknown_key_is_refused(self) -> None:
        with self.assertRaises(settings.SettingsError):
            settings.where("modules.nothing.here")

    def test_every_key_the_modules_point_at_exists(self) -> None:
        """A typo in one of these only shows when that switch is off and someone
        trips over it — the one moment the message has to be right."""
        keys = set()
        for path in glob.glob(os.path.join(_REPO_ROOT, "modules", "*.py")):
            with open(path, encoding="utf-8-sig") as handle:
                keys |= set(re.findall(r"where\('([\w.]+)'\)", handle.read()))
        self.assertGreaterEqual(len(keys), 5)
        for key in keys:
            with self.subTest(key=key):
                settings.where(key)

    def test_a_switch_that_is_off_points_at_the_screen_not_the_file(self) -> None:
        from modules import basics, home_assistant
        from modules.calendar import Calendar
        from modules.gmail import Gmail

        Config.load()
        with mock.patch.object(basics, "logger"), mock.patch.object(basics.Config, "get", return_value=False):
            messages = [
                basics._run_power_command("power off", "poweroff"),
                Gmail._write_disabled_note(None, "Sending email"),
                Calendar._write_disabled_note(None),
                home_assistant._requirement().setup_hint,
            ]
        for message in messages:
            with self.subTest(message=message):
                self.assertIn("under Settings →", message)
                self.assertNotIn("config.yaml", message)
                self.assertNotIn("allow_", message)


class TestGuide(unittest.TestCase):
    def setUp(self) -> None:
        Config.load()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "README.md")
        patcher = mock.patch.object(guide, "_GUIDE_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, text: str) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_a_heading_beats_a_passing_mention(self) -> None:
        self._write(
            "## Install\nRun the installer.\n\n## Troubleshooting\nIf it fails, install it again.\n"
        )
        with mock.patch.object(guide, "_MAX_CHUNKS", 1):
            text = guide.search(["install"])
        self.assertIn("Run the installer.", text)
        self.assertNotIn("install it again", text)

    def test_a_rare_word_says_more_than_a_common_one(self) -> None:
        """"set" is all over the guide; the thing being set up is the subject."""
        self._write(
            "".join(f"## Topic {n}\nset it, set that, set the other\n\n" for n in range(6))
            + "## Weather\nNeeds a free key.\n"
        )
        with mock.patch.object(guide, "_MAX_CHUNKS", 1):
            self.assertIn("Needs a free key.", guide.search(["set", "weather"]))

    def test_only_the_best_pieces_come_back(self) -> None:
        self._write("".join(f"## Topic {n}\nwidgets, and more widgets\n\n" for n in range(20)))
        self.assertEqual(guide.search(["widgets"]).count("widgets"), 2 * guide._MAX_CHUNKS)

    def test_a_weak_match_is_left_out(self) -> None:
        self._write("## Widgets\nAbout widgets, widgets and widgets.\n\n## Other\nMentions widgets once.\n")
        text = guide.search(["widgets"])
        self.assertIn("About widgets", text)
        self.assertNotIn("Mentions widgets once", text)

    def test_a_table_is_answered_one_row_at_a_time_with_its_header(self) -> None:
        self._write(
            "## Features\n| Feature | Needs |\n| --- | --- |\n| Alpha | a red key |\n| Beta | a blue key |\n"
        )
        text = guide.search(["alpha"])
        self.assertIn("| Feature | Needs |", text)
        self.assertIn("a red key", text)
        self.assertNotIn("a blue key", text)

    def test_a_table_row_is_about_its_first_cell(self) -> None:
        self._write(
            "## Chat\nThe weather tile shows today's weather.\n\n"
            "## Features\n| Feature | Needs |\n| --- | --- |\n| Weather | a free key |\n| Maps | nothing |\n"
        )
        text = guide.search(["weather"])
        self.assertIn("a free key", text)
        self.assertNotIn("tile", text)

    def test_a_code_block_is_one_piece_and_its_comments_are_not_headings(self) -> None:
        """A YAML "# comment" read as a heading filed everything after it under
        the wrong name — and a blank line inside the block cut it in two."""
        self._write(
            "## Install\nRun:\n\n```yaml\n# Only what is listed here\nkey: 1\n\nother: 2\n```\n\nAfter.\n"
        )
        self.assertEqual(guide.headings(), "User guide sections: Install")
        text = guide.search(["listed"])
        self.assertIn("key: 1\n\nother: 2", text)
        self.assertNotIn("Run:", text)

    def test_what_comes_back_is_in_reading_order_under_its_heading(self) -> None:
        self._write("## One\nwidgets here\n\n## Two\nwidgets there\n\nmore widgets there\n")
        text = guide.search(["widgets"])
        self.assertLess(text.index("## One"), text.index("## Two"))
        self.assertEqual(text.count("## Two"), 1)

    def test_one_long_paragraph_is_cut_on_a_line(self) -> None:
        self._write("## Big\n" + "".join(f"line {n} of a long paragraph about big things\n" for n in range(200)))
        text = guide.search(["big"])
        self.assertLessEqual(len(text), guide._MAX_CHUNK_CHARS + 100)
        self.assertTrue(text.rstrip().endswith("…"))
        self.assertTrue(text.rstrip("…\n").endswith("big things"))  # cut between lines, not inside one

    def test_a_lookup_never_adds_more_than_the_budget(self) -> None:
        self._write("".join(f"## T{n}\n{'widgets ' * 100}\n\n" for n in range(20)))
        self.assertLess(len(guide.search(["widgets"])), guide._MAX_GUIDE_CHARS + 300)

    def test_no_match_is_empty(self) -> None:
        self._write("## Install\nSteps.\n")
        self.assertEqual(guide.search(["zzzqqq"]), "")

    def test_a_missing_guide_still_answers_from_the_settings(self) -> None:
        self.assertEqual(guide.search(["install"]), "")
        self.assertEqual(guide.headings(), "")
        self.assertIn("Go to the clock after", guide.answer("go to the clock after"))

    def test_nothing_found_says_so_and_offers_what_can_be_asked(self) -> None:
        self._write("## Install\nSteps.\n")
        text = guide.answer("zzzqqq")
        self.assertIn("Nothing about 'zzzqqq'", text)
        self.assertIn("What I can look up:", text)
        self.assertIn("Install", text)

    def test_an_empty_question_lists_what_can_be_asked(self) -> None:
        self._write("## Install\nSteps.\n")
        text = guide.answer("")
        self.assertNotIn("Nothing about", text)
        self.assertIn("Settings, by section", text)

    def test_a_question_of_only_short_words_still_offers_what_can_be_asked(self) -> None:
        self._write("## Install\nSteps.\n")
        self.assertIn("What I can look up:", guide.answer("tv"))


class TestTheRealGuide(unittest.TestCase):
    """The README is the source. These fail when it stops answering what a new
    user asks first."""

    def setUp(self) -> None:
        Config.load()

    def test_installing_names_the_setup_script_and_how_to_start(self) -> None:
        self.assertIn("python setup.py", guide.search(lookup.keywords("install")))
        self.assertIn("python wony.py", guide.search(lookup.keywords("start")))

    def test_adding_a_feature_later_is_covered(self) -> None:
        self.assertIn("python setup.py configure", guide.search(lookup.keywords("configure keys")))

    def test_a_feature_comes_with_what_to_bring(self) -> None:
        for question, answer in (
            ("how do I set up weather", "openweathermap"),
            ("how do I set up spotify", "developer.spotify.com"),
            ("how do I set up home assistant", "Long-lived access tokens"),
            ("how do I set up gmail", "OAuth"),
        ):
            with self.subTest(question=question):
                self.assertIn(answer, guide.search(lookup.keywords(question)))

    def test_the_config_quoted_in_the_readme_adds_no_headings(self) -> None:
        """The README quotes config.yaml, comments and all; one of those comments
        used to be read as a heading."""
        self.assertNotIn("Only what is listed here", guide.headings())

    def test_a_problem_points_at_the_doctor(self) -> None:
        self.assertIn("python wony.py doctor", guide.search(lookup.keywords("something goes wrong")))

    def test_a_setting_question_does_not_drag_in_the_whole_guide(self) -> None:
        self.assertLess(len(guide.search(lookup.keywords("idle clock"))), 2500)


class TestTheJob(unittest.TestCase):
    def setUp(self) -> None:
        Config.load()

    def test_about_looks_the_question_up(self) -> None:
        from modules.status import system_status

        text = system_status(scope="about", query="go to the clock after")
        self.assertIn("Go to the clock after", text)
        self.assertIn("Settings → This device", text)

    def test_about_with_no_query_lists_what_can_be_asked(self) -> None:
        from modules.status import system_status

        self.assertIn("What I can look up:", system_status(scope="about"))

    def test_an_unknown_scope_names_the_real_ones(self) -> None:
        from modules.status import system_status

        self.assertIn("about", system_status(scope="nonsense"))

    def test_the_commands_list_still_answers(self) -> None:
        from modules.status import system_status

        self.assertIn("Available commands", system_status(scope="commands"))


class TestThePrompt(unittest.TestCase):
    def test_it_tells_the_model_where_to_look_and_names_no_file_to_edit(self) -> None:
        from modules.ai import build_agent_system_prompt

        Config.load()
        stable, _ = build_agent_system_prompt()
        self.assertIn("scope='about'", stable)
        self.assertNotIn("config.yaml", stable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
