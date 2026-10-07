"""Updating without a terminal, and a web page without Node.js.

Run directly: python tests/test_updates.py
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _zip(files, prefix="", comment=b""):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(prefix + name, body)
        archive.comment = comment
    return buffer.getvalue()


class TestWebPageDownload(unittest.TestCase):
    def test_a_zip_copy_gets_the_newest_page(self) -> None:
        from helpers import updates

        page = _zip({"index.html": "<!doctype html>", "assets/app.js": "x"})
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(updates, "_is_git_checkout", return_value=False), \
                mock.patch.object(updates, "_download", return_value=page) as fetch:
            dist = os.path.join(root, "dist")
            self.assertEqual(updates.download_web_ui(dist), "")
            self.assertTrue(os.path.isfile(os.path.join(dist, "assets", "app.js")))
        self.assertTrue(fetch.call_args.args[0].endswith("wony-web-latest.zip"))

    def test_a_checkout_gets_the_build_of_its_own_web_folder(self) -> None:
        from helpers import updates

        def git(*args):
            return {"status": "", "rev-parse": "abc123"}[args[0]]

        page = _zip({"index.html": "<html>"})
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(updates, "_is_git_checkout", return_value=True), \
                mock.patch.object(updates, "_git", side_effect=git), \
                mock.patch.object(updates, "_download", return_value=page) as fetch:
            self.assertEqual(updates.download_web_ui(os.path.join(root, "dist")), "")
        self.assertTrue(fetch.call_args.args[0].endswith("wony-web-abc123.zip"))

    def test_local_edits_to_the_page_are_built_not_downloaded(self) -> None:
        from helpers import updates

        with mock.patch.object(updates, "_is_git_checkout", return_value=True), \
                mock.patch.object(updates, "_git", return_value=" M web/src/App.tsx"), \
                mock.patch.object(updates, "_download") as fetch:
            self.assertIn("local edits", updates.download_web_ui("unused"))
        fetch.assert_not_called()

    def test_a_page_that_reaches_outside_its_folder_is_refused(self) -> None:
        from helpers import updates

        evil = _zip({"index.html": "<html>", "../../evil.py": "x"})
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(updates, "_is_git_checkout", return_value=False), \
                mock.patch.object(updates, "_download", return_value=evil):
            self.assertIn("malformed", updates.download_web_ui(os.path.join(root, "dist")))
            self.assertFalse(os.path.exists(os.path.join(root, "dist")))


class TestZipUpdate(unittest.TestCase):
    def test_new_files_land_deleted_ones_go_and_user_files_stay(self) -> None:
        from helpers import updates

        archive = _zip(
            {"wony.py": "new", "modules/kept.py": "new"},
            prefix="Wony-main/",
            comment=b"deadbeef",
        )
        with tempfile.TemporaryDirectory() as root:
            for name, body in {"wony.py": "old", "modules/gone.py": "old", ".env": "KEY=1"}.items():
                os.makedirs(os.path.dirname(os.path.join(root, name)) or root, exist_ok=True)
                with open(os.path.join(root, name), "w") as fh:
                    fh.write(body)
            with open(os.path.join(root, ".wony_files"), "w") as fh:
                fh.write("wony.py\nmodules/gone.py")

            with mock.patch.object(updates, "REPO_ROOT", root), \
                    mock.patch.object(updates, "_MANIFEST_FILE", os.path.join(root, ".wony_files")), \
                    mock.patch.object(updates, "_VERSION_FILE", os.path.join(root, ".wony_version")), \
                    mock.patch.object(updates, "_download", return_value=archive):
                updates._apply_zip()

            with open(os.path.join(root, "wony.py")) as fh:
                self.assertEqual(fh.read(), "new")
            self.assertFalse(os.path.exists(os.path.join(root, "modules", "gone.py")))
            self.assertTrue(os.path.exists(os.path.join(root, "modules", "kept.py")))
            self.assertTrue(os.path.exists(os.path.join(root, ".env")))
            with open(os.path.join(root, ".wony_version")) as fh:
                self.assertEqual(fh.read(), "deadbeef")


class TestApply(unittest.TestCase):
    def test_local_edits_are_never_overwritten(self) -> None:
        from helpers import updates

        with mock.patch.object(updates, "_is_git_checkout", return_value=True), \
                mock.patch.object(updates, "_local_edits", return_value=True), \
                mock.patch.object(updates, "_run_setup_update") as setup:
            worked, message = updates.apply()
        self.assertFalse(worked)
        self.assertIn("local edits", message)
        setup.assert_not_called()


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
