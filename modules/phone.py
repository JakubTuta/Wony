"""Phone calls from the user's own phone, set up from the PC.

Windows' Phone Link pairs the phone over Bluetooth and opens tel: links. Wony
looks the number up and hands it to Phone Link; the user presses Call. Wony
never presses it and never reads the screen to find it.

The number never reaches the AI provider. The model names a person and which of
their numbers; the digits are looked up here, and only their kind ("mobile")
goes back. A number the user dictates reaches the model as a placeholder
(helpers/private_numbers.py).
"""
import os
import re
import sys
import typing

from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, register_job
from helpers.requirements import Requirement

# What this needs, for every reply that finds one of them missing.
NEEDS = (
    "Calls need two things: a Google account signed in with Contacts switched on, "
    "where Wony finds the numbers (an Android phone keeps its contacts there), and "
    "Phone Link with your phone connected, set as the app for TEL links in Windows "
    "Settings → Apps → Default apps."
)


class _Target(typing.NamedTuple):
    who: str  # what to say back: "Tom Nowak"
    label: str  # "mobile"
    number: str


def _resolve(name: str, which: str = "") -> typing.Tuple[typing.Optional[_Target], str]:
    """(the number to call, "") or (None, what to tell the model instead).
    The message names people and kinds of number, never the digits."""
    from helpers import private_numbers

    name = name.strip()
    if not name:
        return None, "Error: Who should I call?"
    dictated = private_numbers.number_in(name)
    if dictated:
        return _Target("the number you said", "", dictated), ""

    contacts = ServiceRegistry.get_service_instance("contacts")
    if contacts is None:
        return None, f"I can't look up numbers. {NEEDS}"
    people = [person for person in contacts.search(name) if person.phones]
    if not people:
        return None, f"I have no phone number for {name} in your Google Contacts."
    if len({person.name for person in people}) > 1:
        return None, f"Which {name}: {', '.join(sorted({p.name for p in people}))}?"

    person = people[0]
    from modules.contacts import phone_labels

    phones = person.phones
    if which.strip():
        phones = [p for p in phones if which.strip().lower() in p.label]
        if not phones:
            return None, f"{person.name} has no {which} number — only {phone_labels(person.phones)}."
    if len(phones) > 1:
        return None, f"{person.name} has {phone_labels(phones)} numbers. Which one?"
    return _Target(person.name, phones[0].label, phones[0].number), ""


def _tel_handler() -> str:
    """The app Windows opens tel: links with, or "" when nobody picked one —
    then Windows would ask which app to use instead of opening Phone Link."""
    if sys.platform != "win32":
        return ""
    import winreg

    key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\tel\UserChoice"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return str(winreg.QueryValueEx(handle, "ProgId")[0])
    except OSError:
        return ""


@register_job(
    module_name="phone",
    requires=Requirement(
        check=lambda: sys.platform == "win32",
        setup_hint=NEEDS,
    ),
)
@capture_response
def call_person(name: str, which: str = "") -> str:
    """
    [PHONE JOB] Gets a call to someone ready on the user's own phone: Phone Link opens
    on this PC with their number filled in, and the user presses Call. Pass the person
    as the user named them; their number is looked up here and never shown to you.
    When they have several numbers you are told which kinds: ask the user, then call
    again with `which`.

    Args:
        name (str): Who to call, as the user said it, e.g. "Tom", or the number the
            user dictated, exactly as you were given it. (required)
        which (str): Which of their numbers, when they have several, e.g. "mobile".

    Returns:
        str: That the number is ready in Phone Link, or what is missing.
    """
    from helpers import turn_context

    if turn_context.user_present() and not turn_context.at_machine():
        return "Calls go through Phone Link on the computer, so I can only set one up when you're at it."

    target, problem = _resolve(name, which)
    if target is None:
        return problem
    if not _tel_handler():
        return f"Windows doesn't know which app makes calls yet. {NEEDS} Then ask me again."

    os.startfile("tel:" + re.sub(r"[^\d+]", "", target.number))  # type: ignore[attr-defined]
    whose = f"{target.who}'s {target.label} number" if target.label else target.who
    return f"Phone Link is open with {whose}. Press Call when you're ready."
