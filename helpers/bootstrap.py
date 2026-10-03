"""
Shared startup / shutdown for all entry points (wony.py, tray_app.py).

Invariant: Config.load() runs before modules.employer is imported, because
decorator-based job registration reads config gates at import time.
"""

import atexit
import os
import signal
import sys
import threading
import typing

# On Windows, pip-installed nvidia packages (nvidia-cudnn-cu12, nvidia-cublas-cu12)
# place DLLs in site-packages/nvidia/*/bin/ which is NOT on the DLL search path by
# default. Register those dirs before anything imports onnxruntime so the CUDA
# provider can find cudnn64_9.dll / cublas64_12.dll without a system-wide install.
#
# add_dll_directory alone is not enough: onnxruntime loads onnxruntime_providers_cuda.dll
# with a search flag that does NOT resolve that DLL's transitive cudnn64_9.dll dependency
# from user-added dirs. Prepending to PATH covers that path (this is why TTS, which set
# PATH, loaded CUDA while fastembed, which did not, failed with "cudnn64_9.dll missing").
if sys.platform == "win32":
    import site

    for _sp in site.getsitepackages():
        _nvidia = os.path.join(_sp, "nvidia")
        if os.path.isdir(_nvidia):
            for _pkg in os.listdir(_nvidia):
                _bin = os.path.join(_nvidia, _pkg, "bin")
                if os.path.isdir(_bin):
                    os.add_dll_directory(_bin)
                    if _bin.lower() not in os.environ.get("PATH", "").lower():
                        os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")

# Silence onnxruntime's benign "Some nodes were not assigned to the preferred execution
# providers" warning (shape ops on CPU is intentional). Set before any ORT session is
# built by fastembed (semantic) or kokoro_onnx (TTS). 3 = ERROR.
try:
    import onnxruntime as _ort

    _ort.set_default_logger_severity(3)
except Exception:
    pass

_shutdown_done = False
_shutdown_lock = threading.Lock()

_idle_sweeper_thread: typing.Optional[threading.Thread] = None
_idle_sweeper_stop = threading.Event()

# How often failed modules are retried (helpers/health_watcher.py).
_HEALTH_CHECK_INTERVAL_MINUTES = 5.0

# Free the Whisper/Kokoro models again after this long unused, so an idle tray
# doesn't sit on GPU/RAM all day. Long enough that a normal back-and-forth never
# pays a reload. 0 would mean "never unload".
_IDLE_UNLOAD_MINUTES = 15.0

# Two weeks covers "it broke last week" without logs growing forever.
_LOG_KEEP_DAYS = 14


class BootstrapError(Exception):
    pass


def shutdown() -> None:
    """Idempotent shutdown: stop jobs, scheduler, close DB."""
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    _stop_idle_sweeper()

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

    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass

    try:
        from helpers import audio as _audio

        _audio.cleanup()
    except Exception:
        pass


def get_ai_client() -> typing.Any:
    """The AI provider's client, resolved lazily so pasting a key into
    Settings makes the next turn work without a restart.

    No key at all is a normal, expected state the first time Wony runs —
    the AI service's own __init__ fails and is caught by register_service,
    leaving it unregistered rather than crashing the app. Retrying the
    registration here is what picks up a key added since.
    """
    from helpers.registry import ServiceRegistry

    inst = ServiceRegistry.get_service_instance("ai")
    if inst is None:
        ServiceRegistry.reinitialize_module("ai")
        inst = ServiceRegistry.get_service_instance("ai")
    if inst is None:
        raise BootstrapError(
            "No AI service is set up yet. Open Settings → AI and paste a key from "
            "Anthropic or Google Gemini, or pick Ollama to run fully on this PC."
        )
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

    try:
        from helpers.logger import logger

        logger.cleanup_old_logs(_LOG_KEEP_DAYS)
    except Exception:
        pass

    from helpers.cache import Cache

    Cache.load_values()
    Cache.set_audio(audio)

    import dotenv

    dotenv.load_dotenv()

    from helpers.model import describe_readiness

    ai_ok, ai_msg = describe_readiness()
    if not ai_ok:
        # Degrade, don't disable: no AI key is how Wony looks the first time
        # it's ever run. The tray and web page still have to come up so there
        # is somewhere to paste one — modules.ai's own __init__ fails the same
        # way and is caught by register_service, so every other module still
        # loads; run_turn() gives a friendly answer until a key is added.
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

    _reconnect_mcp_servers(Config, quiet)
    _start_health_watcher(quiet)
    _start_triggers(quiet)
    _start_learning(quiet)
    if audio:
        _start_idle_sweeper()

    if not quiet:
        print()
        from helpers.health import print_startup_summary

        print_startup_summary(voice_mode=audio)
        print()

    return employer


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


def _start_idle_sweeper() -> None:
    """Periodic background thread, ticking every 60s, that unloads the
    STT/TTS models after _IDLE_UNLOAD_MINUTES of disuse (see
    helpers.recognizer.unload_if_idle / helpers.audio.unload_tts_if_idle).
    Nothing else currently needs a periodic sweep (media_pause needs no
    crash-recovery: it mutates no persistent state, so there's nothing to
    sweep for)."""
    global _idle_sweeper_thread
    if _idle_sweeper_thread is not None and _idle_sweeper_thread.is_alive():
        return

    idle_seconds = _IDLE_UNLOAD_MINUTES * 60.0
    if idle_seconds <= 0:
        return
    _idle_sweeper_stop.clear()

    def _loop() -> None:
        while not _idle_sweeper_stop.wait(60):
            try:
                from helpers.recognizer import unload_if_idle as _unload_stt
                _unload_stt(idle_seconds)
            except Exception:
                pass
            try:
                from helpers.audio import unload_tts_if_idle as _unload_tts
                _unload_tts(idle_seconds)
            except Exception:
                pass

    _idle_sweeper_thread = threading.Thread(target=_loop, daemon=True, name="background-safety-sweeper")
    _idle_sweeper_thread.start()


def _stop_idle_sweeper() -> None:
    _idle_sweeper_stop.set()
