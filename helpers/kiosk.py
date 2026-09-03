"""
The touch screen's side of the conversation.

Two ways in, and the difference between them is the whole point of a touch
device:

  run_tile()  — someone tapped a button. It resolves to a registered job and
                runs it directly. No model call, so it is instant, free, and
                gives the same answer every time. This is the common case.
  run_text()  — someone typed a sentence on the on-screen keyboard. That goes
                through the agent, because free text is what the agent is for.

A third kind of tile, "screen", runs nothing at all: it names a place in the
UI. Some things — signing in to Google, picking a track — need a form and a
back button, not an answer.

Both come back as a KioskTurn so the UI renders one shape either way.

ambient() is the third, passive one: what the screen shows itself when nobody
has touched it for a while.
"""

import threading
import time
import typing

from helpers.config import Config
from helpers.decorators import is_error_response
from helpers.registry import ServiceRegistry

# The home screen when config.yaml says nothing about tiles. Each entry is only
# offered if its module is enabled and its job actually registered, so a tile
# can never be a button that does nothing. Keep these to things worth one tap:
# a question with a stable answer, or an action with no arguments.
#
# None of these open the chat. A tile that dropped you into a conversation to
# read a temperature made the screen a slower way of typing; anything with more
# than a sentence of answer, or anything to press afterwards, gets its own
# screen instead. The same modules are still there to talk to.
_DEFAULT_TILES: typing.List[typing.Dict[str, typing.Any]] = [
    {"id": "time", "label": "Time", "icon": "🕑", "kind": "job",
     "job": "get_datetime", "module": "basics"},
    {"id": "briefing", "label": "Briefing", "icon": "👋", "kind": "job",
     "job": "greeting", "module": "basics"},
    {"id": "weather", "label": "Weather", "icon": "🌤️", "kind": "screen",
     "screen": "weather", "module": "weather"},
    {"id": "reminders", "label": "Reminders", "icon": "⏰", "kind": "screen",
     "screen": "reminders", "module": "scheduler"},
    {"id": "agenda", "label": "Today", "icon": "📅", "kind": "screen",
     "screen": "agenda", "module": "calendar"},
    {"id": "inbox", "label": "Inbox", "icon": "✉️", "kind": "job",
     "job": "inbox_overview", "module": "gmail"},
    {"id": "lights", "label": "Devices", "icon": "💡", "kind": "screen",
     "screen": "devices", "module": "home_assistant"},
    {"id": "playpause", "label": "Play / Pause", "icon": "⏯️", "kind": "job",
     "job": "control_playback", "args": {"action": "toggle"}, "module": "spotify"},
    # Signing in to Google is the one setup step that can't be done from a
    # sentence — it needs a browser and a name field — so it gets a screen.
    {"id": "accounts", "label": "Accounts", "icon": "👤", "kind": "screen",
     "screen": "accounts", "module": "google_accounts"},
    # Last, and a screen rather than a job: sending the device dark is the one
    # tile you must not be able to hit by accident, so it asks for a wake time
    # and a confirmation first.
    {"id": "sleep", "label": "Sleep", "icon": "🌙", "kind": "screen",
     "screen": "sleep", "module": "basics"},
]

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


def tiles() -> typing.List[typing.Dict[str, typing.Any]]:
    """The home-screen manifest.

    A `tiles:` list in config.yaml replaces the defaults outright — a user who
    has arranged their own home screen does not want ours merged back in.
    """
    configured = Config.get("tiles", []) or []
    if configured:
        return [_normalize(dict(tile)) for tile in configured]

    enabled = Config.enabled_modules()

    out = []
    for tile in _DEFAULT_TILES:
        # Only a job tile names a job to check; prompt and screen tiles just
        # need their module on.
        if tile["kind"] in ("prompt", "screen"):
            if tile["module"] not in enabled:
                continue
        elif not _job_available(tile["module"], tile["job"]):
            continue
        out.append(_normalize({k: v for k, v in tile.items() if k != "module"}))
    return out


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


def _normalize(tile: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    """Fill in the optional fields so the UI never has to check for absence."""
    return {
        "id": str(tile.get("id", "")),
        "label": str(tile.get("label", "")),
        "icon": str(tile.get("icon", "")),
        "kind": tile.get("kind", "job"),
        "job": tile.get("job"),
        "prompt": tile.get("prompt"),
        "screen": tile.get("screen"),
        "args": tile.get("args") or {},
    }


def run_tile(tile_id: str) -> KioskTurn:
    """Run the tile with this id.

    Raises KeyError if there is no such tile, and ValueError for a screen tile,
    which has nothing to run here — it is a place the UI goes.
    """
    match = next((t for t in tiles() if t["id"] == tile_id), None)
    if match is None:
        raise KeyError(tile_id)

    if match["kind"] == "screen":
        raise ValueError(f"Tile '{tile_id}' opens a screen; there is nothing to run.")

    if match["kind"] == "prompt":
        return run_text(match["prompt"] or "", source=f"tile:{tile_id}")

    return _run_job(match["job"] or "", match["args"], source=f"tile:{tile_id}")


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


def run_text(
    text: str,
    source: str = "keyboard",
    on_text: typing.Optional[typing.Callable[[str], None]] = None,
) -> KioskTurn:
    """Send typed text through the agent and record the exchange."""
    from helpers.conversation import Conversation
    from helpers.logger import logger
    from helpers.turn import run_turn

    message = (text or "").strip()
    if not message:
        return KioskTurn(text="", source=source, ok=False)

    logger.log_user_input(message, source)
    result = run_turn(message, on_text=on_text)
    if result.error is not None:
        return KioskTurn(text=result.error, source=source, ok=False)

    Conversation.record_turn(message, result.text, calls=result.calls)
    return KioskTurn(text=result.text, source=source, ok=True)
