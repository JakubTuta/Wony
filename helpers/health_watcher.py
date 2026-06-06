"""
Background health watcher — periodically retries failed/misconfigured modules.

When a module fails at startup (e.g. Spotify with no active device, a service
not yet running), the watcher re-attempts initialization every N minutes.
On success the module's jobs become available without an app restart.

Interval is read from modules.health_check_interval_minutes in config.yaml
(default 5, set to 0 to disable).
"""
import threading
import typing

_stop_event = threading.Event()
_thread: typing.Optional[threading.Thread] = None


def start(interval_minutes: float = 5.0) -> None:
    global _thread, _stop_event
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(interval_minutes,),
        daemon=True,
        name="health-watcher",
    )
    _thread.start()


def stop() -> None:
    _stop_event.set()


def _loop(interval_minutes: float) -> None:
    # Wait first so we don't retry immediately after a fresh startup failure.
    while not _stop_event.wait(interval_minutes * 60):
        _check_all()


def _check_all() -> None:
    try:
        from helpers.registry import ServiceRegistry
        retryable = ServiceRegistry.get_retryable_modules()
    except Exception:
        return

    for module_name in retryable:
        try:
            if ServiceRegistry.reinitialize_module(module_name):
                print(f"[health] '{module_name}' recovered — now enabled.")
        except Exception as exc:
            # Keep trying next cycle; don't crash the watcher thread.
            try:
                print(f"[health] reinit '{module_name}' failed: {exc}")
            except Exception:
                pass
