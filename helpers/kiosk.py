"""
The touch screen's side of the conversation.

The panel has no keyboard for typed sentences and no microphone; every tile on
the home screen is a whole-button action, resolved straight to a job with no
model call — instant, free, and the same answer every time.

load_tiles() / save_tiles() hold the user's home-screen layout: a flat list of
tile ids (`kind` or `kind:arg`), kept in the kiosk's own kv row rather than
config.yaml, because it is arranged by touch, not by hand-editing a file.

ambient() is the passive one: what the screen shows itself when nobody has
touched it for a while.
"""

import json
import re
import threading
import time
import typing

from helpers.config import Config
from helpers.decorators import is_error_response
from helpers.registry import ServiceRegistry

# id = "kind" or "kind:arg" — e.g. "routine:briefing", "device:light.lamp",
# "timer:10", "music", "volume", "sleep". The arg (after the colon) is opaque
# here; each kind's own screen code interprets it.
_TILE_ID_RE = re.compile(r"^(routine|device|timer|music|volume|sleep)(:.{1,120})?$")
_MAX_TILES = 32
_TILES_KV_KEY = "kiosk.tiles"


def load_tiles() -> typing.Optional[typing.List[str]]:
    """The saved home-screen layout, or None when nobody has arranged one yet.

    None (as opposed to an empty list) is what tells the UI to seed a starter
    layout instead of showing a blank grid.
    """
    from helpers.memory_db import get_kv

    raw = get_kv(_TILES_KV_KEY, "")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    return [str(item) for item in parsed]


def save_tiles(tile_ids: typing.List[str]) -> None:
    """Validate and persist the home-screen layout.

    Raises ValueError for anything that could not have come from the UI itself
    — this is the one place a hand-crafted request could otherwise smuggle
    arbitrary text into storage.
    """
    from helpers.memory_db import set_kv

    if len(tile_ids) > _MAX_TILES:
        raise ValueError(f"Too many tiles (max {_MAX_TILES}).")
    for tile_id in tile_ids:
        if not isinstance(tile_id, str) or not _TILE_ID_RE.match(tile_id):
            raise ValueError(f"Invalid tile id: {tile_id!r}")
    set_kv(_TILES_KV_KEY, json.dumps(tile_ids))


# What the screen shows itself once nobody has touched it. The clock and date
# are the client's own business; notifications already arrive over the
# WebSocket. This list is only for the cards that need a job run to fill them.
_AMBIENT_CARDS: typing.List[typing.Dict[str, typing.Any]] = [
    {"key": "agenda", "label": "Coming up", "module": "calendar",
     "job": "find_events", "args": {"hours_ahead": 24, "limit": 3}},
]

# An ambient screen left on overnight would otherwise poll Google Calendar
# every few seconds. Nothing on it changes faster than this.
_AMBIENT_TTL_SECONDS = 600

_ambient_lock = threading.Lock()
_ambient_cache: typing.Dict[str, typing.Tuple[float, str]] = {}


class KioskTurn(typing.NamedTuple):
    text: str
    # Which tile or free-text path produced this, for the UI's own logging.
    source: str
    ok: bool


def _job_available(module: str, job_name: str) -> bool:
    """True when this module is on AND the job it names actually registered.

    Both halves matter. A module can be enabled and still fail to register its
    jobs (missing credentials, missing package), and a manifest entry can name
    a job that was renamed out from under it. Either way the result is a button
    that does nothing, which is worse than a button that is not there.
    """
    if module not in Config.enabled_modules():
        return False
    return job_name in ServiceRegistry.get_all_jobs()


def ambient() -> typing.List[typing.Dict[str, typing.Any]]:
    """Cards for the idle screen, each holding a job's own text output.

    No model is involved, and results are cached, so leaving the screen on all
    night costs one calendar lookup per ten minutes.
    """
    now = time.monotonic()
    out = []

    for card in _AMBIENT_CARDS:
        if not _job_available(card["module"], card["job"]):
            continue

        with _ambient_lock:
            cached = _ambient_cache.get(card["key"])

        if cached is not None and now - cached[0] < _AMBIENT_TTL_SECONDS:
            text = cached[1]
        else:
            result = _run_job(
                card["job"], card["args"],
                source=f"ambient:{card['key']}", wait=False,
            )
            # A failed lookup is not cached, and not shown: the network may be
            # back in a second, and a stale "invalid_grant" would sit on the
            # idle screen for the full TTL. An empty card is better.
            # capture_response returns failures as ordinary strings, so the
            # exception never reaches _run_job — is_error_response is the check.
            if not result.ok or is_error_response(result.text):
                continue
            text = result.text
            with _ambient_lock:
                _ambient_cache[card["key"]] = (now, text)

        if text.strip():
            out.append({"key": card["key"], "label": card["label"], "text": text})

    return out


def _run_job(
    job_name: str,
    args: typing.Dict[str, typing.Any],
    source: str,
    wait: bool = True,
) -> KioskTurn:
    """Invoke a registered job directly, with no model in the loop.

    Runs under agent_lock: a tapped tile reaches the same jobs and the same
    _agent_active flag as a typed sentence, and clearing that flag underneath a
    running turn would make it narrate every tool call it makes.

    wait=False gives up rather than queueing behind a turn in progress — for
    the idle screen, whose refresh is a cache top-up nobody is waiting on.
    """
    from helpers.decorators import agent_lock, set_agent_active
    from helpers.logger import logger
    from helpers.web_app import _coerce_args

    func = ServiceRegistry.get_all_jobs().get(job_name)
    if func is None:
        return KioskTurn(text=f"'{job_name}' isn't available right now.",
                         source=source, ok=False)

    if not agent_lock.acquire(blocking=wait):
        return KioskTurn(text="", source=source, ok=False)

    logger.log_function_call(job_name, f"[{source}]", args)
    try:
        set_agent_active(True)
        result = func(**_coerce_args(func, args))
    except Exception as e:
        logger.log_error(str(e), f"kiosk.{job_name}")
        return KioskTurn(text=f"That didn't work: {e}", source=source, ok=False)
    finally:
        set_agent_active(False)
        agent_lock.release()

    text = str(result) if result is not None else ""
    logger.log_function_response(job_name, text[:200], f"[{source}]")
    return KioskTurn(text=text, source=source, ok=True)
