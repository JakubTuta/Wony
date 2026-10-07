"""Calling and saving numbers, without a phone number ever reaching the AI.

Run directly: python tests/test_phone.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DIGITS = "600 700 800"


def _people(*people):
    contacts = mock.Mock()
    contacts.search.return_value = list(people)
    return contacts


class TestCallPerson(unittest.TestCase):
    def setUp(self) -> None:
        from helpers.registry import ServiceRegistry
        from modules.contacts import Person, Phone

        self.tom = Person("Tom Nowak", ["tom@x.com"], [Phone("mobile", f"+48 {_DIGITS}")])
        self.services = {"contacts": _people(self.tom)}
        self.opened = []
        for patcher in (
            mock.patch.object(ServiceRegistry, "get_service_instance", side_effect=lambda n: self.services.get(n)),
            mock.patch("os.startfile", side_effect=self.opened.append, create=True),
            mock.patch("modules.phone._tel_handler", return_value="PhoneLink.tel"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _call(self, **kwargs) -> str:
        from helpers.turn_context import user_request
        from modules import phone

        with user_request("call tom"):
            return phone.call_person(**kwargs)

    def test_the_number_is_filled_in_and_the_user_presses_call(self) -> None:
        result = self._call(name="Tom")
        self.assertEqual(self.opened, ["tel:+48600700800"])
        self.assertIn("Press Call", result)
        self.assertNotIn("700", result)

    def test_several_numbers_are_asked_about_by_kind(self) -> None:
        from modules.contacts import Phone

        self.tom.phones.append(Phone("work", "+48 111 222 333"))
        result = self._call(name="Tom")
        self.assertEqual(self.opened, [])
        self.assertIn("mobile and work", result)
        self.assertNotIn("222", result)

        self._call(name="Tom", which="work")
        self.assertEqual(self.opened, ["tel:+48111222333"])

    def test_two_toms_are_asked_about_by_name(self) -> None:
        from modules.contacts import Person, Phone

        self.services["contacts"] = _people(self.tom, Person("Tom Kowal", [], [Phone("mobile", "+48 999 888 777")]))
        self.assertIn("Which Tom", self._call(name="Tom"))
        self.assertEqual(self.opened, [])

    def test_what_it_needs_is_said_when_it_is_missing(self) -> None:
        self.services.pop("contacts")
        result = self._call(name="Tom")
        self.assertIn("Google account", result)
        self.assertIn("Phone Link", result)
        with mock.patch("modules.phone._tel_handler", return_value=""):
            self.services["contacts"] = _people(self.tom)
            self.assertIn("Default apps", self._call(name="Tom"))
        self.assertEqual(self.opened, [])

    def test_not_from_a_phone_chat(self) -> None:
        from helpers.turn_context import user_request
        from modules import phone

        with user_request("call tom", at_machine=False):
            self.assertIn("at it", phone.call_person(name="Tom"))
        self.assertEqual(self.opened, [])

    def test_a_dictated_number_is_dialled_as_said(self) -> None:
        self._call(name="+48 600 700 800")
        self.assertEqual(self.opened, ["tel:+48600700800"])

    def test_nothing_reads_the_screen_or_presses_call(self) -> None:
        import modules.phone as phone

        self.assertFalse(hasattr(phone, "_press_call"))
        self.assertFalse(phone.call_person._job_confirms)


class TestFindKeepsNumbersLocal(unittest.TestCase):
    def test_numbers_go_to_the_user_not_the_model(self) -> None:
        from modules import contacts
        from modules.contacts import Person, Phone

        service = contacts.Contacts.__new__(contacts.Contacts)
        with mock.patch.object(contacts.Contacts, "search",
                               return_value=[Person("Tom", ["tom@x.com"], [Phone("mobile", f"+48 {_DIGITS}")])]), \
                mock.patch("modules.contacts.notify") as shown:
            result = contacts.Contacts.contact(service, "find", "Tom")
        self.assertNotIn("700", result)
        self.assertIn("mobile number on screen", result)
        self.assertIn(_DIGITS, shown.call_args.args[0][0])


class TestAddNumber(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import undo
        from modules import contacts

        undo.reset()
        self.contacts = contacts
        self.service = contacts.Contacts.__new__(contacts.Contacts)
        self.api = mock.Mock()
        self.people = self.api.people.return_value
        self.people.get.return_value.execute.return_value = {"etag": "e1", "phoneNumbers": []}
        for patcher in (
            mock.patch("helpers.google_auth.service", return_value=self.api),
            mock.patch("helpers.config.Config.get",
                       side_effect=lambda key, default=None: True if key == "modules.contacts.allow_write" else default),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _add(self, **kwargs) -> str:
        from helpers.turn_context import user_request

        with user_request("add ann's phone"):
            return self.contacts.Contacts.contact(self.service, "add_number", **kwargs)

    def test_a_new_person_is_created_and_undo_removes_them(self) -> None:
        from helpers import undo

        self.people.searchContacts.return_value.execute.return_value = {}
        self.people.createContact.return_value.execute.return_value = {"resourceName": "people/1"}
        result = self._add(name="Ann", number=_DIGITS)
        body = self.people.createContact.call_args.kwargs["body"]
        self.assertEqual(body["phoneNumbers"], [{"value": _DIGITS, "type": "mobile"}])
        self.assertNotIn("700", result)
        undo.undo()
        self.people.deleteContact.assert_called_with(resourceName="people/1")

    def test_an_existing_person_gets_the_number_added(self) -> None:
        self.people.searchContacts.return_value.execute.return_value = {"results": [{"person": {
            "resourceName": "people/2", "names": [{"displayName": "Ann Kowal"}],
            "phoneNumbers": [{"value": "+48 111 222 333", "type": "home"}],
        }}]}
        result = self._add(name="Ann", number=_DIGITS, label="work")
        self.assertEqual(result, "Saved it as Ann Kowal's work number.")
        phones = self.people.updateContact.call_args.kwargs["body"]["phoneNumbers"]
        self.assertEqual([p["type"] for p in phones], ["home", "work"])

    def test_off_until_the_user_allows_it(self) -> None:
        with mock.patch("helpers.config.Config.get", return_value=False):
            self.assertIn("not allowed", self._add(name="Ann", number=_DIGITS))
        self.people.createContact.assert_not_called()


class TestDictatedNumbersStayLocal(unittest.TestCase):
    """The user's own sentence holds the number; the model gets a placeholder
    and the job gets the digits back."""

    def test_the_model_sees_a_placeholder_and_the_job_the_digits(self) -> None:
        from helpers.agent import AgentResult
        from helpers.registry import ServiceRegistry
        from helpers.turn import run_turn

        seen = {}

        def save(name: str = "", number: str = "") -> str:
            """Saves a number."""
            seen["number"] = number
            return f"Saved {number} for {name}."

        def fake_agent(**kwargs):
            seen["prompt"] = kwargs["user_input"]
            from helpers import agent

            planned = [agent._plan({"id": "1", "name": "save", "args": {"name": "Ann", "number": "[number 1]"}},
                                   {"save": save}, lambda *a: None, True, lambda *a: None, "")]
            agent._run_planned(planned, True, lambda *a: None, None)
            from helpers import private_numbers

            seen["to_model"] = private_numbers.conceal(planned[0]["result"])
            return AgentResult(text="Saved [number 1] for Ann.", calls=[])

        with mock.patch("helpers.agent.run_agent", fake_agent), \
                mock.patch.dict(ServiceRegistry._jobs, {"save": save}), \
                mock.patch("helpers.bootstrap.get_ai_client", return_value=None), \
                mock.patch("modules.ai.build_agent_system_prompt", return_value=""), \
                mock.patch("helpers.conversation.Conversation.get_messages", return_value=[]):
            result = run_turn("add Ann's phone as +48 600 700 800")

        self.assertEqual(seen["prompt"], "add Ann's phone as [number 1]")
        self.assertEqual(seen["number"], "+48 600 700 800")
        self.assertNotIn("700", seen["to_model"])
        self.assertEqual(result.text, "Saved +48 600 700 800 for Ann.")

    def test_history_goes_out_without_numbers_and_dates_survive(self) -> None:
        from helpers.private_numbers import hide

        self.assertEqual(hide("call +48 600-700-800 on 2026-10-08 at 10:30"), "call [a number] on 2026-10-08 at 10:30")
        self.assertEqual(hide("set a timer for 25 minutes"), "set a timer for 25 minutes")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
