"""Central diagnostics store. Deduplicates by (source, message) and fans out to console + event bus."""
import threading
import time
import typing

_lock = threading.Lock()
_records: typing.List[typing.Dict] = []
# Maps (source, message) → monotonic time of last emit; re-emits after TTL so recurring failures stay visible.
_seen: typing.Dict[typing.Tuple[str, str], float] = {}
_SEEN_TTL = 600.0  # 10 minutes


def add(
    level: str,
    source: str,
    message: str,
    hint: typing.Optional[str] = None,
) -> None:
    key = (source, message)
    with _lock:
        now = time.monotonic()
        if now - _seen.get(key, 0.0) < _SEEN_TTL:
            return
        _seen[key] = now
        record: typing.Dict = {
            "type": "diagnostic",
            "level": level,
            "source": source,
            "message": message,
            "hint": hint or "",
            "ts": time.strftime("%H:%M:%S"),
        }
        _records.append(record)

    prefix = {"info": "[i]", "warning": "[!]", "error": "[✗]"}.get(level, "[?]")
    line = f"{prefix} {source}: {message}"
    if hint:
        line += f"\n    Fix: {hint}"
    print(line)

    try:
        from helpers.events import emit
        emit(record)
    except Exception:
        pass

    # pythonw.exe (tray mode) has no console — print() above goes to a devnull
    # sink, so this is the only durable trace of the failure.
    try:
        from helpers.logger import logger
        full = f"{message} (hint: {hint})" if hint else message
        if level == "error":
            logger.log_error(full, context=source)
        else:
            logger.log_custom(f"diag_{level}", full)
    except Exception:
        pass


def get_all() -> typing.List[typing.Dict]:
    with _lock:
        return list(_records)


def clear() -> None:
    with _lock:
        _records.clear()
        _seen.clear()  # dict.clear() works on both old set and new dict
