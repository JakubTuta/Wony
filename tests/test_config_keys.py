"""Every Config.get("a.b.c") key must resolve against the settings schema.

A key that does not resolve silently returns the caller's default forever, so
the setting looks supported, is documented nowhere, and cannot be changed. Four
of these had accumulated before this test existed — including
`calendar.work_end_hour`, which should have been `modules.calendar.*` and quietly
ignored the user's configured working hours.

Run directly: python tests/test_config_keys.py
"""
import glob
import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

_KEY_CALL = re.compile(r"""Config\.get\(\s*["']([A-Za-z0-9_.]+)["']""")
_SEARCH_DIRS = ("helpers", "modules", ".")

_MISSING = object()


def _all_keys() -> dict:
    keys: dict = {}
    for directory in _SEARCH_DIRS:
        for path in glob.glob(os.path.join(_REPO_ROOT, directory, "*.py")):
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            for match in _KEY_CALL.finditer(source):
                lineno = source[: match.start()].count("\n") + 1
                rel = os.path.relpath(path, _REPO_ROOT)
                keys.setdefault(match.group(1), f"{rel}:{lineno}")
    return keys


def _leaves(node: dict, prefix: tuple = ()):
    for key, value in node.items():
        if isinstance(value, dict):
            yield from _leaves(value, prefix + (key,))
        else:
            yield prefix + (key,), value


class TestConfigKeys(unittest.TestCase):
    def test_every_key_resolves(self) -> None:
        from helpers.config import Config

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))

        unresolved = []
        for key, where in sorted(_all_keys().items()):
            if Config.get(key, _MISSING) is _MISSING:
                unresolved.append(f"  {key}  ({where})")

        self.assertFalse(
            unresolved,
            "Config keys that do not exist in the schema — these silently fall "
            "back to their default and can never be set:\n" + "\n".join(unresolved),
        )

    def test_example_config_matches_schema(self) -> None:
        """config.example.yaml must not document keys the schema drops."""
        self._assert_no_dead_keys("config.example.yaml")

    def test_live_config_matches_schema(self) -> None:
        """The developer's own config.yaml drifts too. pydantic's extra='ignore'
        makes a stale key look like a working setting forever — `voice.ducking`
        survived a whole rewrite of that feature this way."""
        if not os.path.exists(os.path.join(_REPO_ROOT, "config.yaml")):
            self.skipTest("no config.yaml in this checkout")
        self._assert_no_dead_keys("config.yaml")

    def test_example_values_are_the_schema_defaults(self) -> None:
        """Deleting a line from config.yaml must not change behaviour. When
        barge_in defaulted to off in the schema but on in the example, a user
        who removed the line silently lost interruptions."""
        import yaml

        from helpers.config import AppSettings

        with open(os.path.join(_REPO_ROOT, "config.example.yaml"), encoding="utf-8") as fh:
            example = yaml.safe_load(fh) or {}
        AppSettings._yaml_file = None
        try:
            defaults = AppSettings().model_dump()
        finally:
            from helpers.config import Config

            Config.load()

        drift = []
        for path, value in _leaves(example):
            node = defaults
            for part in path:
                node = node[part]
            if node != value:
                drift.append(f"  {'.'.join(path)}: example={value!r} schema={node!r}")
        self.assertFalse(drift, "config.example.yaml disagrees with the schema:\n" + "\n".join(drift))

    def _assert_no_dead_keys(self, filename: str) -> None:
        import yaml

        from helpers.config import dead_keys

        with open(os.path.join(_REPO_ROOT, filename), encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        dead = dead_keys(raw)
        self.assertFalse(
            dead,
            f"{filename} sets keys the schema ignores — they look like working "
            f"settings but do nothing:\n  " + "\n  ".join(dead),
        )


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
