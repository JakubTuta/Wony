"""The labwc session the touch panel runs in.

labwc is started with its own config directory (kiosk/session): no desktop, no
frames, no shortcuts. Used alone that would also throw away what the person set
up in Raspberry Pi's Screen Configuration, and the touchscreen is where it
shows: labwc rotates touch events with the screen only through a libinput
`calibrationMatrix` in rc.xml, so a rotated display would draw sideways-right
and tap sideways-wrong. So the config labwc is given is built at each start: the
repo's own, plus the touch and input settings from the user's rc.xml.

Standard library only: wony.py runs this before anything else is loaded.
"""
import os
import shlex
import shutil
import sys
import typing
import xml.etree.ElementTree as ET

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE_DIR = os.path.join(_REPO_ROOT, "kiosk", "session")

# What is carried over from the user's rc.xml: how the input devices behave and
# which screen each belongs to. Their keybindings, theme and window rules stay out.
_CARRIED = ("touch", "libinput", "tablet")
# Everything else the session directory needs, copied as it is.
_COPIED = ("autostart", "environment")


def _local(tag: str) -> str:
    """An element's name without its namespace (some rc.xml files declare one)."""
    return tag.rsplit("}", 1)[-1]


def user_rc_file() -> typing.Optional[str]:
    """The rc.xml labwc would read for this user, or None: their own, else the
    system one. labwc reads only the first it finds, and so does this."""
    home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    system = [d for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(os.pathsep) if d]
    for base in [home] + system:
        path = os.path.join(base, "labwc", "rc.xml")
        if os.path.isfile(path):
            return path
    return None


def _input_settings(path: typing.Optional[str]) -> typing.List[ET.Element]:
    if not path:
        return []
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        print(f"[session] Could not read {path} ({error}); touch settings left at their defaults.", file=sys.stderr)
        return []
    found = [element for element in root if _local(element.tag) in _CARRIED]
    for element in found:
        for node in element.iter():
            node.tag = _local(node.tag)
    return found


def build(dest: str) -> str:
    """Write the session's config into `dest` and return it."""
    os.makedirs(dest, exist_ok=True)
    for name in _COPIED:
        shutil.copyfile(os.path.join(_BASE_DIR, name), os.path.join(dest, name))

    tree = ET.parse(os.path.join(_BASE_DIR, "rc.xml"))
    root = tree.getroot()
    carried = _input_settings(user_rc_file())
    for name in {_local(element.tag) for element in carried}:
        for old in [e for e in root if _local(e.tag) == name]:
            root.remove(old)
    root.extend(carried)
    ET.indent(tree)
    tree.write(os.path.join(dest, "rc.xml"), encoding="utf-8", xml_declaration=True)
    return dest


def config_dir() -> str:
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "wony", "session")


def command(python: str, script: str) -> typing.List[str]:
    """labwc, in the config built above, running the panel as its one program.
    labwc exits when the panel does, so a closed or crashed panel ends the
    session and systemd starts it again."""
    labwc = shutil.which("labwc") or "/usr/bin/labwc"
    panel = shlex.join([python, script, "panel"])
    return [labwc, "-C", build(config_dir()), "-S", panel]
