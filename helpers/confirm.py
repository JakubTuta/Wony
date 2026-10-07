"""
Second-thought gate for jobs that change something the user cares about.

The screen has always confirmed these before running them, and still does — a
tap there passes the dialog and runs the job directly. Asking for the same thing
in words never had a gate at all, and that is the path where "delete the email
from Anna" and "delete the email from Hannah" are one typo apart. This gate sits
in the agent loop, so it covers every sentence, wherever it was typed.

How it works: the first time the agent tries to run a confirming job, the call
is not executed. Instead the model is told to ask the user, and the exact
(job, arguments) pair is armed. The user answers, the model calls the job again
in a *later* turn, the armed pair matches, and it runs.

Requiring a later turn is the whole point: a model that simply retried inside
the same turn would defeat the gate, and models do exactly that. It is not in
the tool schema for the same reason — a flag the model sets itself is not a
confirmation.
"""

import hashlib
import json
import threading
import time
import typing

# How long an armed confirmation stays good. Long enough for "are you sure?" →
# "yes" with a pause in between, short enough that yesterday's half-finished
# delete cannot be completed by an unrelated request.
_ARM_TTL_SECONDS = 300.0

_lock = threading.Lock()


class _Armed(typing.NamedTuple):
    turn: int
    at: float
    job: str
    args: typing.Dict[str, typing.Any]


# fingerprint -> the armed call
_armed: typing.Dict[str, _Armed] = {}
_turn_counter = 0


def begin_turn() -> int:
    """Advance the turn counter. Called once per agent turn, under agent_lock."""
    global _turn_counter
    with _lock:
        _turn_counter += 1
        return _turn_counter


def normalize(job_name: str, args: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    """The call as it will actually run: blanks and values equal to the job's
    defaults dropped, strings trimmed. The "yes" turn re-sends the call, and a
    model that adds cc="" or a trailing space must not get asked all over again."""
    import inspect

    from helpers.registry import ServiceRegistry

    func = ServiceRegistry.get_all_jobs().get(job_name)
    try:
        params = inspect.signature(func).parameters if func else {}
    except (TypeError, ValueError):
        params = {}
    out: typing.Dict[str, typing.Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            continue
        param = params.get(key)
        if param is not None and param.default is not inspect.Parameter.empty and value == param.default:
            continue
        out[key] = value
    return out


def _fingerprint(job_name: str, args: typing.Dict[str, typing.Any]) -> str:
    # The arguments are part of the identity: confirming "delete mail from Anna"
    # must not also confirm "delete everything".
    payload = json.dumps({"job": job_name, "args": normalize(job_name, args)}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _applies(declared: typing.Any, args: typing.Dict[str, typing.Any]) -> bool:
    """Whether this particular call needs confirming.

    `confirms=True` covers every call. A collection covers only the listed
    values of the job's `action` argument, so a merged job whose default action
    only reads — listing drafts, listing accounts — does not make the user
    confirm a question. A callable decides from the arguments itself.
    """
    if declared is True:
        return True
    if callable(declared):
        return bool(declared(args))
    if not declared:
        return False
    action = str(args.get("action", "")).strip().lower()
    return action in {str(value).lower() for value in declared}


def check(job_name: str, args: typing.Dict[str, typing.Any]) -> typing.Optional[str]:
    """Return None to let the call through, or the message to hand the model.

    Consumes the armed confirmation when it matches, so one "yes" authorises
    one action.
    """
    from helpers.registry import ServiceRegistry

    if not _applies(ServiceRegistry.get_job_confirms().get(job_name), args):
        return None

    from helpers import turn_context

    if not turn_context.user_present():
        # A trigger or scheduled action nobody is watching cannot be the one
        # saying "yes" — and arming here would let a later, real user turn
        # that happens to make the same call spend a confirmation nobody gave.
        return f"NOT DONE — {job_name} needs the user present to confirm. Do not call it."

    key = _fingerprint(job_name, args)
    now = time.monotonic()

    with _lock:
        current_turn = _turn_counter
        armed = _armed.get(key)
        _drop_stale(now)

        if armed is not None:
            if now - armed.at <= _ARM_TTL_SECONDS and current_turn > armed.turn:
                _armed.pop(key, None)
                return None

        _armed[key] = _Armed(current_turn, now, job_name, normalize(job_name, args))

    return (
        f"NOT DONE — {job_name} needs the user's go-ahead first. "
        "Tell them exactly what it will do and ask them to confirm. "
        "If they say yes, call it again with the same arguments."
    )


def after_untrusted(args: typing.Dict[str, typing.Any]) -> bool:
    """A `confirms=` predicate: true once this turn has read text someone
    other than the user wrote (helpers/untrusted.py). `args` is unused — the
    risk lives in the turn having read something, not in which call it is —
    but the signature matches every other confirms callable."""
    from helpers import turn_context

    return turn_context.untrusted_read()


def _drop_stale(now: float) -> None:
    for stale_key, armed in list(_armed.items()):
        if now - armed.at > _ARM_TTL_SECONDS:
            _armed.pop(stale_key, None)


def armed_jobs() -> typing.List[str]:
    with _lock:
        return [armed.job for armed in _armed.values()]


def take_previous_turn() -> typing.List[_Armed]:
    """Every call armed in the turn just before this one, in the order armed —
    what a bare "yes" or "no" is answering. Removed either way."""
    with _lock:
        _drop_stale(time.monotonic())
        keys = [key for key, armed in _armed.items() if armed.turn == _turn_counter - 1]
        return [_armed.pop(key) for key in keys]


def disarm(job_name: str, args: typing.Dict[str, typing.Any]) -> bool:
    """Spend the armed confirmation for this call, if there is one. The web
    page's Confirm button runs the call itself — a "yes" typed afterwards must
    not run it a second time."""
    with _lock:
        return _armed.pop(_fingerprint(job_name, args), None) is not None


def reset() -> None:
    """Drop every armed confirmation (tests, and 'stop everything')."""
    with _lock:
        _armed.clear()
