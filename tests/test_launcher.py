"""wony.sh finds a Python so the person at the device does not have to know
whether this one calls it `python` or `python3`, and says what to install when
there is none. Raspberry Pi OS ships only python3.

Run directly: python tests/test_launcher.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SH = shutil.which("sh")

_NEW = '#!/bin/sh\nif [ "$1" = "-c" ]; then exit 0; fi\necho "%s $@"\n'
_OLD = '#!/bin/sh\nif [ "$1" = "-c" ]; then exit 1; fi\necho "%s $@"\n'
# wony.sh asks dirname where it lives; with PATH cut down to the stubs there is
# no real one, and it was started from its own folder.
_DIRNAME = '#!/bin/sh\necho "."\n'


@unittest.skipIf(_SH is None, "needs a POSIX sh")
class TestLauncher(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self._tmp.name, "app")
        self.bin = os.path.join(self._tmp.name, "bin")
        os.makedirs(self.app)
        os.makedirs(self.bin)
        shutil.copy(os.path.join(_REPO_ROOT, "wony.sh"), self.app)
        self._stub(self.bin, "dirname", _DIRNAME)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _stub(folder: str, name: str, body: str) -> None:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", newline="\n") as handle:
            handle.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        env = {"PATH": self.bin}
        return subprocess.run(
            [_SH, "wony.sh", *args], cwd=self.app, env=env,
            capture_output=True, text=True, timeout=30,
        )

    def test_python3_is_used_when_there_is_no_python(self) -> None:
        self._stub(self.bin, "python3", _NEW % "python3")
        result = self._run("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "python3 wony.py doctor")

    def test_python_is_preferred_to_python3(self) -> None:
        self._stub(self.bin, "python", _NEW % "python")
        self._stub(self.bin, "python3", _NEW % "python3")
        self.assertEqual(self._run().stdout.strip(), "python wony.py")

    def test_the_project_venv_is_preferred_to_both(self) -> None:
        self._stub(self.bin, "python", _NEW % "python")
        self._stub(self.bin, "python3", _NEW % "python3")
        self._stub(os.path.join(self.app, "venv", "bin"), "python", _NEW % "venv")
        self.assertEqual(self._run("text").stdout.strip(), "venv wony.py text")

    def test_setup_runs_the_installer_with_the_rest_of_the_arguments(self) -> None:
        self._stub(self.bin, "python3", _NEW % "python3")
        self.assertEqual(self._run("setup", "configure").stdout.strip(), "python3 setup.py configure")

    def test_no_python_at_all_says_to_install_it_and_fails(self) -> None:
        result = self._run("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Python is not installed", result.stdout)
        self.assertIn("sudo apt install python3", result.stdout)

    def test_an_old_python_is_not_used_and_is_named_as_the_problem(self) -> None:
        self._stub(self.bin, "python3", _OLD % "python3")
        result = self._run("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("too old", result.stdout)
        self.assertNotIn("wony.py", result.stdout)

    def test_an_old_python_is_skipped_for_a_newer_one(self) -> None:
        self._stub(self.bin, "python", _OLD % "python")
        self._stub(self.bin, "python3", _NEW % "python3")
        self.assertEqual(self._run().stdout.strip(), "python3 wony.py")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
