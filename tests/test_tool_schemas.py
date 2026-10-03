"""Every registered job must produce a tool schema the model can actually use.

The docstring `Args:` parser silently degraded once already: its lookahead could
not match across the `(str)` in `date (str):`, so the whole Args block collapsed
into the first parameter's description and every later parameter shipped as
"No description available". Nothing failed — the schemas were just quietly wrong
on every multi-parameter job.

Run directly: python tests/test_tool_schemas.py
"""
import inspect
import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

_NO_DESC = "No description available"

_DOCUMENTED_ARG = re.compile(r"^[ \t]*(\w+)[ \t]*\([^)]*\)[ \t]*:", re.MULTILINE)


def _load_jobs() -> dict:
    from helpers.config import Config

    Config.load(os.path.join(_REPO_ROOT, "config.example.yaml"))
    import modules  # noqa: F401  (import triggers discover_services)
    from helpers.registry import ServiceRegistry

    return ServiceRegistry.get_all_jobs()


class TestToolSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jobs = _load_jobs()

    def test_jobs_are_registered(self) -> None:
        # Deliberately low: CI installs core deps only, so most optional
        # modules gate themselves off. The point is that discovery ran at all.
        self.assertGreater(len(self.jobs), 5, "job registry looks empty")

    def test_every_job_is_wrapped_by_capture_response(self) -> None:
        """@register_job registers whatever callable sits directly beneath it.
        Written the other way round — @capture_response on the outside — the
        registry keeps the *raw* function, so that job silently loses error
        capture, logging and tool-outcome recording. League's three jobs shipped
        like that. `_quiet_success` is the marker capture_response leaves behind.
        """
        from helpers.registry import ServiceRegistry

        # exit() ends in SystemExit, which is a BaseException and so escapes
        # capture_response entirely; it prints its own farewell instead.
        exempt = {"exit"}

        modules = ServiceRegistry.get_job_modules()
        unwrapped = [
            name
            for name, func in self.jobs.items()
            # MCP tools are wrappers built at connect time, not decorated jobs.
            if name not in exempt
            and not modules.get(name, "").startswith("mcp:")
            and not hasattr(func, "_quiet_success")
        ]
        self.assertFalse(
            unwrapped,
            "Jobs registered without @capture_response underneath "
            "(swap the decorator order): " + ", ".join(sorted(unwrapped)),
        )

    def test_every_job_parses(self) -> None:
        from helpers.tools import _parse_signature

        for name, func in self.jobs.items():
            with self.subTest(job=name):
                description, properties, required = _parse_signature(func)
                self.assertTrue(description, f"'{name}' has no description")
                self.assertIsInstance(properties, dict)
                self.assertIsInstance(required, list)

    def test_documented_params_reach_the_schema(self) -> None:
        """A parameter documented in the docstring must carry that text, not the
        fallback — the symptom of a broken Args parse."""
        from helpers.tools import _parse_signature

        broken = []
        for name, func in self.jobs.items():
            doc = inspect.getdoc(func) or ""
            args_block = re.search(
                r"(?:Args|Parameters):(.*?)(?:\n\s*Returns:|\n\s*Raises:|\Z)",
                doc,
                re.DOTALL,
            )
            if not args_block:
                continue
            documented = set(_DOCUMENTED_ARG.findall(args_block.group(1)))
            _, properties, _ = _parse_signature(func)
            signature = inspect.signature(func).parameters
            for param in documented:
                if param not in signature:
                    continue
                desc = properties.get(param, {}).get("description", "")
                if not desc or desc == _NO_DESC:
                    broken.append(f"  {name}({param})")

        self.assertFalse(
            broken,
            "Documented parameters missing their description in the schema:\n"
            + "\n".join(broken),
        )

    def test_required_params_have_no_default(self) -> None:
        from helpers.tools import _parse_signature

        wrong = []
        for name, func in self.jobs.items():
            _, _, required = _parse_signature(func)
            signature = inspect.signature(func).parameters
            for param in required:
                spec = signature.get(param)
                if spec is not None and spec.default is not inspect.Parameter.empty:
                    wrong.append(f"  {name}({param}) is required but has a default")

        self.assertFalse(wrong, "\n".join(wrong))

    def test_schema_params_exist_in_signature(self) -> None:
        from helpers.tools import _parse_signature

        stray = []
        for name, func in self.jobs.items():
            _, properties, _ = _parse_signature(func)
            signature = inspect.signature(func).parameters
            for param in properties:
                if param not in signature:
                    stray.append(f"  {name}({param}) is not a real parameter")

        self.assertFalse(stray, "\n".join(stray))

    def test_literal_params_produce_enum(self) -> None:
        """A `Literal[...]` type hint must surface as a JSON-schema `enum` so the
        web UI can render a select instead of a free-text box, and the default
        value must be one of the declared choices. "" is the not-provided
        sentinel and is left out of the enum (Gemini rejects it there)."""
        import typing

        from helpers.tools import _parse_signature

        for name, func in self.jobs.items():
            try:
                type_hints = typing.get_type_hints(func)
            except Exception:
                continue
            signature = inspect.signature(func).parameters
            _, properties, _ = _parse_signature(func)
            for param, hint in type_hints.items():
                if getattr(hint, "__origin__", None) is not typing.Literal:
                    continue
                with self.subTest(job=name, param=param):
                    choices = list(hint.__args__)
                    entry = properties.get(param, {})
                    self.assertEqual(
                        entry.get("enum"), [c for c in choices if c != ""],
                        f"{name}({param}) is Literal but schema enum is {entry.get('enum')!r}",
                    )
                    default = signature[param].default
                    if default is not inspect.Parameter.empty:
                        self.assertIn(
                            default, choices,
                            f"{name}({param}) default {default!r} is not in {choices!r}",
                        )

    def test_the_empty_sentinel_is_valid_only_where_declared(self) -> None:
        """"" is how an optional Literal says "not provided". It stays out of the
        schema enum, but validate_args must still accept it where the type
        declares it, and must not accept it for a required choice."""
        from helpers.tools import validate_args
        from modules.spotify import Spotify

        self.assertIsNone(validate_args(Spotify.set_volume, {"direction": ""}))
        self.assertIsNone(validate_args(Spotify.play_songs, {"content_type": ""}))
        self.assertIsNotNone(validate_args(self.jobs["power"], {"action": ""}))
        self.assertIsNotNone(validate_args(Spotify.set_volume, {"direction": "sideways"}))

    def test_confirm_words_are_choices_of_a_validated_action(self) -> None:
        """`confirms={...}` matches the text of the job's `action` argument. That
        only holds when `action` is a Literal, because validate_args then
        rejects every other spelling: with a plain str the model can pass a
        synonym the job understands and the gate does not list."""
        import typing

        from helpers.registry import ServiceRegistry
        from helpers.tools import _literal_values

        for name, declared in ServiceRegistry.get_job_confirms().items():
            if not isinstance(declared, (set, frozenset, list, tuple)):
                continue
            func = self.jobs.get(name)
            if func is None:
                continue
            with self.subTest(job=name):
                allowed = _literal_values(typing.get_type_hints(func).get("action"))
                self.assertIsNotNone(
                    allowed, f"{name} confirms on action words but action is not a Literal"
                )
                self.assertLessEqual(
                    {str(word).lower() for word in declared},
                    {str(value).lower() for value in allowed},
                    f"{name} confirms on a word that is not one of its actions",
                )

    def test_schema_builds_for_every_provider(self) -> None:
        from helpers.tools import (
            function_to_schema_anthropic,
            function_to_schema_gemini,
            function_to_schema_ollama,
        )

        for name, func in self.jobs.items():
            with self.subTest(job=name):
                anthropic_schema = function_to_schema_anthropic(func)
                self.assertEqual(anthropic_schema["name"], func.__name__)
                self.assertEqual(anthropic_schema["input_schema"]["type"], "object")

                gemini_schema = function_to_schema_gemini(func)
                self.assertEqual(gemini_schema["name"], func.__name__)

                # Ollama nests the tool under a "function" key.
                ollama_schema = function_to_schema_ollama(func)
                self.assertEqual(ollama_schema["function"]["name"], func.__name__)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
