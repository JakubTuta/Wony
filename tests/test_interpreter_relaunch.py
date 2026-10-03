"""wony.py and setup.py configure used to refuse to run under the wrong
interpreter instead of switching to the right one — meaning every documented
`python wony.py ...` command failed the moment setup had used a venv, which
install.bat's own default recommends.

Run directly: python tests/test_interpreter_relaunch.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _load(module_name: str, filename: str):
    import importlib.util

    path = os.path.join(_REPO_ROOT, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestWonyPyRelaunch(unittest.TestCase):
    def test_a_mismatched_interpreter_relaunches_under_the_recorded_one(self) -> None:
        wony = _load("wony_under_test", "wony.py")

        with tempfile.TemporaryDirectory() as tmp:
            other_dir = os.path.join(tmp, "venv")
            os.makedirs(other_dir)
            other_python = os.path.join(other_dir, "python.exe")
            open(other_python, "w").close()
            marker = os.path.join(tmp, ".wony_setup")
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"python": other_python, "python_dir": other_dir}, fh)

            with mock.patch.object(wony, "__file__", os.path.join(tmp, "wony.py")), \
                    mock.patch("os.execv") as execv:
                wony._require_setup()
            execv.assert_called_once()
            self.assertEqual(execv.call_args[0][0], other_python)

    def test_a_missing_recorded_interpreter_fails_with_a_clear_message_not_a_crash(self) -> None:
        wony = _load("wony_under_test2", "wony.py")

        with tempfile.TemporaryDirectory() as tmp:
            gone_python = os.path.join(tmp, "nonexistent", "python.exe")
            marker = os.path.join(tmp, ".wony_setup")
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"python": gone_python, "python_dir": os.path.join(tmp, "nonexistent")}, fh)

            with mock.patch.object(wony, "__file__", os.path.join(tmp, "wony.py")), \
                    mock.patch("os.execv") as execv, \
                    self.assertRaises(SystemExit):
                wony._require_setup()
            execv.assert_not_called()


class TestSetupPyConfigureRelaunch(unittest.TestCase):
    def test_configure_relaunches_under_the_recorded_interpreter(self) -> None:
        setup_mod = _load("setup_under_test", "setup.py")

        with tempfile.TemporaryDirectory() as tmp:
            other_python = os.path.join(tmp, "venv", "python.exe")
            os.makedirs(os.path.dirname(other_python))
            open(other_python, "w").close()
            marker = os.path.join(tmp, ".wony_setup")
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"python": other_python}, fh)

            with mock.patch.object(setup_mod, "MARKER", marker), \
                    mock.patch("os.execv") as execv:
                setup_mod._relaunch_under_setup_python()
            execv.assert_called_once()
            self.assertEqual(execv.call_args[0][0], other_python)

    def test_already_the_right_interpreter_does_not_relaunch(self) -> None:
        setup_mod = _load("setup_under_test2", "setup.py")

        marker_data = {"python": sys.executable}
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, ".wony_setup")
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump(marker_data, fh)

            with mock.patch.object(setup_mod, "MARKER", marker), \
                    mock.patch("os.execv") as execv:
                setup_mod._relaunch_under_setup_python()
            execv.assert_not_called()


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
