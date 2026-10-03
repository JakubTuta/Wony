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

# Two weeks covers "it broke last week" without logs growing forever.
_LOG_KEEP_DAYS = 14


class BootstrapError(Exception):
    pass


# Shown as the answer to a turn and as a notification on the screen, which has
# no chat and no key field of its own to say it in.
NO_AI_MESSAGE = (
    "No AI service is set up yet. On the device, run `./wony.sh setup configure` "
    "and add a key from Anthropic or Google Gemini, or point Wony at an Ollama server."
)


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
    """The AI provider's client, resolved lazily so a key added after startup
    works on the next turn without a restart.

    No key at all is a normal state the first time Wony runs: the AI service's
    own __init__ fails and register_service leaves it unregistered. Retrying
    here is what picks up a key written to .env since — by another process, so
    .env has to be read again.
    """
    from helpers.registry import ServiceRegistry

    inst = ServiceRegistry.get_service_instance("ai")
    if inst is None:
        import dotenv

        dotenv.load_dotenv(override=True)
        ServiceRegistry.reinitialize_module("ai")
        inst = ServiceRegistry.get_service_instance("ai")
    if inst is None:
        raise BootstrapError(NO_AI_MESSAGE)
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

        logger.cleanup_old_logs(_LOG_KEEP_DAYS)
    except Exception:
        pass

    from helpers.cache import Cache

    Cache.load_values()

    import dotenv

    dotenv.load_dotenv()

    from helpers.model import describe_readiness

    ai_ok, ai_msg = describe_readiness()
    if not ai_ok:
        # Degrade, don't disable: with no key the device still has to come up,
        # because timers, music and the smart home do not need one. The AI
        # service fails on its own and register_service leaves it unregistered;
        # run_turn() answers with NO_AI_MESSAGE until a key is added.
        import helpers.diagnostics

        helpers.diagnostics.add("warning", "AI", f"AI provider not ready: {ai_msg}")
        if not quiet:
            print(f"[AI] Not ready: {ai_msg}")

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
            from helpers.memory_db import visible_turns

            max_turns = int(Config.get("ai.history.max_turns", 5))
            for turn in visible_turns(max_turns):
                Conversation._turns.append(
                    {
                        "user": turn["user_text"],
                        "assistant": turn["assistant_text"],
                    }
                )
        except Exception:
            pass

    # A crash or a restart during deep sleep leaves the panel switched off with
    # nothing left that knows it. Turning it back on here is the difference
    # between a device that looks broken and one that just rebooted.
    try:
        from helpers import lowpower

        lowpower.reset_on_start()
    except Exception:
        pass

    if not ai_ok:
        _announce_missing_ai()
    _warn_if_web_exposed(Config)
    _start_health_watcher(quiet)
    _start_triggers(quiet)
    _start_learning(quiet)

    if not quiet:
        print()
        from helpers.health import print_startup_summary

        print_startup_summary()
        print()

    return employer


def _announce_missing_ai() -> None:
    """Put the missing AI service on the screen's bell. Not repeated on every
    restart while the first one is still unread."""
    try:
        from helpers.memory_db import all_notifications
        from helpers.notify import notify

        unread = all_notifications(include_acknowledged=False, limit=50)
        if not any(n.get("text") == NO_AI_MESSAGE for n in unread):
            notify(NO_AI_MESSAGE, kind="alert", source="ai")
    except Exception:
        pass


def _warn_if_web_exposed(Config: typing.Any) -> None:
    """Flag a web server bound beyond localhost.

    The HTTP API has no authentication: /api/invoke can run any registered job
    — send an email, delete a calendar event, power off the device, wipe the
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


def _start_triggers(quiet: bool) -> None:
    """Start the watcher thread. No-op while every trigger is off."""
    try:
        from helpers import triggers

        if triggers.start() and not quiet:
            print("[triggers] Watching for things worth mentioning.")
    except Exception:
        pass


def _start_learning(quiet: bool) -> None:
    """Start the memory pass. No-op unless assistant.memory.learn_from_my_data."""
    try:
        from helpers import learn

        if learn.start() and not quiet:
            print("[learn] Picking up facts from conversations.")
    except Exception:
        pass

