"""
Shared startup / shutdown for every entry point (wony.py kiosk, text, doctor).

Invariant: Config.load() runs before modules.employer is imported, because
decorator-based job registration reads config gates at import time.
"""

import atexit
import signal
import sys
import threading
import typing

# Silence onnxruntime's benign "Some nodes were not assigned to the preferred execution
# providers" warning (shape ops on CPU is intentional). Set before any ORT session is
# built by fastembed (semantic memory). 3 = ERROR.
try:
    import onnxruntime as _ort

    _ort.set_default_logger_severity(3)
except Exception:
    pass

_shutdown_done = False
_shutdown_lock = threading.Lock()

# How often failed modules are retried (helpers/health_watcher.py).
_HEALTH_CHECK_INTERVAL_MINUTES = 5.0


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
        from helpers.mcp_client import disconnect_all

        disconnect_all()
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
    *,
    install_signal_handlers: bool = True,
    seed_conversation: bool = False,
    quiet: bool = False,
) -> typing.Any:
    """
    Full startup sequence. Returns the Employer instance.

    install_signal_handlers: False off the main thread (signal.signal raises there)
    seed_conversation: pre-load recent DB turns into memory (for the kiosk)
    quiet: suppress the stdout health summary
    """
    global _shutdown_done
    _shutdown_done = False

    from helpers.config import Config

    Config.load()

    try:
        from helpers.logger import logger

        logger.cleanup_old_logs(int(Config.get("logging.keep_days", 14)))
    except Exception:
        pass

    from helpers.cache import Cache

    Cache.load_values()

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

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _signal_handler)

    if seed_conversation:
        try:
            from helpers.conversation import Conversation
            from helpers.memory_db import recent_turns

            max_turns = int(Config.get("ai.history.max_turns", 5))
            for turn in recent_turns(max_turns):
                Conversation._turns.append(
                    {
                        "user": turn["user_text"],
                        "assistant": turn["assistant_text"],
                    }
                )
        except Exception:
            pass

    _warn_if_web_exposed(Config)
    _reconnect_mcp_servers(Config, quiet)
    _start_health_watcher(quiet)

    if not quiet:
        print()
        from helpers.health import print_startup_summary

        print_startup_summary()
        print()

    return employer


def _warn_if_web_exposed(Config: typing.Any) -> None:
    """Flag a web server bound beyond localhost.

    The HTTP API has no authentication: /api/invoke can run any registered job
    — send an email, delete a calendar event, type on the desktop, wipe the
    database, exit the app. On 127.0.0.1 that is fine; on any other address it
    hands those to everyone who can reach the port.
    """
    host = str(Config.get("server.host", "127.0.0.1")).strip()
    if host in ("127.0.0.1", "localhost", "::1", ""):
        return
    import helpers.diagnostics

    helpers.diagnostics.add(
        "warning", "Server",
        f"Web API is bound to {host}, not localhost — anyone who can reach "
        f"port {Config.get('server.port', 8000)} can run any job without a password.",
        hint='Set server.host: "127.0.0.1" in config.yaml unless you have put '
             "the port behind your own authenticated proxy.",
    )


def _reconnect_mcp_servers(Config: typing.Any, quiet: bool) -> None:
    if not Config.is_module_enabled("mcp"):
        return
    try:
        from helpers.mcp_client import reconnect_enabled_servers
        reconnect_enabled_servers()
    except Exception as exc:
        if not quiet:
            print(f"[mcp] Startup reconnect failed (non-fatal): {exc}")


def _start_health_watcher(quiet: bool) -> None:
    try:
        from helpers.health_watcher import start as _watcher_start

        _watcher_start(_HEALTH_CHECK_INTERVAL_MINUTES)
        if not quiet:
            print(
                f"[health] Module recovery watcher started "
                f"(every {_HEALTH_CHECK_INTERVAL_MINUTES:.0f} min)."
            )
    except Exception:
        pass
