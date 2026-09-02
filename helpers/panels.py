"""Structured data for the parts of the UI that are not a conversation.

A job returns a sentence. That is the right answer in chat and the wrong one in
a panel: you cannot put a switch on a sentence, or a temperature into a gauge.
A panel is the same information the job would have described, handed over
before it was turned into words.

Every panel is read-only and runs no model. Adding one: write a `snapshot()` on
the module (or a method on its service), then add a line to _PANELS.
"""

import typing

from helpers.config import Config
from helpers.registry import ServiceRegistry


class PanelUnavailable(Exception):
    """The module behind this panel is switched off or never came up."""


def _service(module: str) -> typing.Any:
    instance = ServiceRegistry.get_service_instance(module)
    if instance is None:
        # The registry already knows why it did not start ("No active Spotify
        # device found"), which beats making the reader go and look.
        _status, reason = ServiceRegistry.get_module_status().get(module, ("", ""))
        raise PanelUnavailable(
            f"{module} did not start: {reason}" if reason
            else f"{module} is enabled but did not start."
        )
    return instance


def _weather() -> typing.Dict[str, typing.Any]:
    from modules import weather

    return weather.snapshot()


def _agenda() -> typing.Dict[str, typing.Any]:
    return _service("calendar").agenda_snapshot()


def _devices() -> typing.Dict[str, typing.Any]:
    from modules import home_assistant

    return home_assistant.snapshot()


def _music() -> typing.Dict[str, typing.Any]:
    return _service("spotify").playback_snapshot()


def _accounts() -> typing.Dict[str, typing.Any]:
    return _service("google_accounts").accounts_snapshot()


class _Panel(typing.NamedTuple):
    module: str  # must be enabled for this panel to exist
    label: str
    load: typing.Callable[[], dict]


_PANELS: typing.Dict[str, _Panel] = {
    "weather": _Panel("weather", "Weather", _weather),
    "agenda": _Panel("calendar", "Today", _agenda),
    "devices": _Panel("home_assistant", "Devices", _devices),
    "music": _Panel("spotify", "Music", _music),
    "accounts": _Panel("google_accounts", "Accounts", _accounts),
}


def available() -> typing.List[typing.Dict[str, str]]:
    """Panels whose module is switched on, in declaration order."""
    enabled = Config.enabled_modules()
    return [
        {"key": key, "label": spec.label, "module": spec.module}
        for key, spec in _PANELS.items()
        if spec.module in enabled
    ]


def panel(key: str) -> typing.Dict[str, typing.Any]:
    """Read one panel.

    Raises KeyError for an unknown key and PanelUnavailable when the module
    behind it is off — those mean different things to the caller.
    """
    spec = _PANELS.get(key)
    if spec is None:
        raise KeyError(key)

    if spec.module not in Config.enabled_modules():
        raise PanelUnavailable(f"{spec.module} is not enabled.")

    try:
        return spec.load()
    except (KeyError, IndexError) as exc:
        # A loader indexing something missing must not reach the caller as the
        # KeyError above, which means "no such panel" and answers 404.
        raise RuntimeError(f"The {key} panel got an unexpected response: {exc}") from exc
