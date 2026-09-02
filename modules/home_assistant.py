"""Home Assistant control over its REST API.

Entity resolution lives here rather than in the prompt: one /api/template
render returns the whole entity/name/area/state index, which /api/states
cannot do — areas live in the entity registry and REST does not expose it.
That keeps the two tool schemas tiny no matter how big the house is.
"""
import os
import typing
from dataclasses import dataclass

import requests

from helpers import net
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement

_TOKEN_ENV = "HOME_ASSISTANT_TOKEN"

# \x1f (unit separator) cannot occur in a device name; '|' can.
_SEP = "\x1f"
_INDEX_TEMPLATE = (
    "{% for s in states %}{{ s.entity_id }}\x1f{{ s.name }}\x1f"
    "{{ area_name(s.entity_id) or '' }}\x1f{{ s.state }}\x1f"
    "{{ s.attributes.get('device_class', '') }}\x1f"
    "{{ s.attributes.get('brightness', '') }}\n{% endfor %}"
)
_INDEX_FIELDS = 6

# Service calls block until Home Assistant has run the handler; the default
# 8s read timeout would report failure for a command that actually landed.
_SERVICE_TIMEOUT = (3.0, 15.0)

# A vague target ("light") can match half the house. Above this, ask instead
# of acting — an unwanted mass switch-off is not something the user can undo
# by saying "no".
_MAX_CONTROL_TARGETS = 12

_MAX_LISTED = 60

_GENERIC_ACTIONS = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}

_DOMAIN_ACTIONS: typing.Dict[str, typing.Dict[str, str]] = {
    "cover": {
        "on": "open_cover", "open": "open_cover", "off": "close_cover",
        "close": "close_cover", "stop": "stop_cover", "toggle": "toggle",
    },
    "lock": {
        "on": "lock", "lock": "lock", "close": "lock",
        "off": "unlock", "unlock": "unlock", "open": "unlock",
    },
    "alarm_control_panel": {
        "on": "alarm_arm_away", "arm": "alarm_arm_away",
        "off": "alarm_disarm", "disarm": "alarm_disarm",
    },
    "button": {"on": "press", "press": "press"},
}

_CONTROLLABLE = {
    "light", "switch", "fan", "cover", "lock", "climate", "media_player",
    "scene", "script", "automation", "input_boolean", "humidifier", "vacuum",
    "siren", "water_heater", "button", "valve", "alarm_control_panel",
}

# Physical-security devices — a misheard command here has consequences the
# other domains don't. Gated behind modules.home_assistant.allow_locks.
_GUARDED_DOMAINS = {"lock", "alarm_control_panel"}
_GUARDED_COVER_CLASSES = {"garage", "gate", "door"}


@dataclass
class _Entity:
    entity_id: str
    name: str
    area: str
    state: str
    device_class: str
    # Home Assistant reports light brightness as 0-255, and only while lit.
    brightness: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    def label(self) -> str:
        return f"{self.name} ({self.area})" if self.area else self.name

    def brightness_percent(self) -> typing.Optional[int]:
        try:
            return round(int(self.brightness) / 255 * 100)
        except ValueError:
            return None


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

    entities = []
    for line in response.text.splitlines():
        parts = line.split(_SEP)
        if len(parts) == _INDEX_FIELDS:
            entities.append(_Entity(*[part.strip() for part in parts]))
    return entities


def _tokens(text: str) -> typing.List[str]:
    cleaned = text.lower().replace("_", " ").replace(".", " ")
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
        haystack = set(name_tokens) | set(_tokens(entity.area)) | set(_tokens(entity.entity_id))
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
    [HOME ASSISTANT JOB] Lists smart-home devices and their current state. This is the
    single tool for both discovery ("what devices do I have", "what's in the kitchen")
    and for reading state ("is the garage door open", "what's the bedroom temperature",
    "did I leave a light on"). With no arguments it lists the whole house.

    Args:
        query (str): Name to look for, e.g. 'garage door', 'bedroom lamp'.
        area (str): Restrict to one room, e.g. 'kitchen', 'living room'.
        domain (str): Restrict to one device type: light, switch, sensor, binary_sensor,
                      climate, cover, lock, media_player, scene, script.

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

    found.sort(key=lambda e: (e.area, e.name))
    lines = [f"{e.label()}: {e.state}" for e in found[:_MAX_LISTED]]
    if len(found) > _MAX_LISTED:
        lines.append(f"...and {len(found) - _MAX_LISTED} more.")
    return "\n".join(lines)


@register_job(module_name="home_assistant", requires=_requirement())
@capture_response
def control_home_device(
    target: str = "",
    action: str = "on",
    area: str = "",
    domain: str = "",
    brightness_percent: typing.Optional[int] = None,
    temperature: typing.Optional[float] = None,
    position_percent: typing.Optional[int] = None,
) -> str:
    """
    [HOME ASSISTANT JOB] Controls smart-home devices through Home Assistant: lights,
    switches, blinds, thermostats, locks, media players, scenes and scripts. Device
    names are resolved here, so pass what the user said ('the bedroom lamp') rather
    than an entity id. Give target, or area/domain, or both.

    Args:
        target (str): What to control, as the user named it, e.g. 'bedroom lamp'.
        action (str): on, off, toggle, open, close, stop, lock, unlock, arm, disarm.
        area (str): Restrict to one room. Use with an empty target for 'all the
                    lights in the kitchen'.
        domain (str): Restrict to one device type: light, switch, cover, lock, climate,
                      media_player, scene, script.
        brightness_percent (int): 1-100. Implies lights and turning them on.
        temperature (float): Target temperature. Implies a thermostat.
        position_percent (int): 0-100 for blinds/covers, 0 is fully closed.

    Returns:
        str: What was changed, or why it could not be.
    """
    if not (target or area or domain):
        return "Say which device, room or device type to control."

    wanted = (action or "on").strip().lower()
    domain = domain or _implied_domain(wanted, brightness_percent, temperature, position_percent)

    try:
        entities = _fetch_index()
    except (requests.exceptions.RequestException, ValueError) as exc:
        return _failure(exc, "control_home_device")

    found = [e for e in _filtered(entities, target, area, domain) if e.domain in _CONTROLLABLE]
    actionable = [e for e in found if _service_for(e.domain, wanted)]
    if not actionable:
        return _no_target_message(target, area, domain, wanted, found)

    _, text = _apply(
        actionable,
        wanted,
        _service_data(brightness_percent, temperature, position_percent),
    )
    return text


def _apply(
    actionable: typing.List[_Entity],
    action: str,
    extra: typing.Dict[str, typing.Any],
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

    if len(actionable) > _MAX_CONTROL_TARGETS:
        return False, (
            f"That matches {len(actionable)} devices — too many to change at once. "
            "Name a room or a specific device."
        )

    changed, failures = [], []
    for entity_domain, group in _by_domain(actionable).items():
        try:
            _call_service(
                entity_domain,
                _resolve_service(entity_domain, action, extra),
                [e.entity_id for e in group],
                extra,
            )
            changed.extend(group)
        except (requests.exceptions.RequestException, ValueError) as exc:
            logger.log_error(str(exc), "home_assistant_apply")
            failures.extend(group)

    if not changed:
        return False, (
            f"Home Assistant refused the command for "
            f"{', '.join(e.label() for e in failures)}."
        )

    summary = f"{_verb(action, extra)} {', '.join(e.label() for e in changed)}{_value_suffix(extra)}."
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


def snapshot(domain: str = "") -> typing.Dict[str, typing.Any]:
    """Controllable devices grouped by room, for the devices panel.

    Not a job: list_home_devices writes 'Name (room): state', which cannot be
    turned back into a switch. Same index, kept as fields.
    """
    entities = _index_or_fail("home_assistant_snapshot")
    wanted = domain.strip().lower()

    by_area: typing.Dict[str, typing.List[typing.Dict[str, typing.Any]]] = {}
    for entity in entities:
        if entity.domain not in _CONTROLLABLE:
            continue
        if wanted and entity.domain != wanted:
            continue
        by_area.setdefault(entity.area or "", []).append(
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "domain": entity.domain,
                "state": entity.state,
                # Anything not plainly off — 'playing', 'open', 'unlocked' —
                # shows as on.
                "on": entity.state not in ("off", "closed", "locked", "unavailable", "unknown"),
                "available": entity.state not in ("unavailable", "unknown"),
                "brightness": entity.brightness_percent(),
                "dimmable": entity.domain == "light",
                # Guarded devices are shown and refused, so the UI can say why
                # rather than silently hiding the front door.
                "guarded": _is_guarded(entity),
            }
        )

    areas = [
        {"name": area, "devices": sorted(devices, key=lambda d: d["name"])}
        for area, devices in sorted(by_area.items(), key=lambda kv: (kv[0] == "", kv[0]))
    ]
    return {"areas": areas, "locks_allowed": _locks_allowed()}


def control(
    entity_id: str,
    action: str = "toggle",
    brightness_percent: typing.Optional[int] = None,
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
    if not _service_for(entity.domain, wanted):
        return False, (
            f"Cannot '{wanted}' {entity.label()} — that device type does not support it."
        )

    return _apply([entity], wanted, _service_data(brightness_percent, None, None))


# ── control helpers ───────────────────────────────────────────────────────────


def _implied_domain(
    action: str,
    brightness: typing.Optional[int],
    temperature: typing.Optional[float],
    position: typing.Optional[int],
) -> str:
    """An extra parameter or a domain-specific verb pins the device type, which
    is what keeps 'set the kitchen to 30%' off the kitchen's motion sensors."""
    if brightness is not None:
        return "light"
    if temperature is not None:
        return "climate"
    if position is not None:
        return "cover"
    if action in ("lock", "unlock"):
        return "lock"
    if action in ("arm", "disarm"):
        return "alarm_control_panel"
    return ""


def _service_for(domain: str, action: str) -> str:
    return _DOMAIN_ACTIONS.get(domain, _GENERIC_ACTIONS).get(action, "")


def _resolve_service(domain: str, action: str, extra: typing.Dict[str, typing.Any]) -> str:
    """Setting a value has its own service — it is not turn_on carrying data."""
    if domain == "cover" and "position" in extra:
        return "set_cover_position"
    if domain == "climate" and "temperature" in extra:
        return "set_temperature"
    return _service_for(domain, action)


def _is_guarded(entity: _Entity) -> bool:
    if entity.domain in _GUARDED_DOMAINS:
        return True
    return entity.domain == "cover" and entity.device_class in _GUARDED_COVER_CLASSES


def _by_domain(entities: typing.List[_Entity]) -> typing.Dict[str, typing.List[_Entity]]:
    grouped: typing.Dict[str, typing.List[_Entity]] = {}
    for entity in entities:
        grouped.setdefault(entity.domain, []).append(entity)
    return grouped


def _service_data(
    brightness: typing.Optional[int],
    temperature: typing.Optional[float],
    position: typing.Optional[int],
) -> typing.Dict[str, typing.Any]:
    data: typing.Dict[str, typing.Any] = {}
    if brightness is not None:
        data["brightness_pct"] = max(1, min(100, int(brightness)))
    if temperature is not None:
        data["temperature"] = float(temperature)
    if position is not None:
        data["position"] = max(0, min(100, int(position)))
    return data


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


def _no_target_message(
    target: str, area: str, domain: str, action: str, found: typing.List[_Entity]
) -> str:
    if found:
        names = ", ".join(e.label() for e in found[:5])
        return f"Cannot '{action}' {names} — that device type does not support it."
    described = target or " ".join(part for part in (area, domain) if part)
    return (
        f"No controllable device matching '{described}' in Home Assistant. "
        "Ask to list the devices to see the available names."
    )


_PAST_TENSE = {
    "on": "Turned on", "off": "Turned off", "toggle": "Toggled",
    "open": "Opened", "close": "Closed", "stop": "Stopped",
    "lock": "Locked", "unlock": "Unlocked",
    "arm": "Armed", "disarm": "Disarmed", "press": "Pressed",
}


def _verb(action: str, extra: typing.Dict[str, typing.Any]) -> str:
    if extra:
        return "Set"
    return _PAST_TENSE.get(action, f"Ran '{action}' on")


def _value_suffix(extra: typing.Dict[str, typing.Any]) -> str:
    if "brightness_pct" in extra:
        return f" to {extra['brightness_pct']}%"
    if "position" in extra:
        return f" to {extra['position']}%"
    if "temperature" in extra:
        return f" to {extra['temperature']}"
    return ""
