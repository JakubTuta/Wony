"""Google Contacts: "what's Tom's number", and turning "email Anna" into an
address. Also searches "Other contacts" — the people Gmail remembers because
you wrote to them — since that is where most addresses actually live.
"""
import typing

from helpers.accounts import CREDENTIALS_FILE
from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, method_job, register_service
from helpers.requirements import Requirement
from helpers.untrusted import wrap

_READ_MASK = "names,emailAddresses,phoneNumbers"
_PAGE = 10


class Person(typing.NamedTuple):
    name: str
    emails: typing.List[str]
    phones: typing.List[str]


@register_service(
    module_name="contacts",
    requires=Requirement(
        files=[CREDENTIALS_FILE],
        pip_modules=["googleapiclient", "google_auth_oauthlib"],
        setup_hint="Run: python setup.py configure — it sets up Google sign-in.",
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
    def find_contact(self, name: str, account: str = "") -> str:
        """
        [CONTACTS JOB] Looks someone up in Google Contacts: their email addresses and
        phone numbers. "What's Tom's number", "what's Anna's email".

        Args:
            name (str): The person's name, or part of it. (required)
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching people with their addresses and numbers.
        """
        if not name.strip():
            return "Error: Who should I look up?"
        people = self.search(name, account)
        if not people:
            return f"No contact matches '{name}'."
        lines = []
        for person in people[:_PAGE]:
            details = person.emails + person.phones
            lines.append(f"- {person.name or '(no name)'}: {', '.join(details) or 'no details saved'}")
        # Names and details in "Other contacts" come from mail other people sent.
        return f"Contacts matching '{name}':\n" + wrap("\n".join(lines), "contacts")


def _person(raw: typing.Dict[str, typing.Any]) -> Person:
    names = raw.get("names") or [{}]
    return Person(
        name=names[0].get("displayName", ""),
        emails=[e["value"] for e in raw.get("emailAddresses", []) if e.get("value")],
        phones=[p["value"] for p in raw.get("phoneNumbers", []) if p.get("value")],
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
