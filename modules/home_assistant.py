"""Home Assistant control over its REST API.

Entity resolution lives here rather than in the prompt: one /api/template
render returns the whole entity/name/area/state index, which /api/states
cannot do — areas live in the entity registry and REST does not expose it.
That keeps the two tool schemas tiny no matter how big the house is.

Verbs that the tables below do not name are looked up in Home Assistant's own
service registry, so an integration installed after this file was written is
still reachable without a new job.
"""
import os
import re
import time
import typing
import unicodedata
from dataclasses import dataclass, field

import requests

from helpers import net
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement

_TOKEN_ENV = "HOME_ASSISTANT_TOKEN"

# \x1f (unit separator) cannot occur in a device name; '|' can. The one field
# that is itself a list needs a second separator, and it cannot be \x1e — that
# is a line break to str.splitlines(), which would cut the row in half.
_SEP = "\x1f"
_OPTION_SEP = "\x01"
_INDEX_TEMPLATE = (
    "{% for s in states %}{{ s.entity_id }}\x1f{{ s.name }}\x1f"
    "{{ area_name(s.entity_id) or '' }}\x1f{{ s.state }}\x1f"
    "{{ s.attributes.get('device_class', '') }}\x1f"
    # Nested defaults, not 'or': a cover at position 0 is a real level.
    "{{ s.attributes.get('brightness', s.attributes.get('current_position',"
    " s.attributes.get('percentage', ''))) }}\x1f"
    "{{ (s.attributes.get('options') or s.attributes.get('fan_speed_list')"
    " or s.attributes.get('preset_modes') or s.attributes.get('hvac_modes')"
    " or s.attributes.get('source_list') or s.attributes.get('operation_list')"
    " or []) | join('\x01') }}\x1f"
    "{{ device_attr(s.entity_id, 'name') or '' }}\x1f"
    "{{ is_hidden_entity(s.entity_id) }}\n{% endfor %}"
)
# The last field is the hidden flag, which is dropped rather than stored.
_INDEX_FIELDS = 9

# Service calls block until Home Assistant has run the handler; the default
# 8s read timeout would report failure for a command that actually landed.
_SERVICE_TIMEOUT = (3.0, 15.0)

# A vague target ("light") can match half the house, and an unwanted mass
# switch-off is not something the user can undo by saying "no". Naming a room
# or a device type is the user being explicit, so that ceiling is far higher —
# "turn all the lights off" is a normal thing to ask a house.
_MAX_VAGUE_TARGETS = 12
_MAX_SCOPED_TARGETS = 60

_MAX_LISTED = 60

# Above this many devices the question was "what do I have", not "tell me
# about this one", and every sub-entity would bury the answer.
_DETAIL_DEVICES = 5

# The service registry only changes when an integration is added or removed.
_SERVICES_TTL = 300.0

_GENERIC_ACTIONS = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}

# Domains whose services are not turn_on/turn_off/toggle, or that have useful
# verbs beyond them. First verb per service is the one shown to the model.
_DOMAIN_ACTIONS: typing.Dict[str, typing.Dict[str, str]] = {
    "cover": {
        "open": "open_cover", "on": "open_cover", "close": "close_cover",
        "off": "close_cover", "stop": "stop_cover", "toggle": "toggle",
    },
    "valve": {
        "open": "open_valve", "on": "open_valve", "close": "close_valve",
        "off": "close_valve", "stop": "stop_valve", "toggle": "toggle",
    },
    "lock": {
        "lock": "lock", "on": "lock", "close": "lock",
        "unlock": "unlock", "off": "unlock", "open": "unlock",
    },
    "alarm_control_panel": {
        "arm": "alarm_arm_away", "on": "alarm_arm_away",
        "disarm": "alarm_disarm", "off": "alarm_disarm",
    },
    "button": {"press": "press", "on": "press", "toggle": "press"},
    # Vacuums and mowers have no turn_on/turn_off service at all, and "off"
    # means go home rather than cut the power.
    "vacuum": {
        "start": "start", "on": "start", "clean": "start",
        "dock": "return_to_base", "off": "return_to_base",
        "home": "return_to_base", "return": "return_to_base",
        "pause": "pause", "stop": "stop", "locate": "locate",
    },
    "lawn_mower": {
        "start": "start_mowing", "on": "start_mowing", "mow": "start_mowing",
        "dock": "dock", "off": "dock", "home": "dock", "pause": "pause",
    },
    "media_player": {
        "on": "turn_on", "off": "turn_off", "toggle": "toggle",
        "play": "media_play", "pause": "media_pause", "stop": "media_stop",
        "next": "media_next_track", "previous": "media_previous_track",
    },
    # A scene cannot be un-applied, so its switch only ever applies it.
    "scene": {"on": "turn_on", "activate": "turn_on", "toggle": "turn_on"},
    "script": {"run": "turn_on", "on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "automation": {
        "on": "turn_on", "off": "turn_off", "toggle": "toggle",
        "run": "trigger", "trigger": "trigger",
    },
    "water_heater": {"on": "turn_on", "off": "turn_off"},
    # Set-only entities: no on/off exists, they take a value or a named mode.
    "select": {},
    "input_select": {},
    "number": {},
    "input_number": {},
}


class _Setting(typing.NamedTuple):
    """How one domain takes a value: which service, which field, what range."""

    service: str
    field: str
    # None where the device decides its own range, or the value is a name.
    limits: typing.Optional[typing.Tuple[float, float]] = (0.0, 100.0)
    # Home Assistant wants media volume as 0-1; the user says "volume 30".
    scale: float = 1.0


_VALUE_SETTINGS: typing.Dict[str, _Setting] = {
    "light": _Setting("turn_on", "brightness_pct", (1.0, 100.0)),
    "cover": _Setting("set_cover_position", "position"),
    "fan": _Setting("set_percentage", "percentage"),
    "humidifier": _Setting("set_humidity", "humidity"),
    "media_player": _Setting("volume_set", "volume_level", (0.0, 100.0), 0.01),
    "number": _Setting("set_value", "value", None),
    "input_number": _Setting("set_value", "value", None),
    # A bare number at a thermostat is degrees, not a percentage — "set the
    # bedroom to 21" reaches this only when no light or blind matched.
    "climate": _Setting("set_temperature", "temperature", None),
    "water_heater": _Setting("set_temperature", "temperature", None),
}

_TEMPERATURE_SETTINGS: typing.Dict[str, _Setting] = {
    "climate": _Setting("set_temperature", "temperature", None),
    "water_heater": _Setting("set_temperature", "temperature", None),
}

_OPTION_SETTINGS: typing.Dict[str, _Setting] = {
    "select": _Setting("select_option", "option", None),
    "input_select": _Setting("select_option", "option", None),
    "vacuum": _Setting("set_fan_speed", "fan_speed", None),
    "climate": _Setting("set_hvac_mode", "hvac_mode", None),
    "fan": _Setting("set_preset_mode", "preset_mode", None),
    "humidifier": _Setting("set_mode", "mode", None),
    "media_player": _Setting("select_source", "source", None),
    "water_heater": _Setting("set_operation_mode", "operation_mode", None),
}

# "Set the kitchen to 30" matches the lights, the thermostat and a sensor.
# Which domain a bare number means is decided here, not by the caller.
_VALUE_ORDER = ("light", "cover", "fan", "number", "input_number", "humidifier",
                "climate", "water_heater", "media_player")
_TEMPERATURE_ORDER = ("climate", "water_heater")
_OPTION_ORDER = ("select", "input_select", "vacuum", "climate", "fan", "humidifier",
                 "media_player", "water_heater")

_CONTROLLABLE = {
    "light", "switch", "fan", "cover", "lock", "climate", "media_player",
    "scene", "script", "automation", "input_boolean", "humidifier", "vacuum",
    "siren", "water_heater", "button", "valve", "alarm_control_panel",
    "lawn_mower", "remote", "select", "input_select", "number", "input_number",
}

# Physical-security devices — a misheard command here has consequences the
# other domains don't. Gated behind modules.home_assistant.allow_locks.
_GUARDED_DOMAINS = {"lock", "alarm_control_panel"}
_GUARDED_COVER_CLASSES = {"garage", "gate", "door"}

# A docked vacuum and an idle siren are off, whatever the domain calls it.
_OFF_STATES = {
    "", "off", "closed", "locked", "docked", "idle", "standby", "paused",
    "unavailable", "unknown", "none",
}

# These hold no state at all — a button's state is when it was last pressed,
# a scene's when it was last applied. Neither means the thing is on now.
_STATELESS_DOMAINS = {"button", "input_button", "scene"}

# Set to a bare number, with a range only the device knows.
_NUMBER_DOMAINS = {"number", "input_number"}

# Only ever a service name, because it is pasted into the request path.
_SERVICE_NAME = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass
class _Entity:
    entity_id: str
    name: str
    area: str
    state: str
    device_class: str
    # Whatever this device shows on a slider: light brightness (0-255), cover
    # position or fan percentage (0-100). Empty unless the device reports one.
    level: str = ""
    options: str = ""
    # The physical thing this entity belongs to. One robot vacuum is twenty-odd
    # entities; without this they are twenty-odd unrelated devices.
    device: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    def label(self) -> str:
        return f"{self.name} ({self.area})" if self.area else self.name

    def short_name(self) -> str:
        """The entity's own name, with the device's name taken off the front:
        'Clanker Suction Level' under Clanker is just 'Suction Level'."""
        prefix = f"{self.device} "
        if self.device and self.name.startswith(prefix):
            return self.name[len(prefix):]
        return self.name

    def level_percent(self) -> typing.Optional[int]:
        try:
            raw = int(self.level)
        except ValueError:
            return None
        return round(raw / 255 * 100) if self.domain == "light" else raw

    def option_list(self) -> typing.List[str]:
        return [part for part in self.options.split(_OPTION_SEP) if part]


@dataclass
class _Change:
    """A value the user asked for, before any domain has claimed it."""

    value: typing.Optional[float] = None
    temperature: typing.Optional[float] = None
    option: str = ""

    def wanted(self) -> bool:
        return self.value is not None or self.temperature is not None or bool(self.option)


# ── config / setup ────────────────────────────────────────────────────────────


def _base_url() -> str:
    from helpers.config import Config

    settings = Config.module_settings("home_assistant")
    return str(settings.get("base_url", "")).rstrip("/")


def _locks_allowed() -> bool:
    from helpers.config import Config

    return bool(Config.get("modules.home_assistant.allow_locks", False))


def _requirement() -> Requirement:
    return Requirement(
        env_vars=[_TOKEN_ENV],
        check=lambda: bool(_base_url()),
        setup_hint=(
            f"Add {_TOKEN_ENV} to .env (Home Assistant → your profile → Security → "
            "Long-lived access tokens) and set modules.home_assistant.base_url "
            "in config.yaml to your Home Assistant URL."
        ),
    )


def _headers() -> typing.Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ.get(_TOKEN_ENV, '')}",
        "Content-Type": "application/json",
    }


def _failure(exc: Exception, where: str) -> str:
    logger.log_error(str(exc), where)
    response = getattr(exc, "response", None)
    if response is not None and response.status_code in (401, 403):
        return f"Home Assistant rejected the access token. Check {_TOKEN_ENV} in .env."
    return f"Could not reach Home Assistant at {_base_url()}."


# ── index + matching ──────────────────────────────────────────────────────────


def _fetch_index() -> typing.List[_Entity]:
    response = net.post(
        f"{_base_url()}/api/template",
        headers=_headers(),
        json={"template": _INDEX_TEMPLATE},
    )
    response.raise_for_status()
    return _parse_index(response.text)


def _parse_index(text: str) -> typing.List[_Entity]:
    """One rendered row per entity, minus the ones the user hid.

    Hiding an entity in Home Assistant means "do not show me this"; carrying
    it here would put it back in front of them by voice.
    """
    entities = []
    for line in text.splitlines():
        parts = line.split(_SEP)
        if len(parts) != _INDEX_FIELDS:
            continue
        fields = [part.strip() for part in parts]
        if fields[-1] == "True":
            continue
        entities.append(_Entity(*fields[:-1]))
    return entities


@dataclass
class _ServiceCache:
    stamp: float = 0.0
    names: typing.Set[str] = field(default_factory=set)


_services = _ServiceCache()


def _known_services() -> typing.Set[str]:
    """Every 'domain.service' Home Assistant currently offers.

    Read only when a verb is not in the tables above, which is how a HACS
    integration's own services stay reachable without a code change here.
    """
    if _services.names and time.monotonic() - _services.stamp < _SERVICES_TTL:
        return _services.names
    try:
        response = net.get(f"{_base_url()}/api/services", headers=_headers())
        response.raise_for_status()
        _services.names = {
            f"{group['domain']}.{name}"
            for group in response.json()
            for name in group.get("services", {})
        }
        _services.stamp = time.monotonic()
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.log_error(str(exc), "home_assistant_services")
    return _services.names


# Stroked letters have no decomposition, so NFKD leaves them alone.
_STROKED = str.maketrans("łđøŁĐØ", "ldoLDO")


def _tokens(text: str) -> typing.List[str]:
    """Device names carry accents; speech and keyboards often do not, so
    'zarowa' has to reach a lamp called 'Żarówa'."""
    folded = unicodedata.normalize("NFKD", text.lower().translate(_STROKED))
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    cleaned = stripped.replace("_", " ").replace(".", " ")
    words = ("".join(c for c in word if c.isalnum()) for word in cleaned.split())
    return [word for word in words if word]


def _variants(word: str) -> typing.Set[str]:
    """light/lights are one device to a user; Home Assistant names are inconsistent."""
    return {word, word[:-1]} if word.endswith("s") else {word, word + "s"}


def _matches(entities: typing.List[_Entity], query: str) -> typing.List[_Entity]:
    wanted = _tokens(query)
    if not wanted:
        return list(entities)

    exact, partial = [], []
    for entity in entities:
        name_tokens = _tokens(entity.name)
        haystack = (
            set(name_tokens)
            | set(_tokens(entity.area))
            | set(_tokens(entity.entity_id))
            | set(_tokens(entity.device))
        )
        if name_tokens == wanted:
            exact.append(entity)
        elif all(_variants(word) & haystack for word in wanted):
            partial.append(entity)
    return exact or partial


def _filtered(
    entities: typing.List[_Entity], query: str, area: str, domain: str
) -> typing.List[_Entity]:
    found = _matches(entities, query)
    if area:
        wanted_area = set(_tokens(area))
        found = [e for e in found if wanted_area <= set(_tokens(e.area))]
    if domain:
        wanted_domain = domain.strip().lower()
        found = [e for e in found if e.domain == wanted_domain]
    return found


# ── jobs ──────────────────────────────────────────────────────────────────────


@register_job(module_name="home_assistant", requires=_requirement())
@capture_response
def list_home_devices(query: str = "", area: str = "", domain: str = "") -> str:
    """
    [HOME ASSISTANT JOB] Lists smart-home devices, their current state and what each
    one accepts. This is the single tool for both discovery ("what devices do I have",
    "what's in the kitchen") and for reading state ("is the garage door open", "what's
    the bedroom temperature"). Call it before controlling an unfamiliar device: the
    listing names that device's actions and its allowed option values. With no
    arguments it lists the whole house.

    Args:
        query (str): Name to look for, e.g. 'garage door', 'bedroom lamp'. Naming a
                     device shows its sensors and settings too.
        area (str): Restrict to one room, e.g. 'kitchen', 'living room'.
        domain (str): Restrict to one device type: light, switch, sensor, binary_sensor,
                      climate, cover, lock, media_player, vacuum, select, scene, script.

    Returns:
        str: Matching devices as 'Name (room): state', or a note that none matched.
    """
    try:
        entities = _fetch_index()
    except (requests.exceptions.RequestException, ValueError) as exc:
        return _failure(exc, "list_home_devices")

    found = _filtered(entities, query, area, domain)
    if not found:
        return "No matching devices found in Home Assistant."

    return _describe(_with_siblings(found, entities, query))


@register_job(module_name="home_assistant", requires=_requirement())
@capture_response
def control_home_device(
    target: str = "",
    action: str = "on",
    area: str = "",
    domain: str = "",
    value: typing.Optional[float] = None,
    temperature: typing.Optional[float] = None,
    option: str = "",
) -> str:
    """
    [HOME ASSISTANT JOB] Controls smart-home devices through Home Assistant: lights,
    switches, blinds, thermostats, vacuums, locks, media players, scenes and scripts.
    Device names are resolved here, so pass what the user said ('the bedroom lamp')
    rather than an entity id. Give target, or area/domain, or both. If a device
    refuses an action, list it to see the actions and option values it accepts.

    Args:
        target (str): What to control, as the user named it, e.g. 'bedroom lamp'.
        action (str): on, off, toggle, open, close, stop, start, pause, dock, locate,
                      play, next, previous, lock, unlock, arm, disarm, press, run.
        area (str): Restrict to one room. Use with an empty target for 'all the
                    lights in the kitchen'.
        domain (str): Restrict to one device type: light, switch, cover, lock, climate,
                      media_player, vacuum, select, scene, script. Give it with an
                      empty target for 'turn all the lights off' — a whole-house
                      command is only allowed when a room or a type says which.
        value (float): The number the user said: percent for lights, blinds, fans and
                       volume; the plain value for a numeric setting.
        temperature (float): Target temperature. Implies a thermostat or water heater.
        option (str): A named mode, level, preset or source, e.g. 'Turbo', 'heat'.

    Returns:
        str: What was changed, or why it could not be.
    """
    if not (target or area or domain):
        return "Say which device, room or device type to control."

    wanted = (action or "on").strip().lower()
    change = _Change(value=value, temperature=temperature, option=option.strip())

    try:
        entities = _fetch_index()
    except (requests.exceptions.RequestException, ValueError) as exc:
        return _failure(exc, "control_home_device")

    matched = [e for e in _filtered(entities, target, area, domain) if e.domain in _CONTROLLABLE]
    actionable = [e for e in _narrow(matched, change, domain) if _plan(e, wanted, change)[0]]
    if not actionable:
        # The pre-narrowing matches, so a refusal can name the device the user
        # meant rather than claiming the house has nothing by that name.
        return _no_target_message(target, area, domain, wanted, change, matched)

    scoped = bool(area or domain)
    _, text = _apply(
        actionable, wanted, change, _MAX_SCOPED_TARGETS if scoped else _MAX_VAGUE_TARGETS
    )
    return text


def _apply(
    actionable: typing.List[_Entity],
    action: str,
    change: _Change,
    limit: int = _MAX_VAGUE_TARGETS,
) -> typing.Tuple[bool, str]:
    """Run one action against already-chosen entities and describe the result.

    Both ways of choosing devices — a spoken name, or an entity id clicked in
    the UI — end up here, so the lock gate, the mass-change ceiling and the
    per-domain service call exist once.

    Returns (anything actually changed, what to say). The flag is what lets the
    UI tell a refusal from a success without reading the sentence back.
    """
    skipped = []
    if not _locks_allowed():
        # Drop guarded devices rather than refusing the whole command — one lock
        # in the room should not veto turning the lights off.
        skipped = [e for e in actionable if _is_guarded(e)]
        actionable = [e for e in actionable if not _is_guarded(e)]
        if not actionable:
            return False, (
                f"Not allowed to control {', '.join(e.label() for e in skipped)}. Set "
                "modules.home_assistant.allow_locks: true in config.yaml to let Wony "
                "unlock doors, open the garage and disarm alarms."
            )

    if len(actionable) > limit:
        return False, (
            f"That matches {len(actionable)} devices — too many to change at once. "
            "Name a room, a device type, or one device."
        )

    changed, failures = [], []
    for (entity_domain, service, data), group in _by_call(actionable, action, change).items():
        try:
            _call_service(entity_domain, service, [e.entity_id for e in group], dict(data))
            changed.extend(group)
        except (requests.exceptions.RequestException, ValueError) as exc:
            logger.log_error(str(exc), "home_assistant_apply")
            failures.extend(group)

    if not changed:
        return False, (
            f"Home Assistant refused the command for "
            f"{', '.join(e.label() for e in failures)}."
        )

    summary = (
        f"{_verb(action, change)} {', '.join(e.label() for e in changed)}"
        f"{_value_suffix(change, changed)}."
    )
    if failures:
        summary += f" Failed: {', '.join(e.label() for e in failures)}."
    if skipped:
        summary += f" Left {', '.join(e.label() for e in skipped)} alone — locks are off in config."
    return True, summary


# ── panel ─────────────────────────────────────────────────────────────────────


def _index_or_fail(where: str) -> typing.List[_Entity]:
    """The entity index, or a RuntimeError carrying a sentence worth showing.

    The panel puts whatever this raises on screen, and a bare ConnectionError
    stringifies into a paragraph of urllib3 internals.
    """
    try:
        return _fetch_index()
    except (requests.exceptions.RequestException, ValueError) as exc:
        raise RuntimeError(_failure(exc, where)) from exc


def snapshot() -> typing.Dict[str, typing.Any]:
    """Controllable devices grouped by room, for the devices panel.

    One card per physical device, not per entity: a robot vacuum is a vacuum
    with a suction setting and three buttons, not six unrelated switches. What
    it reports — battery, filter life, error text — is not here at all; the
    panel is for changing things, and asking is what the listing job is for.
    """
    entities = _index_or_fail("home_assistant_snapshot")
    controllable = [e for e in entities if e.domain in _CONTROLLABLE]

    by_area: typing.Dict[str, typing.List[typing.Dict[str, typing.Any]]] = {}
    for members in _by_device(controllable).values():
        primary = _primary(members)
        extras = [e for e in members if e is not primary]
        # Momentary buttons after the settings they belong with.
        extras.sort(key=lambda e: (e.domain in _STATELESS_DOMAINS, e.short_name()))

        main = _control(primary)
        rest = [_control(e) for e in extras]
        # A vacuum's own fan_speed and the integration's "Suction Level" select
        # are one setting reached two ways, and would draw two identical
        # dropdowns. The named entity is the one worth keeping.
        if main["options"] and any(c["options"] == main["options"] for c in rest):
            main["options"] = []

        by_area.setdefault(primary.area or "", []).append(
            {
                # The name the user knows it by, which is the entity's, not the
                # registry's: "Żarówa", not "shellycolorbulb-FCF5C4B2E436".
                "name": primary.name,
                "primary": main,
                "extras": rest,
            }
        )

    areas = [
        {"name": area, "devices": sorted(devices, key=lambda d: d["name"])}
        for area, devices in sorted(by_area.items(), key=lambda kv: (kv[0] == "", kv[0]))
    ]
    return {"areas": areas, "locks_allowed": _locks_allowed()}


def _control(entity: _Entity) -> typing.Dict[str, typing.Any]:
    """One entity as the single widget it should be drawn as."""
    setting = _VALUE_SETTINGS.get(entity.domain)
    press = entity.domain in _STATELESS_DOMAINS
    number = entity.domain in _NUMBER_DOMAINS
    return {
        "entity_id": entity.entity_id,
        "name": entity.short_name(),
        "domain": entity.domain,
        "state": entity.state,
        "on": _is_on(entity),
        # Only 'unavailable' means the device is gone. Buttons, scenes and
        # scripts sit at 'unknown' until the first time they run.
        "available": entity.state != "unavailable",
        "level": entity.level_percent(),
        "options": entity.option_list(),
        # A press is momentary and a number has no on/off, so neither is a
        # switch. A vacuum has no toggle service, but start/dock stands in.
        "press": press,
        "number": number,
        "toggle": not press and not number and bool(_service_for(entity, "toggle")),
        "slider": bool(setting and setting.limits),
        # Guarded devices are shown and refused, so the UI can say why rather
        # than silently hiding the front door.
        "guarded": _is_guarded(entity),
    }


def control(
    entity_id: str,
    action: str = "toggle",
    value: typing.Optional[float] = None,
    option: str = "",
) -> typing.Tuple[bool, str]:
    """Act on one device by its exact id, for the devices panel.

    Not a second control path: the UI already knows which device was clicked,
    so it skips the name matching control_home_device needs and hands the same
    entity to the same _apply. Matching by name here would toggle both lamps
    called 'Lamp'.

    Raises RuntimeError, with a sentence, when Home Assistant is unreachable.
    """
    entity = next(
        (e for e in _index_or_fail("home_assistant_control") if e.entity_id == entity_id),
        None,
    )
    if entity is None:
        return False, f"No device '{entity_id}' in Home Assistant."
    if entity.domain not in _CONTROLLABLE:
        return False, f"{entity.label()} cannot be controlled."

    wanted = (action or "toggle").strip().lower()
    change = _Change(value=value, option=option.strip())
    if not _plan(entity, wanted, change)[0]:
        return False, (
            f"Cannot '{wanted}' {entity.label()} — that device type does not support it."
        )

    return _apply([entity], wanted, change)


# ── control helpers ───────────────────────────────────────────────────────────


def _is_on(entity: _Entity) -> bool:
    if entity.domain in _STATELESS_DOMAINS:
        return False
    return entity.state.lower() not in _OFF_STATES


def _narrow(
    found: typing.List[_Entity], change: _Change, domain: str
) -> typing.List[_Entity]:
    """A number or a mode only fits some device types, so 'set the kitchen to
    30' must not reach the kitchen thermostat or its motion sensor."""
    if domain or not change.wanted():
        return found

    if change.option:
        order = _OPTION_ORDER
    elif change.temperature is not None:
        order = _TEMPERATURE_ORDER
    else:
        order = _VALUE_ORDER

    for preferred in order:
        same = [e for e in found if e.domain == preferred]
        if same:
            return same
    return []


def _plan(
    entity: _Entity, action: str, change: _Change
) -> typing.Tuple[str, typing.Dict[str, typing.Any]]:
    """The single service call for this entity, as (service, data).

    Setting a value has its own service per domain — it is not turn_on
    carrying data, except for light brightness, where it is.
    """
    domain = entity.domain

    if change.option and domain in _OPTION_SETTINGS:
        setting = _OPTION_SETTINGS[domain]
        return setting.service, {setting.field: _spelling(entity, change.option)}
    if change.temperature is not None and domain in _TEMPERATURE_SETTINGS:
        setting = _TEMPERATURE_SETTINGS[domain]
        return setting.service, {setting.field: float(change.temperature)}
    if change.value is not None and domain in _VALUE_SETTINGS:
        setting = _VALUE_SETTINGS[domain]
        return setting.service, {setting.field: _number(setting, change.value)}

    return _service_for(entity, action), {}


def _service_for(entity: _Entity, action: str) -> str:
    actions = _DOMAIN_ACTIONS.get(entity.domain, _GENERIC_ACTIONS)
    if action in actions:
        return actions[action]
    if action == "toggle":
        # Vacuums, mowers and water heaters have no toggle service, but the
        # panel's switch still has to mean something.
        return actions.get("off" if _is_on(entity) else "on", "")
    if _SERVICE_NAME.match(action) and f"{entity.domain}.{action}" in _known_services():
        return action
    return ""


def _spelling(entity: _Entity, option: str) -> str:
    """Home Assistant matches options exactly; speech does not carry case."""
    for known in entity.option_list():
        if known.lower() == option.lower():
            return known
    return option


def _number(setting: _Setting, value: float) -> float:
    if setting.limits:
        low, high = setting.limits
        value = max(low, min(high, value))
    return round(float(value) * setting.scale, 4)


def _is_guarded(entity: _Entity) -> bool:
    if entity.domain in _GUARDED_DOMAINS:
        return True
    return entity.domain == "cover" and entity.device_class in _GUARDED_COVER_CLASSES


_Call = typing.Tuple[str, str, typing.Tuple[typing.Tuple[str, typing.Any], ...]]


def _by_call(
    entities: typing.List[_Entity], action: str, change: _Change
) -> typing.Dict[_Call, typing.List[_Entity]]:
    """One request per distinct service call, however many entities share it."""
    grouped: typing.Dict[_Call, typing.List[_Entity]] = {}
    for entity in entities:
        service, data = _plan(entity, action, change)
        grouped.setdefault((entity.domain, service, tuple(sorted(data.items()))), []).append(
            entity
        )
    return grouped


def _call_service(
    domain: str,
    service: str,
    entity_ids: typing.List[str],
    extra: typing.Dict[str, typing.Any],
) -> None:
    payload: typing.Dict[str, typing.Any] = {"entity_id": entity_ids}
    payload.update(extra)
    response = net.post(
        f"{_base_url()}/api/services/{domain}/{service}",
        headers=_headers(),
        json=payload,
        timeout=_SERVICE_TIMEOUT,
    )
    response.raise_for_status()


def _verbs(domain: str) -> typing.List[str]:
    """The user-facing verbs a domain accepts, one per distinct service."""
    seen: typing.Set[str] = set()
    verbs = []
    for verb, service in _DOMAIN_ACTIONS.get(domain, _GENERIC_ACTIONS).items():
        if service not in seen:
            seen.add(service)
            verbs.append(verb)
    return verbs


# ── listing ───────────────────────────────────────────────────────────────────


# What a device *is* when it exposes several entities: the vacuum, not its
# "Pause" button; the bulb, not its "Restart" button.
_PRIMARY_DOMAINS = (
    "light", "switch", "cover", "climate", "media_player", "vacuum", "lawn_mower",
    "fan", "lock", "alarm_control_panel", "water_heater", "humidifier", "valve",
    "siren", "remote", "scene", "script", "automation",
)


def _with_siblings(
    found: typing.List[_Entity], entities: typing.List[_Entity], query: str
) -> typing.List[_Entity]:
    """Naming a device means the whole device: 'how is the vacuum doing' wants
    its battery and its error message, not only the entity that holds its
    state. Naming one of its sensors does not drag the other twenty-six along.
    """
    wanted = set(_tokens(query))
    if not wanted:
        return found

    devices = {e.device for e in found if e.device and set(_tokens(e.device)) == wanted}
    if not devices:
        return found

    known = {e.entity_id for e in found}
    return found + [
        e for e in entities if e.device in devices and e.entity_id not in known
    ]


def _by_device(
    entities: typing.List[_Entity],
) -> typing.Dict[str, typing.List[_Entity]]:
    """Entities under the physical device they belong to, grouped by room."""
    groups: typing.Dict[str, typing.List[_Entity]] = {}
    for entity in sorted(entities, key=lambda e: (e.area, e.device or e.name, e.name)):
        groups.setdefault(entity.device or entity.name, []).append(entity)
    return groups


def _primary(members: typing.List[_Entity]) -> _Entity:
    for domain in _PRIMARY_DOMAINS:
        for entity in members:
            if entity.domain == domain:
                return entity
    return members[0]


def _headline(entity: _Entity) -> str:
    return f"{entity.label()}: {entity.state}{_capability_hint(entity)}"


def _describe(found: typing.List[_Entity]) -> str:
    """The listing, one entry per device rather than per entity.

    A single robot vacuum is twenty-odd entities. Flat, they bury the house in
    'Filter Remaining' rows and push the real devices past the truncation
    limit, so the model's map of the house is mostly noise.
    """
    groups = _by_device(found)
    detailed = len(groups) <= _DETAIL_DEVICES

    if detailed:
        lines = _detail_lines(groups)
    else:
        lines = [_headline(_primary(members)) for members in groups.values()]

    if len(lines) > _MAX_LISTED:
        lines = lines[:_MAX_LISTED] + [f"...and {len(lines) - _MAX_LISTED} more."]
    if not detailed:
        lines.append("Ask for a device by name to see its sensors and settings.")
    return "\n".join(lines)


def _detail_lines(
    groups: typing.Dict[str, typing.List[_Entity]],
) -> typing.List[str]:
    """Each device, then what can be done to it, then what it reports."""
    lines = []
    for members in groups.values():
        primary = _primary(members)
        rest = [e for e in members if e is not primary]
        lines.append(_headline(primary))
        lines.extend(
            f"  {e.short_name()}: {e.state}{_capability_hint(e)}"
            for e in rest
            if e.domain in _CONTROLLABLE
        )
        readings = [
            f"{e.short_name()}: {e.state}" for e in rest if e.domain not in _CONTROLLABLE
        ]
        if readings:
            lines.append("  " + "; ".join(readings))
    return lines


# ── sentences ─────────────────────────────────────────────────────────────────


def _capability_hint(entity: _Entity) -> str:
    """What this device takes, for the devices where guessing goes wrong.

    Without it the model tries 'on' against a vacuum, gets refused, and tells
    the user the device is unsupported. Domains that are only on/off say
    nothing, so a house-wide listing does not grow a column of noise.
    """
    if entity.domain not in _CONTROLLABLE:
        return ""

    parts = []
    verbs = _verbs(entity.domain)
    if verbs and not set(verbs) <= set(_GENERIC_ACTIONS):
        parts.append("accepts " + ", ".join(verbs))
    if entity.option_list():
        parts.append("options " + ", ".join(entity.option_list()))
    return f" [{'; '.join(parts)}]" if parts else ""


def _no_target_message(
    target: str,
    area: str,
    domain: str,
    action: str,
    change: _Change,
    found: typing.List[_Entity],
) -> str:
    if found:
        names = ", ".join(e.label() for e in found[:5])
        hint = _capability_hint(found[0])
        if change.option and not hint:
            return f"{names} does not take a named setting like '{change.option}'."
        return f"Cannot '{action}' {names} — that device type does not support it.{hint}"
    described = target or " ".join(part for part in (area, domain) if part)
    return (
        f"No controllable device matching '{described}' in Home Assistant. "
        "Ask to list the devices to see the available names."
    )


_PAST_TENSE = {
    "on": "Turned on", "off": "Turned off", "toggle": "Toggled",
    "open": "Opened", "close": "Closed", "stop": "Stopped",
    "lock": "Locked", "unlock": "Unlocked", "start": "Started",
    "pause": "Paused", "dock": "Sent home", "home": "Sent home",
    "return": "Sent home", "locate": "Located", "play": "Started",
    "next": "Skipped", "previous": "Went back on", "run": "Ran",
    "arm": "Armed", "disarm": "Disarmed", "press": "Pressed",
}


def _verb(action: str, change: _Change) -> str:
    if change.wanted():
        return "Set"
    return _PAST_TENSE.get(action, f"Ran '{action}' on")


def _value_suffix(change: _Change, changed: typing.List[_Entity]) -> str:
    if change.option:
        return f" to {_spelling(changed[0], change.option)}"
    if change.temperature is not None:
        return f" to {change.temperature:g}"
    if change.value is None:
        return ""
    percent = all(
        (_VALUE_SETTINGS.get(e.domain) or _Setting("", "", None)).limits for e in changed
    )
    return f" to {change.value:g}%" if percent else f" to {change.value:g}"
