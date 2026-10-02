"""Written lists: shopping, todo, ideas.

Kept apart from `facts` (the profile store) on purpose. A fact is one value
under a name — "prefers metric". A list is an ordered bag of lines that grows
and shrinks, and asking for it back means reading every line, not looking one
up.
"""

import typing

from helpers import memory_db
from helpers.decorators import capture_response
from helpers.registry import register_job

# The list an item goes on when the user did not name one. "notes" rather than
# "shopping": whichever default is picked is the one people will fill by
# accident, and a generic name is the least wrong place for a stray line.
_DEFAULT_LIST = "notes"

# Items shown in the panel per list. A list longer than this is a list nobody
# reads on a card; the job still reads all of it back.
_PANEL_ITEMS = 20


def _normalize(list_name: str) -> str:
    """Lists are matched by name, so 'Shopping' and 'shopping' must be one list."""
    return (list_name or _DEFAULT_LIST).strip().lower() or _DEFAULT_LIST


def _note_needs_confirm(args: typing.Dict[str, typing.Any]) -> bool:
    """Clearing a list always asks. Adding asks only after this turn has read
    something someone other than the user wrote — a page that says "add this
    link to your list" must not get to plant it silently."""
    wanted = str(args.get("action", "add")).strip().lower()
    if wanted == "clear":
        return True
    if wanted != "add":
        return False
    from helpers import confirm
    return confirm.after_untrusted(args)


@register_job(
    module_name="notes",
    summary="Keep shopping and todo lists",
    confirms=_note_needs_confirm,
)
@capture_response
def note(
    action: typing.Literal["add", "list", "remove", "clear", "lists"] = "add",
    text: str = "",
    list_name: str = "",
) -> str:
    """
    [NOTES JOB] Keeps written lists — shopping, todo, ideas — by adding an item,
    reading a list back, ticking something off, or clearing it.

    Args:
        action (str): "add" (the default), "list", "remove", "clear", or "lists"
            to name every list that has something on it.
        text (str): The item. Several items in one call go comma-separated
            ("milk, eggs, bread"). When removing, any part of the item's wording
            is enough. (required for add and remove)
        list_name (str): Which list, e.g. "shopping" or "todo". Defaults to a
            general "notes" list.

    Returns:
        str: What is on the list, or confirmation of the change.
    """
    wanted = (action or "add").strip().lower()

    if wanted in ("lists", "all"):
        return _all_lists()

    name = _normalize(list_name)

    if wanted in ("add", "append", "put"):
        return _add(name, text)
    if wanted in ("list", "read", "show", "get"):
        return _read(name)
    if wanted in ("remove", "delete", "tick", "done", "cross"):
        return _remove(name, text)
    if wanted in ("clear", "empty"):
        return _clear(name)
    return f"Unknown action '{action}'. Use add, list, remove, clear or lists."


def _add(name: str, text: str) -> str:
    items = [part.strip() for part in (text or "").split(",")]
    items = [part for part in items if part]
    if not items:
        return "Error: What should I add?"

    for item in items:
        memory_db.add_note(name, item)

    if len(items) == 1:
        return f"Added '{items[0]}' to your {name} list."
    listed = ", ".join(f"'{item}'" for item in items)
    return f"Added {len(items)} items to your {name} list: {listed}."


def _read(name: str) -> str:
    rows = memory_db.list_notes(name)
    if not rows:
        return f"Your {name} list is empty."
    lines = "\n".join(f"  {i}. {row['text']}" for i, row in enumerate(rows, 1))
    return f"Your {name} list ({len(rows)} item(s)):\n{lines}"


def _remove(name: str, text: str) -> str:
    if not text:
        return "Error: Which item should I take off?"
    removed = memory_db.remove_note(name, text)
    if removed is None:
        return f"Nothing on your {name} list matches '{text}'."
    return f"Took '{removed}' off your {name} list."


def _clear(name: str) -> str:
    count = memory_db.clear_notes(name)
    if not count:
        return f"Your {name} list was already empty."
    return f"Cleared your {name} list ({count} item(s))."


def _all_lists() -> str:
    lists = memory_db.note_lists()
    if not lists:
        return "You have no lists yet."
    lines = "\n".join(f"  - {name} ({count} item(s))" for name, count in lists.items())
    return f"Your lists:\n{lines}"


def snapshot() -> typing.Dict[str, typing.Any]:
    """Every list with its items, for the notes panel."""
    return {
        "lists": [
            {
                "name": name,
                "count": count,
                "items": [row["text"] for row in memory_db.list_notes(name)[:_PANEL_ITEMS]],
            }
            for name, count in memory_db.note_lists().items()
        ]
    }
