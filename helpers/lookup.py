"""Keyword search for what Wony says about itself, shared by its settings
(helpers/settings.py) and its guide (helpers/guide.py) so a word finds the same
things in both."""
import math
import re
import typing

# Words of a question that say nothing about its subject. The assistant's own
# name is added in keywords(): it is in half the headings.
_FILLER = {
    "how", "what", "whats", "when", "where", "why", "which", "who", "does", "can",
    "could", "should", "would", "the", "and", "for", "you", "your", "this", "that",
    "with", "about", "tell", "please", "wony", "not", "are", "was", "has", "have",
    "any", "but", "all", "its", "let", "get",
}

# The job is reachable from the web API with any argument; a question is a
# sentence, so more than this is not one and must not become minutes of matching.
_MAX_QUERY_CHARS = 300
_MAX_KEYWORDS = 8

_TITLE_BONUS = 2  # a word in the title is worth this many in the text
_RELEVANT = 0.5  # an entry must score this much of the best one, or it is noise


def keywords(text: typing.Optional[str]) -> typing.List[str]:
    """What a question is about: distinct lower-case words, without the short
    ones ("my", "do") that match nearly everything or the filler of a question."""
    from helpers.config import Config

    skip = _FILLER | set(re.findall(r"[a-z0-9]+", str(Config.get("assistant.name", "")).lower()))
    words = re.findall(r"[a-z0-9]+", (text or "")[:_MAX_QUERY_CHARS].lower())
    return list(dict.fromkeys(word for word in words if len(word) >= 3 and word not in skip))[:_MAX_KEYWORDS]


def has(word: str, text: str) -> bool:
    """Whether a word of the lower-case `text` starts with `word`: "install"
    finds "installing", but "set" does not find "reset"."""
    return re.search(r"\b" + re.escape(word), text) is not None


def rank(words: typing.List[str], entries: typing.List[typing.Tuple[str, str]]) -> typing.List[int]:
    """Indexes of the (text, title) entries that best match the words, best
    first; none when no entry has any. All lower-case.

    A word found in few entries says more about where the answer is than one
    found in many ("set" is everywhere, "weather" in a handful). Having a word
    counts, not how often: a paragraph that says "set" three times is not about
    the thing being set up.
    """
    weight = {}
    for word in words:
        found = sum(has(word, text) or has(word, title) for text, title in entries)
        weight[word] = math.log(1 + len(entries) / found) if found else 0.0

    scored = []
    for index, (text, title) in enumerate(entries):
        score = sum(weight[word] * (has(word, text) + _TITLE_BONUS * has(word, title)) for word in words)
        if score:
            scored.append((-score, index))
    if not scored:
        return []
    scored.sort()
    best = -scored[0][0]
    return [index for score, index in scored if -score >= best * _RELEVANT]
