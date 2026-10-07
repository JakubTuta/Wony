"""Phone numbers the user says never reach the AI provider.

"Add Ann's phone as 600 700 800" has the number in the user's own sentence. It
goes to the model as "[number 1]"; the model hands that placeholder to a job,
and the digits are put back here, on this computer, before the job runs. Older
turns go out with "[a number]" in place of any number at all.

The placeholders of one turn live here while it runs (begin/end, under
agent_lock); jobs of that turn on worker threads read the same table.
"""
import re
import typing

# Seven to fifteen digits, optionally led by +, with the spaces, dashes, dots and
# brackets people write numbers with. Dates are told apart below.
_CANDIDATE = re.compile(r"(?<![\w+])\+?\(?\d[\d \-.()]{5,}\d(?!\w)")
_DATE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}")
_TOKEN = re.compile(r"\[number (\d+)\]")
_HIDDEN = "[a number]"

_turn: typing.Dict[str, str] = {}  # "[number 1]" -> "+48 600 700 800"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _is_number(candidate: str) -> bool:
    return 7 <= len(_digits(candidate)) <= 15 and not _DATE.fullmatch(candidate.strip())


def begin() -> None:
    _turn.clear()


def end() -> None:
    _turn.clear()


def mask(text: str) -> str:
    """The user's words with each number swapped for this turn's placeholder."""
    def swap(match: "re.Match[str]") -> str:
        number = match.group(0).strip()
        if not _is_number(number):
            return match.group(0)
        for token, known in _turn.items():
            if _digits(known) == _digits(number):
                return token
        token = f"[number {len(_turn) + 1}]"
        _turn[token] = number
        return token

    return _CANDIDATE.sub(swap, text)


def hide(text: str) -> str:
    """Any number in an earlier turn's text, for history going back to the model."""
    return _CANDIDATE.sub(lambda m: _HIDDEN if _is_number(m.group(0)) else m.group(0), text)


def reveal(value: typing.Any) -> typing.Any:
    """Placeholders back to digits — job arguments, and the answer the user sees."""
    if isinstance(value, str):
        return _TOKEN.sub(lambda m: _turn.get(m.group(0), m.group(0)), value)
    if isinstance(value, dict):
        return {key: reveal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [reveal(item) for item in value]
    return value


def conceal(text: str) -> str:
    """A job's result with this turn's numbers placeholdered again, so a job that
    repeats its argument back ("Saved 600 700 800") does not undo the masking."""
    if not _turn:
        return text

    def swap(match: "re.Match[str]") -> str:
        for token, known in _turn.items():
            if _digits(known) == _digits(match.group(0)):
                return token
        return match.group(0)

    return _CANDIDATE.sub(swap, text)


def number_in(text: str) -> str:
    """`text` as a phone number when that is all it is, else ""."""
    text = text.strip()
    match = _CANDIDATE.fullmatch(text)
    return text if match and _is_number(text) else ""
