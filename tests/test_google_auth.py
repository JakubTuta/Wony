"""One Google sign-in per account, asking only for what the switches allow.

The failures this guards are all silent: a write scope granted while the
switch is off, a consent window popping up from a background poll, and old
per-service token files that never get cleaned up.

Run directly: python tests/test_google_auth.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

_API = "https://www.googleapis.com/auth/"


def _config(modules, switches=None):
    """Patch Config so `modules` are on and `switches` (dotted key -> bool) set."""
    switches = switches or {}
    return (
        mock.patch("helpers.config.Config.is_module_enabled", side_effect=lambda m: m in modules),
        mock.patch("helpers.config.Config.get", side_effect=lambda key, default=None: switches.get(key, default)),
    )


class TestScopes(unittest.TestCase):
    def _wanted(self, modules, switches=None):
        from helpers.google_auth import scopes_wanted

        on, get = _config(modules, switches)
        with on, get:
            return set(scopes_wanted())

    def test_read_only_until_a_switch_is_on(self) -> None:
        scopes = self._wanted({"gmail", "calendar", "drive"})
        self.assertIn(_API + "gmail.readonly", scopes)
        self.assertIn(_API + "calendar.readonly", scopes)
        self.assertIn(_API + "drive.readonly", scopes)
        for write in ("gmail.modify", "calendar.events", "documents", "spreadsheets", "drive.file"):
            self.assertNotIn(_API + write, scopes)

    def test_each_switch_adds_only_its_own_scopes(self) -> None:
        scopes = self._wanted({"gmail", "calendar"}, {"modules.calendar.allow_write": True})
        self.assertIn(_API + "calendar.events", scopes)
        self.assertNotIn(_API + "gmail.modify", scopes)

    def test_switched_off_modules_ask_for_nothing(self) -> None:
        scopes = self._wanted({"calendar"})
        self.assertFalse(any("gmail" in s or "drive" in s for s in scopes))


class AccountsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import accounts

        self.dir = tempfile.mkdtemp()
        self._patches = [
            mock.patch.object(accounts, "_ACCOUNTS_FILE", os.path.join(self.dir, "accounts.json")),
            mock.patch.object(accounts, "repo_path", side_effect=lambda *p: os.path.join(self.dir, *p)),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)
        accounts.GoogleAccounts._data = None
        self.addCleanup(setattr, accounts.GoogleAccounts, "_data", None)


class TestMigration(AccountsTestCase):
    def test_per_service_tokens_become_one_and_are_deleted_after_sign_in(self) -> None:
        from helpers.accounts import GoogleAccounts

        os.makedirs(os.path.join(self.dir, "credentials"))
        old = ["credentials/gmail_token_work.json", "credentials/calendar_token_work.json"]
        for path in old:
            open(os.path.join(self.dir, path), "w").close()
        with open(os.path.join(self.dir, "accounts.json"), "w") as fh:
            json.dump({"primary": "work", "accounts": {"work": {
                "gmail_token": old[0], "calendar_token": old[1], "email": "me@x.com"}}}, fh)

        record = GoogleAccounts.record("work")
        self.assertTrue(record["token"].endswith("google_token_work.json"))
        self.assertTrue(record["needs_sign_in"])
        self.assertEqual(record["email"], "me@x.com")

        GoogleAccounts.drop_legacy_tokens("work")
        for path in old:
            self.assertFalse(os.path.exists(os.path.join(self.dir, path)))


class TestNoSurpriseBrowser(AccountsTestCase):
    def test_background_code_never_opens_consent(self) -> None:
        from helpers import google_auth
        from helpers.accounts import GoogleAccounts

        GoogleAccounts.add_account("work")
        on, get = _config({"gmail"})
        with on, get, mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file") as flow:
            with self.assertRaises(google_auth.SignInNeeded) as raised:
                google_auth.credentials("work")
        flow.assert_not_called()
        self.assertIn("authorize work", str(raised.exception))

    def test_a_chat_from_a_phone_never_opens_it_on_an_empty_desk(self) -> None:
        from helpers import google_auth
        from helpers.accounts import GoogleAccounts
        from helpers.turn_context import user_request

        GoogleAccounts.add_account("work")
        on, get = _config({"gmail"})
        with on, get, user_request("check my mail", at_machine=False), \
                mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file") as flow:
            with self.assertRaises(google_auth.SignInNeeded) as raised:
                google_auth.credentials("work")
        flow.assert_not_called()
        self.assertIn("at your PC", str(raised.exception))

    def test_a_user_request_may_open_it(self) -> None:
        from helpers import google_auth
        from helpers.accounts import GoogleAccounts
        from helpers.turn_context import user_request

        GoogleAccounts.add_account("work")
        on, get = _config({"gmail"})
        fake_creds = mock.Mock(scopes=[], to_json=lambda: "{}")
        with on, get, user_request("check my mail"), \
                mock.patch("os.path.exists", return_value=True), \
                mock.patch.object(google_auth, "_load", return_value=None), \
                mock.patch.object(google_auth, "_save"), \
                mock.patch.object(google_auth, "_email_for", return_value="me@x.com"), \
                mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file") as flow:
            flow.return_value.run_local_server.return_value = fake_creds
            google_auth.credentials("work")
        asked = set(flow.call_args.kwargs["scopes"])
        self.assertIn(_API + "gmail.readonly", asked)
        self.assertNotIn(_API + "gmail.modify", asked)
        self.assertEqual(GoogleAccounts.record("work")["email"], "me@x.com")
        self.assertFalse(GoogleAccounts.record("work")["needs_sign_in"])

    def test_an_expired_sign_in_is_announced_once(self) -> None:
        from google.auth.exceptions import RefreshError

        from helpers import google_auth
        from helpers.accounts import GoogleAccounts

        GoogleAccounts.add_account("work")
        stale = mock.Mock(valid=False, refresh_token="r", scopes=sorted(google_auth._IDENTITY + [_API + "gmail.readonly", _API + "gmail.compose"]))
        stale.refresh.side_effect = RefreshError("invalid_grant")
        on, get = _config({"gmail"})
        with on, get, mock.patch.object(google_auth, "_load", return_value=stale), \
                mock.patch("helpers.notify.notify") as notify:
            for _ in range(3):
                with self.assertRaises(google_auth.SignInNeeded):
                    google_auth.credentials("work")
        self.assertEqual(notify.call_count, 1)
        self.assertTrue(GoogleAccounts.record("work")["needs_sign_in"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
