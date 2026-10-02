"""MCP tools are third-party code that can do anything. Before this, every one
of them ran without the confirm gate — a tool named `delete_all_files` ran the
moment the model picked it.

Run directly: python tests/test_mcp_confirms.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


class _FakeSession:
    name = "fake"

    def list_tools(self):
        return [
            {"name": "read_thing", "description": "Reads.", "read_only": True},
            {"name": "delete_thing", "description": "Deletes.", "read_only": False},
            {"name": "unannotated", "description": "Says nothing."},
        ]

    def is_alive(self) -> bool:
        return True


class TestMcpConfirms(unittest.TestCase):
    def tearDown(self) -> None:
        from helpers.mcp_client import _unregister_tools

        _unregister_tools("fake")

    def test_only_read_only_tools_skip_the_confirm(self) -> None:
        from helpers.mcp_client import _register_tools
        from helpers.registry import ServiceRegistry

        _register_tools(_FakeSession())
        self.assertFalse(ServiceRegistry.job_confirms("read_thing"))
        self.assertTrue(ServiceRegistry.job_confirms("delete_thing"))
        self.assertTrue(ServiceRegistry.job_confirms("unannotated"))

    def test_unregister_forgets_the_gate(self) -> None:
        from helpers.mcp_client import _register_tools, _unregister_tools
        from helpers.registry import ServiceRegistry

        _register_tools(_FakeSession())
        _unregister_tools("fake")
        self.assertNotIn("delete_thing", ServiceRegistry.get_job_confirms())


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
