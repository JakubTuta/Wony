"""Everything Wony can find about one person, gathered when asked.

Nothing new is stored: their contact entry, the facts the user told Wony, the
latest mail and meetings with them, and past conversations that name them are
already there — "what's going on with Anna" just has to look in all of them.
Each part is allowed to come back empty; one service being down must not lose
the rest.
"""
import typing

from helpers.logger import logger
from helpers.registry import ServiceRegistry
from helpers.untrusted import wrap

_MAIL_DAYS = 30
_MAIL_HITS = 3
_MEETING_DAYS = 30
_TALK_HITS = 3


def about(name: str) -> str:
    """A briefing on `name`, or a sentence saying nothing was found."""
    name = name.strip()
    if not name:
        return "Error: Who should I look up?"

    addresses: typing.List[str] = []
    sections: typing.List[str] = []
    for part in (_contact, _facts, _mail, _meetings, _talks):
        try:
            text = part(name, addresses)
        except Exception as e:
            logger.log_error(str(e), f"people.{part.__name__}")
            continue
        if text:
            sections.append(text)
    if not sections:
        return f"I have nothing on {name}."
    return f"About {name}:\n\n" + "\n\n".join(sections)


def recent_mail(people: typing.List[str], days: int = _MAIL_DAYS, limit: int = _MAIL_HITS) -> str:
    """Subjects of the latest mail to or from any of `people`, one line. Not
    fenced: the caller does that, once (the meeting prep in helpers/triggers.py
    fences its whole announcement)."""
    from helpers.config import Config

    gmail = ServiceRegistry.get_service_instance("gmail")
    if gmail is None or not people or not Config.is_module_enabled("gmail"):
        return ""
    # Gmail's own OR syntax in one query: one round trip for everyone.
    who = " OR ".join(f"from:{person} OR to:{person}" for person in people)
    try:
        messages = gmail.search_messages(f"({who}) newer_than:{days}d", max_results=limit, folder="anywhere")
    except Exception:
        return ""
    if not messages:
        return ""
    subjects = ", ".join(f"'{m.subject.strip() or '(no subject)'}'" for m in messages)
    return f"Recent mail with them: {subjects}."


def _contact(name: str, addresses: typing.List[str]) -> str:
    contacts = ServiceRegistry.get_service_instance("contacts")
    if contacts is None:
        return ""
    found = contacts.search(name)[:3]
    if not found:
        return ""
    from modules.contacts import phone_labels

    # The first match is the one the other parts look up by address.
    addresses.extend(found[0].emails[:2])
    lines = []
    for person in found:
        # Numbers stay on this computer (modules/phone.py); their kinds do not.
        details = person.emails + ([f"{phone_labels(person.phones)} number saved"] if person.phones else [])
        lines.append(f"- {person.name or '(no name)'}: {', '.join(details) or 'no details saved'}")
    return "Contact: " + wrap("\n".join(lines), "contacts")


def _facts(name: str, _addresses: typing.List[str]) -> str:
    from helpers.memory_db import all_facts_with_source

    needle = name.lower()
    rows = [r for r in all_facts_with_source() if needle in r["key"].lower() or needle in str(r["value"]).lower()]
    if not rows:
        return ""
    return "What you've told me: " + "; ".join(str(r["value"]) for r in rows)


def _mail(name: str, addresses: typing.List[str]) -> str:
    line = recent_mail(addresses or [name])
    return wrap(line, "email subjects") if line else ""


def _meetings(name: str, addresses: typing.List[str]) -> str:
    from helpers.config import Config

    calendar = ServiceRegistry.get_service_instance("calendar")
    if calendar is None or not Config.is_module_enabled("calendar"):
        return ""
    events = calendar.events_with(addresses[0] if addresses else name, days=_MEETING_DAYS)
    if not events:
        return ""
    lines = []
    for event in events:
        start = event.get("start", {})
        when = (start.get("dateTime") or start.get("date") or "")[:16].replace("T", " ")
        lines.append(f"- {when} {event.get('summary', 'Untitled event')}")
    return "Meetings with them (a month either side): " + wrap("\n".join(lines), "calendar")


def _talks(name: str, _addresses: typing.List[str]) -> str:
    from helpers.memory_db import search_turns

    turns = search_turns(name, days_back=365, limit=_TALK_HITS)
    if not turns:
        return ""
    from helpers.private_numbers import hide

    lines = [f"- {t['ts'][:10]}: you said \"{t['user_text'][:120]}\"" for t in turns]
    return "We talked about them:\n" + hide("\n".join(lines))
