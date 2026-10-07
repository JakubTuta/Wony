"""Named sequences of steps, written in the user's own words.

A routine is not code. It is a sentence — "turn off the lights, tell me
tomorrow's first meeting, set an alarm for seven" — stored under a name and
handed back to the agent when the name is said. That makes every registered job
composable without a single line of per-routine code, and lets the user rewrite
their own morning briefing by talking to it.

Running one deliberately does *not* start a nested turn: `routine(action="run")`
is itself called from inside an agent turn that already holds `agent_lock`, so
calling `run_turn` here would deadlock. It returns the steps as instructions for
the turn already in progress, which then calls the tools itself. Jobs that
declare `confirms` still confirm inside a routine — the gate lives in the agent
loop, below this.

Security: a routine is a stored instruction that runs later, possibly while
nobody is watching. It may only ever be written by the user, never from content
Wony read — an email or a web page that could get itself saved as a routine
would be a persistent foothold. That is why `add` and `remove` confirm.
"""

import typing

from helpers.decorators import capture_response
from helpers.registry import register_job

# The briefing that used to be a hardcoded `greeting` job. Seeded once, then it
# belongs to the user: it is a row like any other, and "add my shopping list to
# the briefing" rewrites it.
BRIEFING = "briefing"

_DEFAULT_ROUTINES: typing.Dict[str, str] = {
    BRIEFING: (
        "Greet me by name for the time of day and tell me the date and time. "
        "Then the weather here, then my unread email, then today's meetings. "
        "Skip anything you have no tool for. Keep it to a few short lines."
    ),
}

# A routine's steps ride into the model as instructions, so their length is a
# per-run token cost and a way to smuggle in a wall of text. A routine is a
# handful of sentences.
MAX_STEPS_CHARS = 600


def _seed() -> None:
    """Create the default routines once, if the user has none of them.

    Only when absent: a user who deleted the briefing on purpose must not get it
    back on the next restart.
    """
    from helpers.memory_db import get_kv, save_routine, set_kv

    if get_kv("routines_seeded") == "1":
        return
    for name, steps in _DEFAULT_ROUTINES.items():
        save_routine(name, steps)
    set_kv("routines_seeded", "1")


def _normalize(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


@register_job(
    module_name="routines",
    summary="Named sequences of steps you can run by name",
    confirms={"add", "remove"},
)
@capture_response
def routine(
    action: typing.Literal["run", "list", "add", "remove"] = "run",
    name: str = "",
    steps: str = "",
) -> str:
    """
    [ROUTINE JOB] Runs one of the user's named routines, or manages the list of them.
    A routine is a saved set of steps in plain words — "good night" might turn off the
    lights, read tomorrow's first meeting and set an alarm. Running one returns the
    steps: carry them out yourself with the other tools, then report back once.

    Args:
        action (str): "run" (the default), "list", "add" or "remove".
        name (str): Which routine, e.g. "briefing" or "good night". (required except for list)
        steps (str): What the routine should do, in plain words, when adding one.
            Replaces the steps of a routine that already has this name. (required for add)

    Returns:
        str: The steps to carry out, the list of routines, or confirmation of a change.
    """
    from helpers.memory_db import delete_routine

    _seed()
    wanted = (action or "run").strip().lower()
    key = _normalize(name)

    if wanted == "list":
        return _list()

    if wanted == "add":
        return _add(key, name, steps)

    if wanted == "remove":
        if not key:
            return "Error: which routine should I remove?"
        if delete_routine(key):
            return f"Removed the '{key}' routine."
        return f"There is no '{key}' routine. {_names_hint()}"

    if wanted != "run":
        return f"Unknown action '{action}'. Use run, list, add or remove."

    if not key:
        return f"Error: which routine should I run? {_names_hint()}"

    return instructions(key) or f"There is no '{key}' routine. {_names_hint()}"


def instructions(name: str) -> typing.Optional[str]:
    """The routine's steps as an instruction for the model, or None if there is
    no such routine. A timer runs a routine by handing this to a turn of its own."""
    from helpers.memory_db import get_routine

    _seed()
    key = _normalize(name)
    if not key:
        return None
    found = get_routine(key) or _closest(key)
    if found is None:
        return None
    # Framed as the user's own standing instruction, because that is what it is
    # — and so a routine cannot be mistaken for a fresh request from elsewhere.
    return (
        f"The user's saved '{found['name']}' routine says: {found['steps']}\n"
        "Do that now using your tools, then give one short answer covering all of it."
    )


def _add(key: str, raw_name: str, steps: str) -> str:
    from helpers.memory_db import get_routine, save_routine

    if not key:
        return "Error: what should the routine be called?"
    if not steps.strip():
        return "Error: say what the routine should do."
    if len(steps) > MAX_STEPS_CHARS:
        return (
            f"That is too long for a routine ({len(steps)} characters, "
            f"limit {MAX_STEPS_CHARS}). Shorten it to the steps themselves."
        )

    existed = get_routine(key) is not None
    save_routine(key, steps.strip())
    verb = "Updated" if existed else "Saved"
    return f"{verb} the '{raw_name.strip() or key}' routine: {steps.strip()}"


def _list() -> str:
    from helpers.memory_db import all_routines

    rows = all_routines()
    if not rows:
        return "There are no routines yet."
    lines = ["Saved routines:"]
    for row in rows:
        lines.append(f"  - {row['name']}: {row['steps']}")
    return "\n".join(lines)


def _closest(key: str) -> typing.Optional[typing.Dict]:
    """A routine whose name contains what was asked for, when exactly one does.

    "run my good night one" and "good night routine" should both find the
    routine called "good night"; two candidates mean the caller has to be clearer.
    """
    from helpers.memory_db import all_routines

    matches = [row for row in all_routines() if key in row["name"] or row["name"] in key]
    return matches[0] if len(matches) == 1 else None


def _names_hint() -> str:
    from helpers.memory_db import all_routines

    names = [row["name"] for row in all_routines()]
    return f"Known routines: {', '.join(names)}." if names else "There are none yet."


def snapshot() -> typing.Dict[str, typing.Any]:
    """Routines as data, for a UI that lists them as buttons.

    Not a job: `routine(action="list")` writes a sentence, and a tile per routine
    cannot be recovered from a sentence.
    """
    from helpers.memory_db import all_routines

    _seed()
    return {"routines": [{"name": r["name"], "steps": r["steps"]} for r in all_routines()]}
