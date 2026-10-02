"""Drive reads through Google's own export and writes only behind "Change my
Drive files"; documents from anywhere become text through one extractor.
No network: every Google answer is a fake.

Run directly: python tests/test_drive.py
"""
import io
import json
import os
import sys
import unittest
import zipfile
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

def _pdf(text: str) -> bytes:
    """The smallest valid PDF carrying one line of text."""
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % number + body + b"endobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)
    return out


_PDF = _pdf("Lease ends in May")


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
    return buffer.getvalue()


class TestTextExtract(unittest.TestCase):
    def test_formats(self) -> None:
        from helpers.text_extract import extract_bytes

        self.assertIn("Lease ends in May", extract_bytes(_PDF, "lease.pdf"))
        self.assertEqual(extract_bytes(_docx("Hello", "Tom &amp; Ana"), "notes.docx"), "Hello\nTom & Ana")
        self.assertEqual(extract_bytes(b"a,b\n1,2", "", "text/csv"), "a,b\n1,2")

    def test_binary_it_cannot_read_is_empty_not_noise(self) -> None:
        from helpers.text_extract import extract_bytes

        self.assertEqual(extract_bytes(b"\x89PNG\r\n\x1a\n\x00\x00", "photo.png"), "")
        self.assertEqual(extract_bytes(b"not a zip", "broken.docx"), "")


def _drive_with(files=None, export=b"", get_meta=None):
    """A fake googleapiclient Drive/Docs/Sheets, recording what was sent."""
    api = mock.MagicMock()
    api.files.return_value.list.return_value.execute.return_value = {"files": files or []}
    api.files.return_value.export.return_value.execute.return_value = export
    api.files.return_value.get.return_value.execute.side_effect = get_meta or Exception("not an id")
    api.files.return_value.create.return_value.execute.return_value = {"id": "new", "webViewLink": "https://docs/new"}
    api.documents.return_value.get.return_value.execute.return_value = {"body": {"content": [{"endIndex": 42}]}}
    return api


_BUDGET = {"id": "s1", "name": "Budget", "mimeType": "application/vnd.google-apps.spreadsheet"}
_NOTES = {"id": "d1", "name": "Notes", "mimeType": "application/vnd.google-apps.document"}


class TestDrive(unittest.TestCase):
    def setUp(self) -> None:
        from modules.drive import Drive

        self.drive = Drive.__new__(Drive)

    def _with(self, api, allow_write=False):
        return (
            mock.patch("helpers.google_auth.service", return_value=api),
            mock.patch("helpers.config.Config.get",
                       side_effect=lambda k, d=None: allow_write if k == "modules.drive.allow_write" else d),
        )

    def test_search_covers_names_and_contents(self) -> None:
        api = _drive_with([_NOTES])
        service, config = self._with(api)
        with service, config:
            out = self.drive.find_files(query="lease's end", kind="doc")
        q = api.files.return_value.list.call_args.kwargs["q"]
        self.assertIn("fullText contains 'lease\\'s end'", q)
        self.assertIn("application/vnd.google-apps.document", q)
        self.assertIn("Notes", out)

    def test_a_doc_is_read_through_markdown_export_and_fenced(self) -> None:
        api = _drive_with([_NOTES], export=b"# Notes\nBuy milk")
        service, config = self._with(api)
        with service, config:
            out = self.drive.find_files(view="read", file="Notes")
        self.assertEqual(api.files.return_value.export.call_args.kwargs["mimeType"], "text/markdown")
        self.assertIn("Buy milk", out)
        self.assertIn('<<<untrusted source="drive">>>', out)

    def test_writing_is_off_until_the_switch_and_says_what_it_would_write(self) -> None:
        api = _drive_with([_BUDGET])
        service, config = self._with(api, allow_write=False)
        with service, config:
            out = self.drive.edit_file(action="add_rows", file="Budget", rows='[["Rent", "1200"]]')
        self.assertIn("Change my Drive files", out)
        self.assertIn("Rent", out)
        api.spreadsheets.assert_not_called()

    def test_rows_and_append_reach_the_apis(self) -> None:
        api = _drive_with([_BUDGET])
        service, config = self._with(api, allow_write=True)
        with service, config:
            self.drive.edit_file(action="add_rows", file="Budget", rows='[["Rent", "1200"]]')
        body = api.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]
        self.assertEqual(body, {"values": [["Rent", "1200"]]})

        api = _drive_with([_NOTES])
        service, config = self._with(api, allow_write=True)
        with service, config:
            self.drive.edit_file(action="append", file="Notes", text="Call Anna")
        request = api.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"][0]
        self.assertEqual(request["insertText"]["location"]["index"], 41)
        self.assertIn("Call Anna", request["insertText"]["text"])

    def test_ambiguous_names_are_not_guessed(self) -> None:
        twins = [dict(_NOTES, id="a", name="Notes 1"), dict(_NOTES, id="b", name="Notes 2")]
        api = _drive_with(twins)
        service, config = self._with(api, allow_write=True)
        with service, config:
            out = self.drive.edit_file(action="append", file="Notes", text="x")
        self.assertIn("Several files", out)
        api.documents.assert_not_called()


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
