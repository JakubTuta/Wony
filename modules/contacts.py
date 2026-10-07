"""Google Contacts: "what's Tom's number", "add Ann's phone as …", and turning
"email Anna" into an address. Also searches "Other contacts" — the people Gmail
remembers because you wrote to them — since that is where most addresses live.

Phone numbers never reach the AI provider: found ones go to the user through
notify(), and one being saved arrives as digits put back by helpers/agent.py.
"""
import re
import typing

from helpers.accounts import CREDENTIALS_FILE
from helpers.decorators import capture_response
from helpers.notify import notify
from helpers.registry import ServiceRegistry, method_job, register_service
from helpers.requirements import Requirement
from helpers.untrusted import wrap

_READ_MASK = "names,emailAddresses,phoneNumbers"
_PAGE = 10


class Phone(typing.NamedTuple):
    label: str  # "mobile", "work"… — what the model may see
    number: str  # never sent to the AI provider (modules/phone.py)


class Person(typing.NamedTuple):
    name: str
    emails: typing.List[str]
    phones: typing.List[Phone]


def phone_labels(phones: typing.List[Phone]) -> str:
    """"mobile and work" — how a person's numbers are described to the model."""
    labels = [p.label for p in phones]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


@register_service(
    module_name="contacts",
    requires=Requirement(
        files=[CREDENTIALS_FILE],
        pip_modules=["googleapiclient", "google_auth_oauthlib"],
        setup_hint="Open Settings → Google accounts and sign in.",
    ),
)
class Contacts:
    """Google Contacts lookups."""

    def __init__(self) -> None:
        self._warmed: typing.Set[str] = set()

    def search(self, query: str, account: str = "") -> typing.List[Person]:
        from helpers import google_auth

        people = google_auth.service("people", "v1", account)
        key = account or "_primary"
        if key not in self._warmed:
            # Google's contact search answers from a cache it only fills after
            # one empty query; without it the first real search finds nothing.
            for warm in (people.people().searchContacts(query="", readMask=_READ_MASK),
                         people.otherContacts().search(query="", readMask=_READ_MASK)):
                warm.execute()
            self._warmed.add(key)

        found: typing.List[Person] = []
        seen: typing.Set[str] = set()
        for request in (
            people.people().searchContacts(query=query, readMask=_READ_MASK, pageSize=_PAGE),
            people.otherContacts().search(query=query, readMask=_READ_MASK, pageSize=_PAGE),
        ):
            for result in request.execute().get("results", []):
                person = _person(result.get("person", {}))
                identity = (person.emails or [person.name])[0].lower()
                if identity not in seen:
                    seen.add(identity)
                    found.append(person)
        return found

    @capture_response
    @method_job
    def contact(
        self,
        action: typing.Literal["find", "add_number"] = "find",
        name: str = "",
        number: str = "",
        label: str = "mobile",
        account: str = "",
    ) -> str:
        """
        [CONTACTS JOB] Looks someone up in Google Contacts ("what's Tom's number",
        "what's Anna's email"), or saves a phone number for someone ("add Ann's phone
        as …", "save this as Tom's work number"). Phone numbers never reach you: found
        ones are shown to the user directly, and one the user says reaches you as a
        placeholder like [number 1] — pass it as `number` exactly as written.

        Args:
            action (str): "find" (the default) or "add_number".
            name (str): The person's name, or part of it. (required)
            number (str): The number to save, as you were given it. (required for add_number)
            label (str): What kind of number: "mobile" (the default), "work", "home".
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching people with their addresses and which numbers were shown,
                or confirmation of the saved number.
        """
        if not name.strip():
            return "Error: Who is it?"
        if action == "add_number":
            return self._add_number(name.strip(), number.strip(), (label or "mobile").strip().lower(), account)
        return self._find(name, account)

    def _find(self, name: str, account: str) -> str:
        people = self.search(name, account)[:_PAGE]
        if not people:
            return f"No contact matches '{name}'."
        lines, shown = [], []
        for person in people:
            details = list(person.emails)
            if person.phones:
                details.append(f"{phone_labels(person.phones)} number on screen")
                shown.append(
                    f"{person.name or '(no name)'}: "
                    + ", ".join(f"{p.label} {p.number}" for p in person.phones)
                )
            lines.append(f"- {person.name or '(no name)'}: {', '.join(details) or 'no details saved'}")
        if shown:
            # Straight to the user — the bell, the speaker, Telegram — so the
            # numbers never pass through the AI provider.
            notify(shown, kind="info", source="contacts")
        # Names and details in "Other contacts" come from mail other people sent.
        return f"Contacts matching '{name}':\n" + wrap("\n".join(lines), "contacts")

    def _add_number(self, name: str, number: str, label: str, account: str) -> str:
        """Add `number` to the one contact called `name`, or create that contact.
        The reply names the person and the kind of number, never the digits."""
        from helpers import google_auth, private_numbers, undo
        from helpers.config import Config

        if not Config.get("modules.contacts.allow_write", False):
            from helpers.settings import where

            return f"I'm not allowed to change your contacts. Switch on {where('modules.contacts.allow_write')}."
        if not private_numbers.number_in(number):
            return "Error: say the phone number to save."

        people = google_auth.service("people", "v1", account).people()
        # Only "My contacts": an entry under "Other contacts" can't be edited.
        found = people.searchContacts(query=name, readMask="names,phoneNumbers", pageSize=_PAGE).execute()
        matches = [r.get("person", {}) for r in found.get("results", [])]
        names = sorted({_person(m).name for m in matches})
        if len(names) > 1:
            return f"Which {name}: {', '.join(names)}?"

        new_phone = {"value": number, "type": label}
        if not matches:
            created = people.createContact(
                body={"names": [{"givenName": name}], "phoneNumbers": [new_phone]},
                personFields="names",
            ).execute()
            resource = created["resourceName"]
            undo.push(
                f"adding {name} to your contacts",
                lambda: (people.deleteContact(resourceName=resource).execute(), "")[1],
            )
            return f"Added {name} to your contacts with their {label} number."

        person = matches[0]
        resource, who = person["resourceName"], _person(person).name or name
        if any(_same(p.get("value", ""), number) for p in person.get("phoneNumbers", [])):
            return f"{who} already has that number."
        self._set_phones(people, resource, person.get("phoneNumbers", []) + [new_phone])

        def revert() -> str:
            current = people.get(resourceName=resource, personFields="phoneNumbers").execute()
            kept = [p for p in current.get("phoneNumbers", []) if not _same(p.get("value", ""), number)]
            self._set_phones(people, resource, kept)
            return ""

        undo.push(f"adding {who}'s {label} number", revert)
        return f"Saved it as {who}'s {label} number."

    @staticmethod
    def _set_phones(people: typing.Any, resource: str, phones: typing.List[typing.Dict[str, str]]) -> None:
        # The etag makes Google refuse the write if the contact changed meanwhile.
        etag = people.get(resourceName=resource, personFields="phoneNumbers").execute()["etag"]
        people.updateContact(
            resourceName=resource,
            updatePersonFields="phoneNumbers",
            body={"etag": etag, "phoneNumbers": [{"value": p["value"], "type": p.get("type", "")} for p in phones]},
        ).execute()


def _same(a: str, b: str) -> bool:
    """One number however it is written: "+48 600-700-800" is "600700800" too."""
    digits_a, digits_b = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    return bool(digits_a and digits_b) and (digits_a.endswith(digits_b) or digits_b.endswith(digits_a))


def _person(raw: typing.Dict[str, typing.Any]) -> Person:
    names = raw.get("names") or [{}]
    return Person(
        name=names[0].get("displayName", ""),
        emails=[e["value"] for e in raw.get("emailAddresses", []) if e.get("value")],
        phones=[
            Phone((p.get("formattedType") or p.get("type") or "phone").lower(), p["value"])
            for p in raw.get("phoneNumbers", [])
            if p.get("value")
        ],
    )


def resolve_addresses(text: str, account: str = "") -> typing.Tuple[typing.List[str], str]:
    """Turn "Anna, bob@x.com" into addresses. Returns (addresses, problem).

    Exactly one address for a name is used; several, or none, come back as the
    question to ask instead — a guessed recipient is a message sent to the
    wrong person.
    """
    wanted = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
    addresses: typing.List[str] = []
    contacts = ServiceRegistry.get_service_instance("contacts")
    for item in wanted:
        if "@" in item:
            addresses.append(item)
            continue
        if contacts is None:
            return [], f"I need an email address for {item} (switch on Contacts to use names)."
        options = sorted({e for person in contacts.search(item, account) for e in person.emails})
        if len(options) == 1:
            addresses.append(options[0])
        elif options:
            # Entries under "Other contacts" are addresses mail from other
            # people left behind, not ones the user typed in themselves.
            return [], f"Which {item} — {wrap(', '.join(options[:5]), 'contacts')}?"
        else:
            return [], f"I don't have an email address for {item}."
    return addresses, ""
