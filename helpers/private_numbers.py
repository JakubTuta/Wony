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

# Digits, optionally led by + or a bracket, with the spaces, dashes, dots and
# brackets people write numbers with — the Unicode ones pasted text brings too.
_SEPARATORS = r" \u00a0\u2009\u202f\-\u2010-\u2015.()"
_CANDIDATE = re.compile(rf"(?<![\w+(])[(+]*\d[\d{_SEPARATORS}]{{5,}}\d(?!\w)")
_MIN_DIGITS = 7
# E.164's longest. Only for telling one phone number apart (number_in): hiding
# has no upper bound, since two numbers side by side run past it.
_MAX_PHONE_DIGITS = 15

# Inside a run of digits these stay: anything with dots between digits (a dotted
# date or time, an amount, an IP address \u2014 nobody writes a phone number that
# way), and a date written with dashes that stands on its own: "2026-10-17",
# but not the "12-03-45" of "12-03-45-67-89".
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DATE = rf"\d{{4}}-{_MONTH}-{_DAY}|{_DAY}-{_MONTH}-(?:\d{{4}}|\d{{2}})"
_NOT_A_NUMBER = re.compile(rf"((?<![\d\-.])(?:{_DATE})(?![-.]?\d)|(?<![\d.])\d+(?:\.\d+)+)")
_NUMBER = re.compile(r"[(+]*\d(?:.*\d)?", re.DOTALL)

# Next to a currency it is an amount: "1 250 000 z\u0142", "$ 1 250 000", "1 250 000,50 PLN".
_CURRENCY = r"z\u0142|[$\u20ac\u00a3\u00a5\u20b9\u20bd]|\b(?:pln|usd|eur|gbp|chf|czk|sek|nok|dkk|jpy|cad|aud)\b"
_PRICE_AFTER = re.compile(rf"(?:,\d{{1,2}})?\s?(?:{_CURRENCY})", re.IGNORECASE)
_PRICE_BEFORE = re.compile(rf"(?:{_CURRENCY})\s?$", re.IGNORECASE)

_TOKEN = re.compile(r"\[number (\d+)\]")
_HIDDEN = "[a number]"

_turn: typing.Dict[str, str] = {}  # "[number 1]" -> "+48 600 700 800"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _each_number(text: str, replace: typing.Callable[[str], str]) -> str:
    """`text` with replace(number) put in for every number in it."""
    def run(match: "re.Match[str]") -> str:
        before = match.string[max(0, match.start() - 5):match.start()]
        if _PRICE_AFTER.match(match.string, match.end()) or _PRICE_BEFORE.search(before):
            return match.group(0)
        # split() keeps the dates and dotted parts at the odd indexes, untouched.
        pieces = _NOT_A_NUMBER.split(match.group(0))
        for i in range(0, len(pieces), 2):
            found = _NUMBER.search(pieces[i])
            if found and len(_digits(found.group(0))) >= _MIN_DIGITS:
                pieces[i] = pieces[i][:found.start()] + replace(found.group(0)) + pieces[i][found.end():]
        return "".join(pieces)

    return _CANDIDATE.sub(run, text)


def begin() -> None:
    _turn.clear()


def end() -> None:
    _turn.clear()


def mask(text: str) -> str:
    """The user's words with each number swapped for this turn's placeholder."""
    def swap(number: str) -> str:
        for token, known in _turn.items():
            if _digits(known) == _digits(number):
                return token
        token = f"[number {len(_turn) + 1}]"
        _turn[token] = number
        return token

    return _each_number(text, swap)


def hide(text: str) -> str:
    """Any number in an earlier turn's text, for history going back to the model."""
    return _each_number(text, lambda _number: _HIDDEN)


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

    def swap(number: str) -> str:
        for token, known in _turn.items():
            if _digits(known) == _digits(number):
                return token
        return number

    return _each_number(text, swap)


def number_in(text: str) -> str:
    """`text` as a phone number when that is all it is, else ""."""
    text = text.strip()
    if not _CANDIDATE.fullmatch(text) or _NOT_A_NUMBER.search(text):
        return ""
    return text if _MIN_DIGITS <= len(_digits(text)) <= _MAX_PHONE_DIGITS else ""
