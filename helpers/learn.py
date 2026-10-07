"""What Wony works out about the user without being told to remember it.

`remember` only ever fires when the user says "remember that". Everything else
they mention — the dog's name, that they cycle to work, that they hate being
called by their full name — is said once and gone. This is the background pass
that keeps it: every so often it reads the conversations since it last looked,
asks the model for the handful of facts that will still be true next month, and
stores them like any other fact. It also samples the user's own sent mail so a
drafted reply sounds like them rather than like a form letter.

Two things make this safe to have at all:

- It is off until `assistant.memory.learn_from_my_data` is set. Storing things
  nobody asked to store is a decision the user makes, not a default.
- Everything it writes is marked `source="auto"`, so `recall` can show which
  facts were guessed rather than stated, and `remember(action="forget")` throws
  one out. A wrong fact that rides along in every prompt is the failure mode
  that matters, and it has to be findable.
"""

import json
import re
import typing

from helpers.jobs import BackgroundJobs
from helpers.logger import logger

_JOB_NAME = "learn"

# How often the pass wakes. Facts do not go stale in an hour, and each pass is a
# model call the user did not ask for — this is the whole reason it is not run
# after every turn.
_TICK_SECONDS = 1800.0

# Below this many new exchanges there is nothing worth a model call; above it,
# one pass would be a wall of text.
_MIN_NEW_TURNS = 6
_MAX_TURNS_PER_PASS = 40

# Profile.as_text() carries facts into every system prompt, so an unbounded
# learner would quietly grow the cost of every request. At the cap it stops
# adding rather than evicting: throwing away a fact the user stated by hand to
# make room for a guessed one is the wrong trade.
_MAX_AUTO_FACTS = 60

_MAX_FACT_CHARS = 160

# Style is a property of how someone writes, which does not change week to week.
_STYLE_INTERVAL_SECONDS = 7 * 24 * 3600.0
_STYLE_SAMPLE = 12
_STYLE_BODY_CHARS = 600
_STYLE_KEY = "writing_style"

_CURSOR_KEY = "learn_last_turn_id"
_STYLE_STAMP_KEY = "learn_style_ts"

_FACTS_PROMPT = (
    "Below are transcript excerpts from a personal assistant's conversations with"
    " its user. List the durable facts about the user that are worth remembering"
    " for months: preferences, relationships, routines, constraints, names of"
    " people, pets and places in their life.\n\n"
    "Rules:\n"
    "- Only what the USER stated about themselves. Never what the assistant said.\n"
    "- Nothing transient: no current weather, no what-is-playing, no one-off tasks.\n"
    "- Nothing sensitive: no passwords, card numbers, addresses or health details.\n"
    "- If nothing qualifies, return [].\n\n"
    'Answer with JSON only: [{"topic": "short_snake_case", "fact": "one sentence"}]'
)

_STYLE_PROMPT = (
    "Below are emails the user wrote. Describe how they write in at most 40 words:"
    " greeting and sign-off they use, sentence length, formality, whether they use"
    " lists or emoji. Describe the style only — never repeat the subject matter,"
    " names or any other content of the emails. Answer with the description alone."
)


def enabled() -> bool:
    from helpers.config import Config

    return bool(Config.get("assistant.memory.learn_from_my_data", False))


def start() -> bool:
    """Begin learning in the background. No-op while the gate is off."""
    if not enabled():
        return False
    return BackgroundJobs.start(_JOB_NAME, tick, interval=_TICK_SECONDS)


def stop() -> bool:
    return BackgroundJobs.stop(_JOB_NAME)


def running() -> bool:
    return BackgroundJobs.is_running(_JOB_NAME)


def tick() -> None:
    """One pass. Public so `recall` can force one and tests can call it directly."""
    if not enabled():
        return
    for step in (learn_facts, learn_style):
        try:
            step()
        except Exception as e:
            # A failed pass is a missed fact, not a reason to end the thread.
            logger.log_error(str(e), f"learn.{step.__name__}")


# ------------------------------------------------------------------ facts


def learn_facts() -> int:
    """Distil new conversations into facts. Returns how many were stored."""
    from helpers.memory_db import count_facts, get_kv, recent_turns, set_kv

    since = int(get_kv(_CURSOR_KEY, "0") or 0)
    turns = [t for t in recent_turns(limit=_MAX_TURNS_PER_PASS) if int(t["id"]) > since]
    if len(turns) < _MIN_NEW_TURNS:
        return 0

    newest = max(int(t["id"]) for t in turns)
    # Move the cursor before extracting, not after: a model call that fails
    # halfway must not make the next pass re-read and re-charge for the same
    # exchanges forever.
    set_kv(_CURSOR_KEY, str(newest))

    if count_facts("auto") >= _MAX_AUTO_FACTS:
        return 0

    from helpers.private_numbers import hide

    transcript = hide("\n".join(
        f"User: {t['user_text']}\nAssistant: {(t.get('assistant_text') or '')[:400]}"
        for t in turns
    ))
    candidates = _ask_for_facts(transcript)
    return _store(candidates)


def _store(candidates: typing.List[typing.Dict[str, str]]) -> int:
    from helpers.memory_db import count_facts, get_fact
    from helpers.profile import Profile

    stored = 0
    for item in candidates:
        # count_facts already counts what this loop has written, so the running
        # total must not be added to it again.
        if count_facts("auto") >= _MAX_AUTO_FACTS:
            break
        fact = str(item.get("fact", "")).strip()[:_MAX_FACT_CHARS]
        if not fact:
            continue
        topic = str(item.get("topic", "")) or fact
        key = re.sub(r"[^a-z0-9_]+", "_", topic.lower().strip())[:40].strip("_")
        if not key:
            continue
        # Never overwrite: a fact the user stated by hand outranks a guess, and
        # re-deriving one that is already stored is not new information.
        if get_fact(key) is not None:
            continue
        Profile.set(key, fact, source="auto")
        logger.log_system_event("learned", f"{key}: {fact}")
        stored += 1
    return stored


def _ask_for_facts(transcript: str) -> typing.List[typing.Dict[str, str]]:
    raw = _ask(f"{_FACTS_PROMPT}\n\n---\n{transcript}")
    parsed = _parse_json_list(raw)
    return [item for item in parsed if isinstance(item, dict)]


# ------------------------------------------------------------------ writing style


def learn_style() -> bool:
    """Summarise how the user writes, from their own sent mail. True when updated."""
    import time

    from helpers.config import Config
    from helpers.memory_db import get_kv, set_kv
    from helpers.registry import ServiceRegistry

    if not Config.is_module_enabled("gmail"):
        return False
    last = float(get_kv(_STYLE_STAMP_KEY, "0") or 0)
    if time.time() - last < _STYLE_INTERVAL_SECONDS:
        return False

    gmail = ServiceRegistry.get_service_instance("gmail")
    if gmail is None:
        return False

    messages = gmail.search_messages("", max_results=_STYLE_SAMPLE, folder="sent")
    if not messages:
        return False

    set_kv(_STYLE_STAMP_KEY, str(time.time()))
    sample = "\n\n---\n\n".join(
        (msg.plain or msg.snippet or "")[:_STYLE_BODY_CHARS] for msg in messages
    ).strip()
    if not sample:
        return False

    description = _ask(f"{_STYLE_PROMPT}\n\n---\n{sample}").strip()
    if not description:
        return False

    from helpers.profile import Profile

    Profile.set(_STYLE_KEY, description[:_MAX_FACT_CHARS], source="auto")
    logger.log_system_event("learned", f"{_STYLE_KEY}: {description[:80]}")
    return True


# ------------------------------------------------------------------ model plumbing


def _ask(prompt: str) -> str:
    import helpers.model as helpers_model

    return helpers_model.ask_plain(prompt)


def _parse_json_list(raw: str) -> typing.List[typing.Any]:
    """Read a JSON array out of a model reply, fenced or prefaced or neither."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []
