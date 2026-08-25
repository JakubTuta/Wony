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

# ModulesSettings allows extra keys, so per-module settings a module defines for
# itself are legitimately absent from the schema.
_EXTRA_ALLOWED_PREFIX = "modules."

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


def _dead_keys(node: dict, model: type, prefix: str = "") -> list:
    """YAML key paths that `model` would silently drop (pydantic extra='ignore').

    Recurses into nested models. A model declaring extra='allow' (ModulesSettings,
    so a module can carry settings it defines for itself) ends the walk.
    """
    from pydantic import BaseModel

    if model.model_config.get("extra") == "allow":
        return []

    dead = []
    for key, value in node.items():
        field = model.model_fields.get(key)
        if field is None:
            dead.append(f"{prefix}{key}")
            continue
        annotation = field.annotation
        if (
            isinstance(value, dict)
            and isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
        ):
            dead += _dead_keys(value, annotation, f"{prefix}{key}.")
    return dead


class TestConfigKeys(unittest.TestCase):
    def test_every_key_resolves(self) -> None:
        from helpers.config import Config

        Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))

        unresolved = []
        for key, where in sorted(_all_keys().items()):
            if key.startswith(_EXTRA_ALLOWED_PREFIX):
                continue
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

    def _assert_no_dead_keys(self, filename: str) -> None:
        import yaml

        from helpers.config import AppSettings

        with open(os.path.join(_REPO_ROOT, filename), encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        dead = _dead_keys(raw, AppSettings)
        self.assertFalse(
            dead,
            f"{filename} sets keys the schema ignores — they look like working "
            f"settings but do nothing:\n  " + "\n  ".join(dead),
        )


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
