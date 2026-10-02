"""Contacts, attachments, invitations and file search. Each has one way to go
quietly wrong: mail to the wrong Anna, an attachment read as binary noise, an
invitation that never emails the guests, a search that misses file contents.

Run directly: python tests/test_people_and_files.py
"""
import base64
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _contacts(people):
    from modules.contacts import Person

    service = mock.Mock()
    service.search.side_effect = lambda query, account="": [
        Person(name, emails, []) for name, emails in people if query.lower() in name.lower()
    ]
    return mock.patch("helpers.registry.ServiceRegistry.get_service_instance", return_value=service)


class TestNameResolution(unittest.TestCase):
    def test_one_match_many_matches_none(self) -> None:
        from modules.contacts import resolve_addresses

        people = [("Anna Kowalska", ["anna@k.pl"]), ("Anna Nowak", ["anna@n.pl"]), ("Tom", ["tom@x.com"])]
        with _contacts(people):
            self.assertEqual(resolve_addresses("Tom, bob@y.com"), (["tom@x.com", "bob@y.com"], ""))
            addresses, problem = resolve_addresses("Anna")
            self.assertEqual(addresses, [])
            self.assertIn("anna@k.pl", problem)
            self.assertIn("anna@n.pl", problem)
            self.assertEqual(resolve_addresses("Zed")[1], "I don't have an email address for Zed.")

    def test_without_contacts_a_name_is_refused_not_guessed(self) -> None:
        from modules.contacts import resolve_addresses

        with mock.patch("helpers.registry.ServiceRegistry.get_service_instance", return_value=None):
            addresses, problem = resolve_addresses("Tom")
        self.assertEqual(addresses, [])
        self.assertIn("Contacts", problem)


class TestInvitations(unittest.TestCase):
    def test_guests_get_emailed_and_a_meet_link_is_requested(self) -> None:
        from modules.calendar import Calendar

        cal = Calendar.__new__(Calendar)
        service = mock.MagicMock()
        service.events.return_value.insert.return_value.execute.return_value = {
            "start": {"dateTime": "2026-10-09T10:00:00+02:00"}, "hangoutLink": "https://meet.google.com/abc",
        }
        with _contacts([("Tom", ["tom@x.com"])]), \
                mock.patch.object(Calendar, "_service_for", return_value=service), \
                mock.patch.object(Calendar, "_write_allowed", return_value=True):
            out = cal.manage_event(title="Sync", date="2026-10-09", start_time="10am",
                                   attendees="Tom", add_meet_link=True)
        kwargs = service.events.return_value.insert.call_args.kwargs
        self.assertEqual(kwargs["sendUpdates"], "all")
        self.assertEqual(kwargs["conferenceDataVersion"], 1)
        self.assertEqual(kwargs["body"]["attendees"], [{"email": "tom@x.com"}])
        self.assertEqual(kwargs["body"]["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"], "hangoutsMeet")
        self.assertIn("meet.google.com/abc", out)


class TestAttachments(unittest.TestCase):
    def test_attachment_text_is_read_fenced_and_saved_without_overwriting(self) -> None:
        from modules.gmail import Attachment, Gmail, Msg

        gmail = Gmail.__new__(Gmail)
        msg = Msg(id="m1", subject="Lease", sender="Marta <m@x.pl>",
                  attachments=[Attachment("notes.txt", "text/plain", 20, "a1")])
        svc = mock.MagicMock()
        svc.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(b"Rent is due on the 5th").decode()}
        folder = tempfile.mkdtemp()
        open(os.path.join(folder, "notes.txt"), "w").close()
        with mock.patch.object(Gmail, "_find_latest", return_value=("work", msg)), \
                mock.patch.object(Gmail, "_svc", return_value=svc), \
                mock.patch("helpers.paths.downloads_dir", return_value=folder):
            out = gmail.find_emails(view="attachments", subject="lease", save_attachments=True)
        self.assertIn("Rent is due on the 5th", out)
        self.assertIn('<<<untrusted source="email attachment">>>', out)
        self.assertTrue(os.path.exists(os.path.join(folder, "notes (1).txt")))

    def test_mime_walk_keeps_what_is_needed_to_download(self) -> None:
        from modules.gmail import _walk_parts

        payload = {"parts": [
            {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"hi").decode()}},
            {"mimeType": "application/pdf", "filename": "a.pdf", "body": {"attachmentId": "X", "size": 99}},
        ]}
        plain, _, attachments = _walk_parts(payload)
        self.assertEqual(plain, "hi")
        self.assertEqual((attachments[0].filename, attachments[0].attachment_id, attachments[0].size), ("a.pdf", "X", 99))


class TestFileSearch(unittest.TestCase):
    def test_query_is_escaped_for_the_index(self) -> None:
        from modules import desktop

        captured = {}

        class _Records:
            EOF = True

            def Open(self, sql, connection):
                captured["sql"] = sql

            def Close(self):
                pass

        fake = types.SimpleNamespace(Dispatch=lambda name: _Records() if name == "ADODB.Recordset" else mock.Mock())
        with mock.patch.dict(sys.modules, {"win32com": types.SimpleNamespace(client=fake), "win32com.client": fake}):
            desktop._indexed_search("50% off at Bob's", r"C:\Users\me\Docs")
        sql = captured["sql"]
        self.assertIn("FREETEXT('50% off at Bob''s')", sql)
        self.assertIn("LIKE '%50[%] off at Bob''s%'", sql)
        self.assertIn("SCOPE='file:C:/Users/me/Docs'", sql)

    def test_without_the_index_names_still_match_and_it_says_so(self) -> None:
        from modules import desktop

        folder = tempfile.mkdtemp()
        open(os.path.join(folder, "lease-2025.pdf"), "w").close()
        with mock.patch.object(desktop, "_indexed_search", side_effect=OSError("service off")):
            out = desktop.Desktop.find_file(desktop.Desktop.__new__(desktop.Desktop), "lease", folder)
        self.assertIn("lease-2025.pdf", out)
        self.assertIn("only matched file names", out)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
