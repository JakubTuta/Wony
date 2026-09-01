"""Structured data for the screens that are not a conversation.

A job returns a sentence. That is the right answer in chat and the wrong one on
a screen: you cannot put a switch on a sentence, or a temperature into a gauge,
or tap the third line of a paragraph. A panel is the same information the job
would have described, handed over before it was turned into words.

Every panel is read-only, runs no model, and goes to the same API the job would
have. Tapping a tile is not a shortcut for typing the question — it is the same
work with the prose step skipped.

Adding one: write a `snapshot()` on the module (or a method on its service),
then add a line to _PANELS. The module gate and the error handling are here, so
the panel itself only has to fetch.
"""

import typing

from helpers.config import Config
from helpers.registry import ServiceRegistry


class PanelUnavailable(Exception):
    """The module behind this panel is switched off or never came up."""


def _service(module: str) -> typing.Any:
    instance = ServiceRegistry.get_service_instance(module)
    if instance is None:
        raise PanelUnavailable(f"{module} is enabled but did not start.")
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


# key -> (module that must be enabled, what to call)
_PANELS: typing.Dict[str, typing.Tuple[str, typing.Callable[[], dict]]] = {
    "weather": ("weather", _weather),
    "agenda": ("calendar", _agenda),
    "devices": ("home_assistant", _devices),
    "music": ("spotify", _music),
    "accounts": ("google_accounts", _accounts),
}


def panel(key: str) -> typing.Dict[str, typing.Any]:
    """Read one panel.

    Raises KeyError for an unknown key and PanelUnavailable when the module
    behind it is off — the two mean different things to the caller, and to the
    screen.
    """
    spec = _PANELS.get(key)
    if spec is None:
        raise KeyError(key)

    module_name, load = spec
    if module_name not in Config.enabled_modules():
        raise PanelUnavailable(f"{module_name} is not enabled.")
    return load()
