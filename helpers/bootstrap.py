"""
Shared startup / shutdown for all entry points (wony.py, tray_app.py).

Invariant: Config.load() runs before modules.employer is imported, because
decorator-based job registration reads config gates at import time.
"""

import atexit
import signal
import sys
import threading
import typing

_shutdown_done = False
_shutdown_lock = threading.Lock()


class BootstrapError(Exception):
    pass


def shutdown() -> None:
    """Idempotent shutdown: stop jobs, scheduler, close DB."""
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    try:
        from helpers.health_watcher import stop as _watcher_stop

        _watcher_stop()
    except Exception:
        pass

    try:
        from helpers.jobs import BackgroundJobs

        BackgroundJobs.stop_all()
    except Exception:
        pass

    try:
        from helpers.registry import ServiceRegistry

        sched = ServiceRegistry.get_service_instance("scheduler")
        if sched is not None and hasattr(sched, "_sched"):
            sched._sched.shutdown(wait=False)
    except Exception:
        pass

    try:
        from helpers.memory_db import close as db_close

        db_close()
    except Exception:
        pass


def get_ai_client() -> typing.Any:
    from helpers.registry import ServiceRegistry

    inst = ServiceRegistry.get_service_instance("ai")
    if inst is None:
        raise BootstrapError("AI service not registered.")
    return inst.client


def bootstrap(
    audio: bool,
    *,
    install_signal_handlers: bool = True,
    seed_conversation: bool = False,
    quiet: bool = False,
) -> typing.Any:
    """
    Full startup sequence. Returns the Employer instance.

    audio: enable TTS + STT (sets Cache audio flag)
    install_signal_handlers: False in tray/thread mode (signal.signal off main thread raises)
    seed_conversation: pre-load recent DB turns into memory (for web/tray)
    quiet: suppress stdout health summary (pythonw has no console)
    """
    global _shutdown_done
    _shutdown_done = False

    from helpers.config import Config

    Config.load()

    from helpers.cache import Cache

    Cache.load_values()
    Cache.set_audio(audio)

    import dotenv

    dotenv.load_dotenv()

    from helpers.model import describe_readiness

    ai_ok, ai_msg = describe_readiness()
    if not ai_ok:
        raise BootstrapError(f"AI provider not ready.\n{ai_msg}")

    # Import Employer AFTER Config.load() so module decorators see correct gates.
    from modules.employer import Employer

    employer = Employer()

    atexit.register(shutdown)

    if install_signal_handlers:

        def _signal_handler(signum: int, frame: object) -> None:
            print(f"\nReceived signal {signum}, shutting down...")
            sys.exit(0)

        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _signal_handler)

    if seed_conversation:
        try:
            import time as _time

            from helpers.config import Config as _Cfg
            from helpers.conversation import Conversation as _Conv
            from helpers.memory_db import recent_turns as _recent_turns

            _max = int(_Cfg.get("ai.history.max_turns", 5))
            for _t in _recent_turns(_max):
                _Conv._turns.append(
                    {
                        "user": _t["user_text"],
                        "assistant": _t["assistant_text"],
                    }
                )
            _Conv._last_activity = _time.time()
        except Exception:
            pass

    _start_health_watcher(Config, quiet)

    if not quiet:
        print()
        from helpers.health import print_startup_summary

        print_startup_summary(voice_mode=audio)
        print()

    return employer


def _start_health_watcher(Config: typing.Any, quiet: bool) -> None:
    try:
        interval = float(Config.get("modules.health_check_interval_minutes", 5))
        if interval > 0:
            from helpers.health_watcher import start as _watcher_start

            _watcher_start(interval)
            if not quiet:
                print(
                    f"[health] Module recovery watcher started (every {interval:.0f} min)."
                )
    except Exception:
        pass
