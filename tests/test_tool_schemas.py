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
