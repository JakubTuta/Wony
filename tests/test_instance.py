"""Two Wony processes would each restore every timer from wony.db and fire it, so
the entry points claim a lock first (helpers/instance.py). It has to be refused
across processes, and it has to be gone when Wony dies without cleaning up.

Run directly: python tests/test_instance.py
"""
import ast
import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

_HOLDER = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
from helpers import instance
instance._LOCK_FILE = sys.argv[2]
assert instance.acquire()
print(os.getpid(), flush=True)
time.sleep(60)
"""


class TestOnlyOneWony(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import instance

        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, ".wony_lock")
        patcher = mock.patch.object(instance, "_LOCK_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        from helpers import instance

        instance.release()
        self._tmp.cleanup()

    def _someone_else_can_lock(self) -> bool:
        from helpers import instance

        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            return instance._lock(fd)
        finally:
            os.close(fd)

    def test_the_first_claim_wins_and_a_second_is_refused(self) -> None:
        from helpers import instance

        self.assertTrue(instance.acquire())
        self.assertFalse(self._someone_else_can_lock())
        self.assertEqual(instance.holder_pid(), os.getpid())

    def test_claiming_twice_in_one_process_is_not_a_conflict(self) -> None:
        from helpers import instance

        self.assertTrue(instance.acquire())
        self.assertTrue(instance.acquire())

    def test_releasing_lets_the_next_one_in(self) -> None:
        from helpers import instance

        instance.acquire()
        instance.release()
        self.assertTrue(self._someone_else_can_lock())

    def test_a_wony_that_is_killed_leaves_nothing_behind(self) -> None:
        from helpers import instance

        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, _REPO_ROOT, self.path],
            stdout=subprocess.PIPE, text=True,
        )
        # The holder reports its own pid: a venv's python.exe on Windows is a
        # launcher, and killing that would leave the real interpreter running.
        holder_pid = int(holder.stdout.readline())
        try:
            self.assertFalse(instance.acquire())
            self.assertEqual(instance.holder_pid(), holder_pid)
        finally:
            os.kill(holder_pid, signal.SIGTERM)
            holder.wait()
            holder.stdout.close()
        self.assertTrue(instance.acquire())

    def test_a_refused_copy_says_who_is_running_and_how_to_stop_it(self) -> None:
        from helpers import instance

        out = io.StringIO()
        with mock.patch.object(instance, "acquire", return_value=False), \
                mock.patch.object(instance, "holder_pid", return_value=4242), \
                contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as raised:
            instance.claim_or_exit("Stop it with the stop command.")
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("4242", out.getvalue())
        self.assertIn("Stop it with the stop command.", out.getvalue())

    def test_the_first_copy_just_carries_on(self) -> None:
        from helpers import instance

        instance.claim_or_exit("unused")
        self.assertEqual(instance.holder_pid(), os.getpid())


class TestEveryEntryPointClaimsIt(unittest.TestCase):
    def test_a_command_that_bootstraps_claims_the_lock_first(self) -> None:
        """A new `wony.py` command that starts the assistant but forgets the
        claim would run beside the real one with nothing to say so."""
        with open(os.path.join(_REPO_ROOT, "wony.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        def calls(node: ast.AST) -> list:
            return [
                n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                for n in ast.walk(node) if isinstance(n, ast.Call)
            ]

        starts_wony = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("cmd_")
            and "bootstrap" in calls(node)
        ]
        self.assertTrue(starts_wony, "no command in wony.py bootstraps the assistant")
        for node in starts_wony:
            with self.subTest(command=node.name):
                self.assertIn("claim_or_exit", calls(node))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
