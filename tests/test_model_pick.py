"""Claude and Gemini always run their fastest model. "Latest" used to mean the
newest model of any family (Anthropic) or the alphabetically last name
(Gemini) — which could be the slowest model, a preview, or a TTS-only one.

Run directly: python tests/test_model_pick.py
"""
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _gemini(name: str, chat: bool = True):
    return types.SimpleNamespace(
        name=f"models/{name}", supported_actions=["generateContent"] if chat else ["embedContent"]
    )


def _claude(model_id: str, created: str):
    return types.SimpleNamespace(id=model_id, created_at=created)


class TestPickFlash(unittest.TestCase):
    def test_newest_stable_flash_wins_by_version_not_alphabet(self) -> None:
        from helpers.model import pick_flash

        models = [
            _gemini("gemini-3.8-flash"),
            _gemini("gemini-3.10-flash"),
            _gemini("gemini-3.9-pro"),
            _gemini("gemini-3.9-flash-lite"),
            _gemini("gemini-3.9-flash-tts"),
            _gemini("gemini-3.9-flash-image"),
            _gemini("gemini-4-flash-preview"),
            _gemini("gemini-embedding-001", chat=False),
        ]
        self.assertEqual(pick_flash(models), "gemini-3.10-flash")

    def test_preview_only_when_no_stable_flash(self) -> None:
        from helpers.model import pick_flash

        self.assertEqual(
            pick_flash([_gemini("gemini-3-flash-preview"), _gemini("gemini-3-pro")]),
            "gemini-3-flash-preview",
        )
        self.assertIsNone(pick_flash([_gemini("gemini-3-pro")]))


class TestPickHaiku(unittest.TestCase):
    def test_newest_haiku_not_newest_model(self) -> None:
        from helpers.model import pick_haiku

        models = [
            _claude("claude-opus-5-5", "2026-08-01"),
            _claude("claude-haiku-4-5-20251001", "2025-10-01"),
            _claude("claude-haiku-3-5", "2024-10-01"),
        ]
        self.assertEqual(pick_haiku(models), "claude-haiku-4-5-20251001")
        self.assertIsNone(pick_haiku([_claude("claude-opus-5-5", "2026-08-01")]))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
