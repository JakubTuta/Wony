"""How the computer itself is doing: battery, disk, memory, processor, network.

Deliberately not `status`: that module reports on Wony (which of its features
work). This one reports on the machine Wony runs on, which is what "how much
battery have I got" is asking — and you cannot see the tray icon from across
the room.
"""

import typing

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement

# Below this, a warning is worth saying out loud rather than just reading the
# number back. Also what the battery/disk triggers fire on (helpers/triggers.py).
LOW_BATTERY_PERCENT = 20
LOW_DISK_PERCENT = 10

# How long cpu_percent() samples for. The first call with no interval always
# answers 0.0, which reads as a broken machine; a short block gives a real
# number without a noticeable pause in a spoken reply.
_CPU_SAMPLE_SECONDS = 0.3

_GIB = 1024 ** 3


@register_job(
    module_name="system",
    requires=Requirement(
        pip_modules=["psutil"],
        setup_hint="pip install -r requirements/system.txt",
    ),
    summary="Battery, disk, memory and network",
)
@capture_response
def computer_health(
    what: typing.Literal["all", "battery", "disk", "memory", "cpu", "network"] = "all",
) -> str:
    """
    [SYSTEM JOB] Reports how this computer is doing: battery level and whether it is
    charging, free disk space, memory and processor load, and network status.

    Args:
        what (str): "all" (the default), "battery", "disk", "memory", "cpu" or
            "network".

    Returns:
        str: A sentence per thing asked about.
    """
    wanted = (what or "all").strip().lower()
    readers: typing.Dict[str, typing.Callable[[], str]] = {
        "battery": _battery_line,
        "disk": _disk_line,
        "memory": _memory_line,
        "cpu": _cpu_line,
        "network": _network_line,
    }

    if wanted in ("all", ""):
        return "\n".join(read() for read in readers.values())

    read = readers.get(wanted) or readers.get(_ALIASES.get(wanted, ""))
    if read is None:
        return f"Unknown option '{what}'. Use all, battery, disk, memory, cpu or network."
    return read()


_ALIASES = {
    "power": "battery",
    "storage": "disk",
    "space": "disk",
    "ram": "memory",
    "processor": "cpu",
    "internet": "network",
    "wifi": "network",
}


# ------------------------------------------------------------------ readings


def battery() -> typing.Optional[typing.Dict[str, typing.Any]]:
    """Battery state, or None on a machine that has no battery."""
    import psutil

    state = psutil.sensors_battery()
    if state is None:
        return None
    return {
        "percent": round(state.percent),
        "plugged_in": bool(state.power_plugged),
        # psutil reports -1/-2 for "unlimited" and "unknown"; both mean there is
        # no estimate to pass on.
        "minutes_left": (
            round(state.secsleft / 60) if isinstance(state.secsleft, int) and state.secsleft >= 0
            else None
        ),
    }


def disks() -> typing.List[typing.Dict[str, typing.Any]]:
    """Every fixed drive with space figures, largest shortfall first."""
    import psutil

    found = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            # An empty card reader or optical drive is listed but not readable.
            continue
        found.append({
            "mount": part.mountpoint,
            "free_gb": round(usage.free / _GIB, 1),
            "total_gb": round(usage.total / _GIB, 1),
            "free_percent": round(100 - usage.percent),
        })
    found.sort(key=lambda d: d["free_percent"])
    return found


def _battery_line() -> str:
    state = battery()
    if state is None:
        return "This computer has no battery — it runs on mains power."

    line = f"Battery is at {state['percent']}%"
    line += ", charging" if state["plugged_in"] else ", on battery"
    if state["minutes_left"] is not None and not state["plugged_in"]:
        hours, minutes = divmod(state["minutes_left"], 60)
        left = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        line += f", about {left} left"
    if not state["plugged_in"] and state["percent"] <= LOW_BATTERY_PERCENT:
        line += " — worth plugging in"
    return line + "."


def _disk_line() -> str:
    drives = disks()
    if not drives:
        return "I couldn't read any drives."
    return "\n".join(
        f"Drive {d['mount']}: {d['free_gb']} GB free of {d['total_gb']} GB ({d['free_percent']}%)."
        for d in drives
    )


def _memory_line() -> str:
    import psutil

    memory = psutil.virtual_memory()
    return (
        f"Memory is {round(memory.percent)}% used — "
        f"{round(memory.available / _GIB, 1)} GB free of {round(memory.total / _GIB, 1)} GB."
    )


def _cpu_line() -> str:
    import psutil

    load = psutil.cpu_percent(interval=_CPU_SAMPLE_SECONDS)
    return f"Processor is at {round(load)}% across {psutil.cpu_count(logical=True)} cores."


def _network_line() -> str:
    import psutil

    # Loopback is up on a machine with the cable unplugged and the wifi off, so
    # counting it would report a connection that does not exist.
    up = [
        name for name, stats in psutil.net_if_stats().items()
        if stats.isup and not name.lower().startswith(("loopback", "lo"))
    ]
    if not up:
        return "No network connection."
    return f"{len(up)} network connection(s) up: {', '.join(sorted(up))}."
