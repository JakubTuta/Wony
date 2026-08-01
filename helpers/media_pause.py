import asyncio
import atexit
import sys
import threading
import typing

import helpers.diagnostics

_lock = threading.Lock()
_singleton: typing.Optional["MediaPause"] = None

_IS_WINDOWS = sys.platform == "win32"


def pause_media() -> "MediaPause":
    global _singleton
    with _lock:
        if _singleton is None:
            _singleton = MediaPause()
    return _singleton


def resume_all() -> None:
    """Force any paused media back to playing, synchronously.

    Call on shutdown so nothing can stay paused if a resume was abandoned by
    process exit. Safe to call even if nothing is paused. Tray mode (which
    exits via os._exit, bypassing atexit) must call this explicitly.
    """
    s = _singleton
    if s is not None:
        s._force_resume_sync()


class MediaPause:
    """
    Context manager that pauses other apps' media playback (via Windows
    System Media Transport Controls) while Wony is active. Refcounted —
    nested `with pause_media():` blocks pause once and resume only when the
    outermost exits. Thread-safe.

    Replaces the old volume-ducking approach. Ducking had to persistently
    mutate per-app volume and then perfectly undo it across process kill,
    device switches, PID reuse, etc. — every one of those needed its own
    crash-recovery path, and it still leaked (apps left stuck at low volume
    with no visible sign anything was wrong). Pausing mutates nothing
    persistent: it's a command, not a setting we owe an undo for. A crash
    mid-turn leaves media paused, which is visible and fixed with one
    keypress — not silently stuck.

    All SMTC/WinRT work happens on one dedicated `media-pause-worker` thread
    running its own asyncio event loop, so no WinRT object crosses a thread
    boundary. __enter__/__exit__ only schedule coroutines and return
    immediately — no session-manager latency on the caller's hot path.

    Windows-only. On any other platform every operation is a no-op (see
    _IS_WINDOWS).
    """

    # A voice turn is several back-to-back `with pause_media():` blocks (wake
    # ack, capture, reply) plus continuous-conversation follow-ups. Resuming
    # between them would play/pause every session repeatedly — audible
    # pumping. Holding the pause briefly lets the next block reuse it, so one
    # turn pauses and resumes exactly once.
    _RESUME_LINGER = 3.0
    # Hard ceiling on how long anything may stay paused. If a turn hangs, or
    # a refcount is somehow leaked, resume anyway — nothing can be left
    # paused indefinitely.
    _MAX_PAUSE_SECONDS = 180.0

    def __init__(self) -> None:
        self._ref_lock = threading.RLock()
        self._refcount = 0
        self._loop: typing.Optional[asyncio.AbstractEventLoop] = None
        self._thread: typing.Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()

        # Only ever touched on the loop thread.
        self._active = False
        self._paused_aumids: typing.List[str] = []
        self._resume_handle: typing.Optional[asyncio.TimerHandle] = None
        self._watchdog_handle: typing.Optional[asyncio.TimerHandle] = None

        # Guarantee un-pause on normal interpreter exit (Ctrl+C, sys.exit).
        # os._exit (tray) bypasses this — that path calls resume_all() itself.
        atexit.register(self._force_resume_sync)

    def __enter__(self) -> "MediaPause":
        if not _IS_WINDOWS:
            return self
        with self._ref_lock:
            self._refcount += 1
            if self._refcount == 1:
                self._ensure_loop()
                from helpers.config import Config

                enabled = bool(Config.get("voice.media_pause.enabled", True))
                self._submit(self._on_enter(enabled))
        return self

    def __exit__(self, *_: object) -> None:
        if not _IS_WINDOWS:
            return
        with self._ref_lock:
            self._refcount -= 1
            if self._refcount == 0:
                self._submit(self._on_exit())

    # ── Loop plumbing ────────────────────────────────────────────────────

    def _ensure_loop(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            ready = threading.Event()

            def _run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    loop.close()

            self._thread = threading.Thread(target=_run, name="media-pause-worker", daemon=True)
            self._thread.start()
            ready.wait(2.0)

    def _submit(self, coro: typing.Coroutine) -> "typing.Optional[asyncio.Future]":
        if self._loop is None:
            return None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        fut.add_done_callback(self._log_task_exception)
        return fut

    def _log_task_exception(self, fut: "asyncio.Future") -> None:
        try:
            exc = fut.exception()
        except Exception:
            return
        if exc is not None:
            helpers.diagnostics.add("warning", "MediaPause", f"Background task failed: {exc}")

    def _force_resume_sync(self) -> None:
        """Full teardown: resume any paused media AND reset refcount.

        Used on process exit (atexit / tray teardown) only. Blocks briefly
        for the worker to finish. Safe to call even if nothing is paused or
        the worker was never started.
        """
        with self._thread_lock:
            loop = self._loop
            worker_alive = self._thread is not None and self._thread.is_alive()
        with self._ref_lock:
            self._refcount = 0
        if not worker_alive or loop is None:
            return

        done = threading.Event()

        async def _go() -> None:
            try:
                await self._do_resume_now()
            finally:
                done.set()

        try:
            asyncio.run_coroutine_threadsafe(_go(), loop)
        except Exception:
            return
        done.wait(2.0)

    # ── Loop-thread state machine ───────────────────────────────────────

    async def _on_enter(self, enabled: bool) -> None:
        if self._resume_handle is not None:
            self._resume_handle.cancel()
            self._resume_handle = None
        if self._active:
            return  # already paused and still held — don't re-pause
        if not enabled:
            return
        self._active = True
        self._paused_aumids = await self._do_pause()
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
        assert self._loop is not None
        self._watchdog_handle = self._loop.call_later(self._MAX_PAUSE_SECONDS, self._on_watchdog)

    async def _on_exit(self) -> None:
        if not self._active:
            return
        if self._resume_handle is not None:
            self._resume_handle.cancel()
        from helpers.config import Config

        linger = Config.get("voice.media_pause.resume_linger_seconds", None)
        linger = float(linger) if linger is not None else self._RESUME_LINGER
        assert self._loop is not None
        self._resume_handle = self._loop.call_later(linger, self._on_resume_deadline)

    def _on_resume_deadline(self) -> None:
        self._resume_handle = None
        assert self._loop is not None
        asyncio.ensure_future(self._do_resume_now(), loop=self._loop)

    def _on_watchdog(self) -> None:
        self._watchdog_handle = None
        helpers.diagnostics.add(
            "warning", "MediaPause",
            f"Paused media for over {int(self._MAX_PAUSE_SECONDS)}s — resuming anyway "
            "(a voice turn did not finish cleanly).",
        )
        assert self._loop is not None
        asyncio.ensure_future(self._do_resume_now(), loop=self._loop)

    async def _do_resume_now(self) -> None:
        if self._resume_handle is not None:
            self._resume_handle.cancel()
            self._resume_handle = None
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None
        aumids, self._paused_aumids = self._paused_aumids, []
        self._active = False
        if aumids:
            await self._resume_aumids(aumids)

    # ── WinRT/SMTC work ──────────────────────────────────────────────────

    async def _do_pause(self) -> typing.List[str]:
        session_manager_cls, playback_status_cls = _import_smtc()
        if session_manager_cls is None:
            return []

        try:
            mgr = await session_manager_cls.request_async()
            sessions = mgr.get_sessions()
        except Exception as e:
            helpers.diagnostics.add("warning", "MediaPause", f"Couldn't reach Windows media session manager: {e}")
            return []

        paused: typing.List[str] = []
        for session in sessions:
            try:
                info = session.get_playback_info()
                if info.playback_status != playback_status_cls.PLAYING:
                    continue
                if info.controls is not None and not info.controls.is_pause_enabled:
                    continue
                aumid = session.source_app_user_model_id
                await session.try_pause_async()
                paused.append(aumid)
            except Exception:
                continue
        return paused

    async def _resume_aumids(self, aumids: typing.List[str]) -> None:
        session_manager_cls, playback_status_cls = _import_smtc()
        if session_manager_cls is None:
            return

        try:
            mgr = await session_manager_cls.request_async()
            sessions = mgr.get_sessions()
        except Exception as e:
            helpers.diagnostics.add("warning", "MediaPause", f"Couldn't resume media — session manager unavailable: {e}")
            return

        wanted = set(aumids)
        for session in sessions:
            try:
                if session.source_app_user_model_id not in wanted:
                    continue
                info = session.get_playback_info()
                # Only resume what's still paused — if the user pressed play
                # themselves, or stopped it, leave it alone.
                if info.playback_status != playback_status_cls.PAUSED:
                    continue
                await session.try_play_async()
            except Exception:
                continue


_smtc_warned = False


def _import_smtc() -> "typing.Tuple[typing.Any, typing.Any]":
    """Import the WinRT SMTC types. Returns (None, None) if unavailable —
    missing on non-Windows and if the winrt packages aren't installed."""
    global _smtc_warned
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        )
        return SessionManager, PlaybackStatus
    except ImportError:
        if not _smtc_warned:
            _smtc_warned = True
            helpers.diagnostics.add(
                "info", "MediaPause",
                "winrt not installed — media won't be paused automatically while Wony speaks.",
                hint="pip install -r requirements/voice.txt",
            )
        return None, None
