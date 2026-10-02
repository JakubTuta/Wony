"""Browsing hands a model a real browser, so its boundaries are the point:
it must not reach the local network, a page the user never named or searched
for must be confirmed first — with or without a task, since reading a page
can leak data exactly as well as clicking through it can — and the sub-agent
must not touch the user's turn — its confirm gate and its tool-outcome
ledger.

Run directly: python tests/test_browse.py
"""
import os
import sys
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class TestExfilRule(unittest.TestCase):
    def _needs_ok(self, said: str, url: str, task: str = "find the price") -> bool:
        from helpers.turn_context import user_request
        from modules.web import _needs_ok

        with user_request(said), mock.patch("helpers.conversation.Conversation.get_messages", return_value=[]):
            return _needs_ok({"url": url, "task": task})

    def test_a_site_the_user_named_runs_without_asking(self) -> None:
        self.assertFalse(self._needs_ok("check the price on shop.example", "https://www.shop.example/item/1"))

    def test_a_site_from_somewhere_else_needs_a_yes(self) -> None:
        self.assertTrue(self._needs_ok("summarise my latest email", "https://evil.example/?inbox=secret"))

    def test_plain_reading_of_an_unnamed_site_needs_a_yes(self) -> None:
        self.assertTrue(self._needs_ok("read my email", "https://evil.example/", task=""))

    def test_plain_reading_of_a_named_site_runs_without_asking(self) -> None:
        self.assertFalse(self._needs_ok("read shop.example for me", "https://shop.example/", task=""))

    def test_a_substring_domain_does_not_count_as_named(self) -> None:
        self.assertTrue(self._needs_ok("summarise notevil.example for me", "https://evil.example/", task=""))

    def test_a_link_from_this_turns_search_runs_without_asking(self) -> None:
        from helpers.turn_context import record_search_hrefs, user_request
        from modules.web import _needs_ok

        with user_request("find me a shop"), \
                mock.patch("helpers.conversation.Conversation.get_messages", return_value=[]):
            record_search_hrefs(["https://evil.example/?d=secret"])
            self.assertFalse(_needs_ok({"url": "https://evil.example/?d=secret", "task": ""}))

    def test_the_gate_is_wired_into_confirm(self) -> None:
        from helpers import confirm
        from helpers.turn_context import user_request
        from modules.web import _needs_ok

        with mock.patch("helpers.registry.ServiceRegistry.get_job_confirms", return_value={"browse": _needs_ok}), \
                mock.patch("helpers.conversation.Conversation.get_messages", return_value=[]), \
                user_request("summarise my latest email"):
            confirm.reset()
            message = confirm.check("browse", {"url": "https://evil.example/", "task": "click send"})
        self.assertIsNotNone(message)


class TestIsolatedLoop(unittest.TestCase):
    def test_sub_agent_skips_the_gate_and_the_ledger_and_trims_old_pages(self) -> None:
        from helpers import agent

        seen_messages = []
        steps = iter([
            [{"id": "1", "name": "scroll", "args": {}}],
            [{"id": "2", "name": "scroll", "args": {}}],
            [{"id": "3", "name": "scroll", "args": {}}],
            [],
        ])

        def fake_send(**kwargs):
            seen_messages.append([dict(m) for m in kwargs["messages"]])
            return object()

        page = "x" * 5000
        tools = {"scroll": lambda: page}
        tools["scroll"].__name__ = "scroll"
        with mock.patch("helpers.model.send_agent_messages", side_effect=fake_send), \
                mock.patch.object(agent, "_extract_all_tool_calls", side_effect=lambda r: next(steps)), \
                mock.patch("helpers.model.get_text_from_response", return_value="Battery: 5000 mAh"), \
                mock.patch("helpers.confirm.check") as gate, \
                mock.patch.object(agent, "record_tool_outcome") as ledger:
            result = agent.run_agent(
                client=None, user_input="task", available_jobs=tools,
                system_instructions="", isolated=True, keep_full_results=1, max_steps=6,
            )
        self.assertEqual(result.text, "Battery: 5000 mAh")
        gate.assert_not_called()
        ledger.assert_not_called()
        last = [m for m in seen_messages[-1] if m["role"] == "tool_result"]
        self.assertLess(len(last[0]["content"]), 1000)  # older page trimmed
        self.assertEqual(len(last[-1]["content"]), 5000)  # latest page whole


class TestBrowseJob(unittest.TestCase):
    def test_a_task_without_the_browser_feature_says_what_to_do(self) -> None:
        from modules import web

        with mock.patch("helpers.net.is_public_url", return_value=True), \
                mock.patch("modules.web.is_public_url", return_value=True), \
                mock.patch("helpers.browser.available", return_value=False):
            out = web.browse("https://shop.example/", task="find the price")
        self.assertIn("Web browsing", out)


class TestRealBrowser(unittest.TestCase):
    """Skipped where no browser can start (CI)."""

    def test_snapshot_refs_drive_clicks(self) -> None:
        from helpers import browser

        if not browser.available():
            self.skipTest("playwright not installed")
        try:
            session = browser.Session().__enter__()
        except Exception as e:
            self.skipTest(f"no browser: {e}")
        try:
            session.page.set_content(
                "<div role=tablist><button role=tab>Overview</button>"
                "<button role=tab onclick=\"document.getElementById('p').textContent='Battery: 5000 mAh'\">Specs</button>"
                "</div><p id=p>Pick a tab</p>"
            )
            browser._active = session
            import re

            ref = re.search(r'tab "Specs" \[ref=(\w+)\]', session.snapshot()).group(1)
            self.assertIn("Battery: 5000 mAh", browser.click(ref))
            self.assertTrue(browser.goto("http://127.0.0.1:1/").startswith("Refused"))
        finally:
            browser._active = None
            session.__exit__(None, None, None)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
