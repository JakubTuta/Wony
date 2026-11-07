"""Email and calendar contents the AI provider never sees.

With `ai.hide_mail_and_calendar` on, the model still picks the Gmail or Calendar
job and its arguments, but the result goes to the user as it is and the model
gets note() in its place (helpers/agent.py). The kept turn has those results
fenced (fence), so history, the summary, recall and learning leave them out
(strip) while the chat window shows them again (show).
"""
import re
import typing

_MODULES = ("gmail", "calendar")

_OPEN = "[[private]]"
_CLOSE = "[[/private]]"
_FENCED = re.compile(re.escape(_OPEN) + ".*?" + re.escape(_CLOSE), re.DOTALL)
_LEFT_OUT = "(Email or calendar contents shown to the user; kept from you by their privacy setting.)"


def on() -> bool:
    from helpers.config import Config

    return bool(Config.get("ai.hide_mail_and_calendar", False))


def covers(module: str) -> bool:
    """Whether what `module` reads is kept from the model right now."""
    return module in _MODULES and on()


def withheld(job_name: str) -> bool:
    """Whether this job's result goes to the user only."""
    from helpers.registry import ServiceRegistry

    return covers(ServiceRegistry.get_job_modules().get(job_name, ""))


def note() -> str:
    """What the model reads where a withheld result would have been."""
    from helpers.settings import where

    return (
        "[Shown to the user as is. Their privacy setting keeps email and calendar contents"
        " from you: do not describe, repeat or guess them. If their request needed what it"
        f" says, tell them you can't see it while {where('ai.hide_mail_and_calendar')} is on.]"
    )


def hold(text: str) -> str:
    return f"{_OPEN}{text}{_CLOSE}" if text else text


def fence(text: str, calls: typing.List[typing.Dict[str, typing.Any]]) -> str:
    """`text` with each withheld result in it fenced, for keeping. A result that
    is not found fences the whole text: a gap in the history beats a leak."""
    for result in dict.fromkeys(c["result"] for c in calls if c.get("private") and c.get("result")):
        if result not in text:
            return hold(text)
        text = text.replace(result, hold(result))
    return text


def strip(text: str) -> str:
    """A kept turn as the model may read it."""
    return _FENCED.sub(_LEFT_OUT, text)


def show(text: str) -> str:
    """A kept turn as the user reads it."""
    return text.replace(_OPEN, "").replace(_CLOSE, "")
