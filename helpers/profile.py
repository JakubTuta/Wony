import typing

_seeded: bool = False

# as_text() lands in every system prompt, so it cannot grow without bound.
# Guessed and older facts past this are still stored and reachable through
# recall — they just stop riding along on every request.
_MAX_PROMPT_FACTS = 40
_MAX_PROMPT_FACT_CHARS = 200


def _seed_from_config() -> None:
    global _seeded
    if _seeded:
        return
    _seeded = True
    from helpers.memory_db import all_facts, import_facts_from_dict
    if all_facts():
        return
    try:
        from helpers.config import Config
        data: typing.Dict[str, str] = {}
        name = Config.get("assistant.owner_name")
        if name and name != "User":
            data["owner_name"] = name
        if data:
            import_facts_from_dict(data)
    except Exception:
        pass


class Profile:
    """Persistent personalization store backed by the SQLite facts table in wony.db."""

    @classmethod
    def get(cls, key: str, default: typing.Optional[str] = None) -> typing.Optional[str]:
        _seed_from_config()
        from helpers.memory_db import get_fact
        value = get_fact(key)
        return value if value is not None else default

    @classmethod
    def set(cls, key: str, value: str, source: str = "") -> None:
        """Store a fact. source="auto" marks one helpers/learn.py worked out
        rather than one the user asked to keep."""
        from helpers.memory_db import set_fact
        set_fact(key, value, source)
        try:
            from helpers import semantic
            if semantic.is_available():
                semantic.store_fact(key, value)
        except Exception:
            pass

    @classmethod
    def remove(cls, key: str) -> bool:
        from helpers.memory_db import remove_fact
        removed = remove_fact(key)
        if removed:
            try:
                from helpers import semantic
                if semantic.is_available():
                    semantic.remove_fact(key)
            except Exception:
                pass
        return removed

    @classmethod
    def all(cls) -> typing.Dict[str, str]:
        _seed_from_config()
        from helpers.memory_db import all_facts
        return all_facts()

    @classmethod
    def as_text(cls) -> str:
        """The facts that ride along in every request (the cached half of the prompt)."""
        kept, rest = _split()
        if not kept:
            return ""
        text = "Known user facts: " + "; ".join(_line(r) for r in sorted(kept, key=lambda r: r["key"])) + "."
        if rest:
            text += f" ({len(rest)} more — the ones that matter to a request are added to it.)"
        return text

    @classmethod
    def relevant(cls, request: str) -> str:
        """Facts left out of as_text() that this request is about, or ""."""
        _, rest = _split()
        if not rest or not request.strip():
            return ""
        picked = [rest[i] for i in _rank(request, rest)[:_MAX_RELEVANT_FACTS]]
        if not picked:
            return ""
        return "Also relevant from what you know about the user: " + "; ".join(_line(r) for r in picked) + "."


# Facts beyond the always-sent ones that a single request may pull in.
_MAX_RELEVANT_FACTS = 5


def _split() -> typing.Tuple[typing.List[typing.Dict], typing.List[typing.Dict]]:
    """(facts for every prompt, the rest). What the user said outranks what was
    guessed, and newer outranks older."""
    _seed_from_config()
    from helpers.memory_db import all_facts_with_source

    ranked = sorted(all_facts_with_source(), key=lambda r: r["ts"] or "", reverse=True)
    ranked.sort(key=lambda r: r["source"] == "auto")  # stable: newest first within each
    return ranked[:_MAX_PROMPT_FACTS], ranked[_MAX_PROMPT_FACTS:]


def _line(row: typing.Dict) -> str:
    return f"{row['key'].replace('_', ' ')}: {str(row['value'])[:_MAX_PROMPT_FACT_CHARS]}"


def _rank(request: str, rows: typing.List[typing.Dict]) -> typing.List[int]:
    """By meaning once the embedding model is loaded, by words until then."""
    from helpers import lookup, semantic

    if semantic.ready():
        try:
            # Profile.set already stored each fact's embedding.
            index = {r["key"]: i for i, r in enumerate(rows)}
            hits = semantic.retrieve(request, k=len(rows) + _MAX_PROMPT_FACTS, source_types=["fact"])
            # Below this a fact is about something else; bge-small scores
            # unrelated short texts around 0.4-0.5.
            return [index[h["ref_key"]] for h in hits if h["ref_key"] in index and h["score"] >= 0.6]
        except Exception:
            pass
    semantic.warm()
    entries = [(str(r["value"]).lower(), r["key"].replace("_", " ").lower()) for r in rows]
    return lookup.rank(lookup.keywords(request), entries)
