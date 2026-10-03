"""How the device itself is doing: disk, memory, processor, temperature, network.

Deliberately not `status`: that module reports on Wony (which of its features
work). This one reports on the machine Wony runs on, which is what "is the Pi
getting hot" and "how much space is left" are asking.

Battery is still read here — a Pi on a UPS HAT reports one — but nothing says
so on a device that has none.
"""

import typing

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement

# Below these, a warning is worth adding rather than just reading the number
# back. The disk and temperature triggers fire on the same figures
# (helpers/triggers.py), so the watcher and the report never disagree.
LOW_BATTERY_PERCENT = 20
LOW_DISK_PERCENT = 10

# A Pi 4 starts throttling itself at 80 °C and is already struggling before
# that; 70 is the point where saying something is still useful.
HIGH_TEMPERATURE_C = 70

# How long cpu_percent() samples for. The first call with no interval always
# answers 0.0, which reads as a broken machine; a short block gives a real
# number without a noticeable pause before the answer appears.
_CPU_SAMPLE_SECONDS = 0.3

_GIB = 1024 ** 3


@register_job(
    module_name="system",
    requires=Requirement(
        pip_modules=["psutil"],
        setup_hint="pip install -r requirements/system.txt",
    ),
    summary="Disk, memory, processor, temperature and network",
)
@capture_response
def device_health(
    what: typing.Literal["all", "disk", "memory", "cpu", "temperature", "network", "battery"] = "all",
) -> str:
    """
    [SYSTEM JOB] Reports how this device is doing: free disk space, memory and
    processor load, how hot it is running, and network status.

    Args:
        what (str): "all" (the default), "disk", "memory", "cpu", "temperature",
            "network" or "battery".

    Returns:
        str: A sentence per thing asked about.
    """
    wanted = (what or "all").strip().lower()
    readers: typing.Dict[str, typing.Callable[[], str]] = {
        "battery": _battery_line,
        "disk": _disk_line,
        "memory": _memory_line,
        "cpu": _cpu_line,
        "temperature": _temperature_line,
        "network": _network_line,
    }

    if wanted in ("all", ""):
        # Battery and temperature return "" on hardware that reports neither —
        # "this device has no battery" on every health check is noise.
        lines = [read() for read in readers.values()]
        return "\n".join(line for line in lines if line)

    read = readers.get(wanted) or readers.get(_ALIASES.get(wanted, ""))
    if read is None:
        return (
            f"Unknown option '{what}'. Use all, disk, memory, cpu, temperature, "
            "network or battery."
        )
    return read() or "This device does not report that."


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
    """Empty when there is no battery: the caller decides whether silence or a
    sentence is the right answer."""
    state = battery()
    if state is None:
        return ""

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


def temperature() -> typing.Optional[float]:
    """Hottest reported sensor in °C, or None where nothing reports one.

    psutil has no temperature support on Windows at all, and names the sensor
    differently per board, so the hottest reading is the only portable answer.
    """
    import psutil

    readings = getattr(psutil, "sensors_temperatures", None)
    if readings is None:
        return None
    try:
        groups = readings()
    except Exception:
        return None

    values = [
        entry.current
        for entries in groups.values()
        for entry in entries
        if entry.current
    ]
    return max(values) if values else None


def _temperature_line() -> str:
    reading = temperature()
    if reading is None:
        return ""
    line = f"Running at {round(reading)} °C"
    if reading >= HIGH_TEMPERATURE_C:
        line += " — hot enough to start slowing itself down"
    return line + "."


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
