import atexit
import json
import os
import queue
import threading
import time
import typing

import helpers.diagnostics

_lock = threading.Lock()
_singleton: typing.Optional["AudioDucker"] = None

# System/audio-infrastructure PIDs to never touch.
_SKIP_NAMES = {"audiodg.exe", "system idle process", "system"}

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Written only while a duck is actually in progress — a stale copy here means
# the process died mid-duck. Overwritten on every fresh duck, so it must never
# be used to hold anything else.
_SNAPSHOT_PATH = os.path.join(_REPO_ROOT, ".ducking_snapshot.json")
# Recovery entries whose app wasn't found live on a previous attempt, kept
# separately so a normal duck cycle (which rewrites _SNAPSHOT_PATH) can never
# clobber them. Retried by the periodic safety sweep until _MAX_RECOVERY_AGE_SECONDS.
_PENDING_RECOVERY_PATH = os.path.join(_REPO_ROOT, ".ducking_pending_recovery.json")


def duck_others() -> "AudioDucker":
    global _singleton
    with _lock:
        if _singleton is None:
            _singleton = AudioDucker()
    return _singleton


def _iter_foreign_sessions(own_pid: int) -> typing.Iterator[typing.Tuple[int, str, typing.Any]]:
    """Yield (pid, name, IAudioSessionControl) for every foreign audio session
    across ALL active render devices.

    COM must already be initialized on the calling thread. Deliberately NOT
    deduplicated by PID — see AudioDucker._get_foreign_volumes for why.
    """
    import comtypes
    import psutil
    from comtypes import GUID
    from pycaw.pycaw import (
        IAudioSessionControl2,
        IAudioSessionManager2,
        IMMDeviceEnumerator,
    )

    CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator)
    # eRender=0, DEVICE_STATE_ACTIVE=1
    collection = enumerator.EnumAudioEndpoints(0, 1)

    for i in range(collection.GetCount()):
        try:
            device = collection.Item(i)
            mgr = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            mgr = mgr.QueryInterface(IAudioSessionManager2)
            sess_enum = mgr.GetSessionEnumerator()
        except Exception:
            continue

        for j in range(sess_enum.GetCount()):
            try:
                ctrl = sess_enum.GetSession(j)
                ctrl2 = ctrl.QueryInterface(IAudioSessionControl2)
                try:
                    pid = ctrl2.GetProcessId()
                except Exception:
                    continue
                if pid == own_pid or pid == 0:
                    continue
                name = ""
                try:
                    name = psutil.Process(pid).name().lower()
                    if name in _SKIP_NAMES:
                        continue
                except Exception:
                    pass
                yield pid, name, ctrl
            except Exception:
                continue


def restore_all() -> None:
    """Force every ducked session back to its original volume, synchronously.

    Call on shutdown so audio can never stay ducked if a restore was abandoned
    by process exit. Safe to call even if nothing is ducked. Tray mode (which
    exits via os._exit, bypassing atexit) must call this explicitly.
    """
    s = _singleton
    if s is not None:
        s._force_restore_sync()


def recover_stale_snapshot() -> None:
    """Restore volumes recorded in either leftover snapshot file — the active-
    duck snapshot (a previous crash mid-duck) and/or the pending-recovery file
    (an earlier recovery attempt whose app wasn't found live yet). Called once
    at startup, and periodically as a safety net (see bootstrap.py's idle
    sweeper): the refcount==0 guard means a periodic call never fights an
    actually-active duck."""
    if not os.path.exists(_SNAPSHOT_PATH) and not os.path.exists(_PENDING_RECOVERY_PATH):
        return
    ducker = duck_others()
    with ducker._ref_lock:
        if ducker._refcount > 0:
            return  # actively ducking right now — don't interfere
    ducker._ensure_worker()
    for path in (_SNAPSHOT_PATH, _PENDING_RECOVERY_PATH):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except Exception:
            # Corrupt/partial file — remove it so it doesn't linger forever.
            try:
                os.remove(path)
            except Exception:
                pass
            continue
        ducker._cmd_q.put(("recover", snapshot, path))


class AudioDucker:
    """
    Context manager that lowers all other apps' audio while Wony is active.
    Enumerates ALL render devices (handles SteelSeries Sonar virtual devices,
    Spotify on non-default endpoints, etc.). Refcounted — nested
    `with duck_others():` blocks duck once and restore only when the outermost
    exits. Thread-safe.

    All COM work (enumeration, volume reads/writes, fades) happens on one
    dedicated `ducking-worker` thread so no COM interface ever crosses a
    thread boundary. __enter__/__exit__ only enqueue commands and return
    immediately — no COM/enumeration latency on the caller's hot path.

    Crash safety: before the first volume is ever lowered, the pre-duck
    snapshot is written to disk (see _SNAPSHOT_PATH). If the process is killed
    mid-duck, recover_stale_snapshot() restores those volumes on next startup.
    """

    _FADE_STEPS = 20
    # Duck fast so the assistant is audible immediately; restore gently.
    _DUCK_DURATION = 0.25
    _RESTORE_DURATION = 1.0
    # A voice turn is several back-to-back `with duck_others():` blocks (wake
    # ack, capture, reply). Restoring between them would fade every other app
    # up and straight back down — audible pumping. Holding the duck briefly
    # lets the next block reuse it, so one turn ducks and restores exactly once.
    _RESTORE_LINGER = 1.5
    # Hard ceiling on how long anything may stay ducked. If a turn hangs, or a
    # refcount is somehow leaked, the worker restores anyway — nothing can be
    # left quiet indefinitely.
    _MAX_DUCK_SECONDS = 120.0

    def __init__(self) -> None:
        self._ref_lock = threading.RLock()
        self._refcount = 0
        self._own_pid = os.getpid()
        self._cmd_q: "queue.Queue" = queue.Queue()
        self._worker: typing.Optional[threading.Thread] = None
        self._worker_lock = threading.Lock()
        # Guarantee un-duck on normal interpreter exit (Ctrl+C, sys.exit).
        # os._exit (tray) bypasses this — that path calls restore_all() itself.
        atexit.register(self._force_restore_sync)

    def __enter__(self) -> "AudioDucker":
        with self._ref_lock:
            self._refcount += 1
            if self._refcount == 1:
                self._ensure_worker()
                from helpers.config import Config

                if bool(Config.get("voice.ducking.enabled", True)):
                    level = float(Config.get("voice.ducking.level", 0.15))
                    self._cmd_q.put(("duck", level))
        return self

    def __exit__(self, *_: object) -> None:
        with self._ref_lock:
            self._refcount -= 1
            if self._refcount == 0:
                self._cmd_q.put(("restore",))

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_main, name="ducking-worker", daemon=True
            )
            self._worker.start()

    def _force_restore_sync(self) -> None:
        """Full teardown: restore every ducked session AND reset refcount.

        Used on process exit (atexit / tray teardown) only. Blocks briefly
        for the worker to finish. Safe to call even if nothing is ducked or
        the worker was never started.
        """
        with self._worker_lock:
            worker_alive = self._worker is not None and self._worker.is_alive()
        if worker_alive:
            done = threading.Event()
            self._cmd_q.put(("force_restore", done))
            done.wait(2.0)
        with self._ref_lock:
            self._refcount = 0

    # ── Worker thread — owns all COM ────────────────────────────────────────

    def _worker_main(self) -> None:
        try:
            import comtypes

            comtypes.CoInitialize()
        except Exception:
            pass

        snapshot: list = []  # [{"pid", "name", "iface", "orig"}]
        ducked_since: typing.Optional[float] = None
        restore_at: typing.Optional[float] = None  # deferred restore deadline

        def _restore_now() -> None:
            nonlocal snapshot, ducked_since, restore_at
            snapshot = self._do_restore(snapshot)
            restore_at = None
            ducked_since = None

        try:
            while True:
                # Wake for whichever deadline lands first, so a lingering
                # restore and the max-duck watchdog are both honoured even
                # while no commands arrive.
                deadlines = [d for d in (restore_at, (ducked_since + self._MAX_DUCK_SECONDS) if ducked_since else None) if d]
                timeout = max(0.05, min(deadlines) - time.monotonic()) if deadlines else None
                try:
                    cmd = self._cmd_q.get(timeout=timeout)
                except queue.Empty:
                    now = time.monotonic()
                    if restore_at is not None and now >= restore_at:
                        _restore_now()
                    elif ducked_since is not None and now - ducked_since >= self._MAX_DUCK_SECONDS:
                        helpers.diagnostics.add(
                            "warning", "Ducking",
                            f"Ducked for over {int(self._MAX_DUCK_SECONDS)}s — restoring volumes anyway "
                            "(a voice turn did not finish cleanly).",
                        )
                        _restore_now()
                    continue

                try:
                    kind = cmd[0]
                    if kind == "duck":
                        restore_at = None  # cancel a pending linger
                        if snapshot:
                            continue  # already ducked and still held — don't re-fade
                        snapshot = self._do_duck(cmd[1], snapshot)
                        ducked_since = time.monotonic() if snapshot else None
                    elif kind == "restore":
                        # Deferred — see _RESTORE_LINGER.
                        restore_at = time.monotonic() + self._RESTORE_LINGER if snapshot else None
                    elif kind == "force_restore":
                        _restore_now()
                        cmd[1].set()
                    elif kind == "recover":
                        self._do_recover(cmd[1], cmd[2])
                except Exception as e:
                    # The worker owns every COM interface we hold; if it dies,
                    # nothing can ever restore those volumes in-process. Never
                    # let one bad command take it down — unduck and carry on.
                    helpers.diagnostics.add("error", "Ducking", f"Worker command '{cmd[0]}' failed: {e}")
                    try:
                        _restore_now()
                    except Exception:
                        pass
                    if cmd[0] == "force_restore":
                        try:
                            cmd[1].set()
                        except Exception:
                            pass
        finally:
            try:
                import comtypes

                comtypes.CoUninitialize()
            except Exception:
                pass

    def _rescue_stale_snapshot_before_duck(self) -> None:
        """Restore a crashed run's volumes BEFORE capturing new originals.

        _SNAPSHOT_PATH only exists while a duck is in progress, so finding one
        here — with nothing ducked in this worker — means a previous run died
        mid-duck and its apps are still sitting at the duck level. Ducking on
        top of that would record 0.15 as the "original", write it over the
        crash snapshot (which is always fully overwritten), and then faithfully
        restore 0.15 and delete the file — losing the true volume permanently
        and leaving the user quietly ducked forever. Observed live.

        _do_recover also moves anything it can't match to the pending-recovery
        file, so the originals survive even if the app isn't running yet.
        """
        if not os.path.exists(_SNAPSHOT_PATH):
            return
        try:
            with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                stale = json.load(f)
        except Exception:
            self._delete_snapshot_file()
            return
        helpers.diagnostics.add(
            "warning", "Ducking",
            "Found volumes stranded by a previous run — restoring them before ducking.",
        )
        self._do_recover(stale, _SNAPSHOT_PATH)

    def _do_duck(self, level: float, prev_snapshot: list) -> list:
        try:
            # Flush any lingering restore fade to true originals first, so we
            # never snapshot a mid-fade volume as a session's "original".
            if prev_snapshot:
                self._flush_snapshot(prev_snapshot)
            else:
                self._rescue_stale_snapshot_before_duck()

            targets = self._get_foreign_volumes()
            snapshot = []
            fade_targets = []
            for pid, name, iface in targets:
                try:
                    current = iface.GetMasterVolume()
                    target = min(current, level)
                    snapshot.append({"pid": pid, "name": name, "iface": iface, "orig": current})
                    fade_targets.append((iface, current, target))
                except Exception:
                    continue

            # Persist BEFORE any volume is written — this is what makes a
            # hard-kill mid-duck recoverable on next startup.
            self._write_snapshot_file(snapshot, level)
            self._fade_inline(fade_targets, self._DUCK_DURATION)
            return snapshot
        except Exception as e:
            helpers.diagnostics.add("warning", "Ducking", f"Duck failed: {e}")
            return prev_snapshot

    def _do_restore(self, snapshot: list) -> list:
        if not snapshot:
            return []
        try:
            fade_targets = []
            for entry in snapshot:
                try:
                    current = entry["iface"].GetMasterVolume()
                except Exception:
                    current = entry["orig"]
                fade_targets.append((entry["iface"], current, entry["orig"]))

            self._fade_inline(fade_targets, self._RESTORE_DURATION)

            # Guarantee the exact original is applied even if the fade was
            # preempted partway (e.g. a new duck interrupted it).
            failed = []
            for entry in snapshot:
                if not self._set_volume_with_retry(entry):
                    failed.append(entry)

            if failed:
                self._write_snapshot_file(failed, None)
                helpers.diagnostics.add(
                    "warning", "Ducking",
                    f"Could not restore {len(failed)} app volume(s) — device may have changed.",
                )
            else:
                self._delete_snapshot_file()
            return failed
        except Exception as e:
            helpers.diagnostics.add("error", "Ducking", f"Restore failed — some apps may remain ducked: {e}")
            return snapshot

    # Give up retrying a recovery record after this long — the app it refers
    # to is presumed gone for good; retrying forever would mean a stale
    # record from a long-closed app lingers and gets re-checked every sweep.
    _MAX_RECOVERY_AGE_SECONDS = 24 * 60 * 60

    def _do_recover(self, parsed_snapshot: typing.Any, source_path: str) -> None:
        sessions = parsed_snapshot.get("sessions", []) if isinstance(parsed_snapshot, dict) else []
        duck_level = parsed_snapshot.get("duck_level") if isinstance(parsed_snapshot, dict) else None
        created_epoch = parsed_snapshot.get("created_epoch") if isinstance(parsed_snapshot, dict) else None
        if not sessions:
            self._delete_file(source_path)
            return

        if created_epoch is not None and time.time() - created_epoch > self._MAX_RECOVERY_AGE_SECONDS:
            helpers.diagnostics.add(
                "warning", "Ducking",
                f"Discarding a {len(sessions)}-session crash-recovery record older than 24h — app(s) presumed gone.",
            )
            self._delete_file(source_path)
            return

        live = self._get_foreign_volumes()
        # A PID can have multiple independent live sessions (see
        # _get_foreign_volumes docstring) — keep all of them per key, and
        # track which ones have already been used so two snapshot entries
        # never restore the same live session twice.
        by_pid: typing.Dict[int, list] = {}
        by_name: typing.Dict[str, list] = {}
        for pid, name, iface in live:
            by_pid.setdefault(pid, []).append(iface)
            by_name.setdefault(name, []).append((pid, iface))
        claimed: set = set()
        threshold = (duck_level if duck_level is not None else 0.15) + 0.02

        recovered = 0
        unrecovered = []
        for sess in sessions:
            pid = sess.get("pid")
            name = (sess.get("name") or "").lower()
            vol = sess.get("volume")
            if vol is None:
                continue

            iface = None
            for cand in by_pid.get(pid, []):
                if id(cand) not in claimed:
                    iface = cand
                    break
            if iface is None:
                # PID reused/changed (e.g. reboot) — only "fix" sessions that
                # currently look stuck low, so we never clobber a volume the
                # user set deliberately in the meantime.
                for cand_pid, cand_iface in by_name.get(name, []):
                    if id(cand_iface) in claimed:
                        continue
                    try:
                        if cand_iface.GetMasterVolume() <= threshold:
                            iface = cand_iface
                            break
                    except Exception:
                        continue

            if iface is not None:
                claimed.add(id(iface))
                try:
                    iface.SetMasterVolume(vol, None)
                    recovered += 1
                except Exception:
                    unrecovered.append(sess)
            else:
                # App wasn't running (or was already fine) this time — keep the
                # record so a later recovery attempt (next startup, or the
                # periodic safety sweep) can still catch it if it reappears
                # stuck low. Dropping it here would lose it permanently.
                unrecovered.append(sess)

        # Entries we couldn't match live always move to the pending-recovery
        # file (never back to source_path) — if source_path was the active
        # snapshot, that path must stay reserved for "currently ducking" only.
        self._delete_file(source_path)
        if unrecovered:
            self._write_recovery_snapshot(unrecovered, duck_level, created_epoch)
        if recovered:
            helpers.diagnostics.add(
                "info", "Ducking", f"Recovered {recovered} stranded app volume(s) from a previous crash."
            )

    def _flush_snapshot(self, snapshot: list) -> None:
        for entry in snapshot:
            self._set_volume_with_retry(entry)
        self._delete_snapshot_file()

    def _set_volume_with_retry(self, entry: dict) -> bool:
        try:
            entry["iface"].SetMasterVolume(entry["orig"], None)
            return True
        except Exception:
            pass
        # Interface may be stale (default device changed mid-duck) — re-resolve
        # this session by PID and retry once.
        for pid, _name, iface in self._get_foreign_volumes():
            if pid == entry["pid"]:
                try:
                    iface.SetMasterVolume(entry["orig"], None)
                    return True
                except Exception:
                    break
        return False

    def _fade_inline(self, targets: list, duration: float) -> bool:
        """Fade each (iface, start, end) over `duration` seconds, inline on the
        worker thread. Aborts early (returning True) if another command is
        already queued, so duck/restore ordering never backs up behind a fade."""
        if not targets:
            return False
        interval = duration / self._FADE_STEPS
        for step in range(1, self._FADE_STEPS + 1):
            if not self._cmd_q.empty():
                return True
            t = step / self._FADE_STEPS
            for iface, start, end in targets:
                try:
                    iface.SetMasterVolume(start + (end - start) * t, None)
                except Exception:
                    pass
            time.sleep(interval)
        return False

    def _write_snapshot_file(self, snapshot: list, duck_level: typing.Optional[float]) -> None:
        """Write the active-duck snapshot (_SNAPSHOT_PATH) — the "currently
        ducking, crash-recover me" marker. Always fully overwritten: it must
        only ever describe the current duck, never accumulate history."""
        if not snapshot:
            return
        self._write_snapshot_data(
            _SNAPSHOT_PATH,
            {
                "version": 1,
                "pid": self._own_pid,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "created_epoch": time.time(),
                "duck_level": duck_level,
                "sessions": [
                    {"pid": e["pid"], "name": e.get("name", ""), "volume": e["orig"]}
                    for e in snapshot
                ],
            },
        )

    def _write_recovery_snapshot(
        self, sessions: list, duck_level: typing.Optional[float], created_epoch: typing.Optional[float] = None
    ) -> None:
        """Merge unrecovered entries into the pending-recovery file (never the
        active snapshot) so a later attempt (next startup, or the periodic
        safety sweep) can retry them — and so two recovery attempts landing
        back-to-back can never clobber each other's still-pending entries."""
        if not sessions:
            return
        existing_sessions: list = []
        existing_epoch: typing.Optional[float] = None
        try:
            if os.path.exists(_PENDING_RECOVERY_PATH):
                with open(_PENDING_RECOVERY_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict):
                    existing_sessions = existing.get("sessions", []) or []
                    existing_epoch = existing.get("created_epoch")
        except Exception:
            pass

        # De-dupe by (pid, name) — a fresh retry attempt's volume value wins
        # over a stale one already on disk for the same app.
        merged: typing.Dict[typing.Tuple[typing.Any, str], dict] = {}
        for sess in existing_sessions + sessions:
            key = (sess.get("pid"), (sess.get("name") or "").lower())
            merged[key] = sess

        # Oldest known created_epoch wins, so the 24h staleness clock tracks
        # from when an entry first became unrecoverable, not the last retry.
        epochs = [e for e in (created_epoch, existing_epoch) if e is not None]
        merged_epoch = min(epochs) if epochs else time.time()

        self._write_snapshot_data(
            _PENDING_RECOVERY_PATH,
            {
                "version": 1,
                "pid": self._own_pid,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "created_epoch": merged_epoch,
                "duck_level": duck_level,
                "sessions": list(merged.values()),
            },
        )

    def _write_snapshot_data(self, path: str, data: dict) -> None:
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception:
            pass

    def _delete_snapshot_file(self) -> None:
        self._delete_file(_SNAPSHOT_PATH)

    def _delete_file(self, path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _get_foreign_volumes(self) -> list:
        """Return (pid, name, ISimpleAudioVolume) for every foreign session across all render devices.

        Deliberately NOT deduplicated by PID: a single process can hold
        genuinely independent session objects on multiple devices at once
        (observed live: a game had 10 separate sessions across a SteelSeries
        Sonar virtual-routing setup, only one of which was actually playing
        audio at non-default volume). Ducking/restoring only the first one
        found per PID left the others un-managed — usually harmless since
        they're already at 1.0, but if the "representative" session picked
        during duck ever failed to restore, the real one stayed silently
        stuck with no way back. Setting the same volume on every session for
        a PID is idempotent, so there's no downside to controlling all of them.
        """
        try:
            from pycaw.pycaw import ISimpleAudioVolume

            result = []
            for pid, name, ctrl in _iter_foreign_sessions(self._own_pid):
                try:
                    result.append((pid, name, ctrl.QueryInterface(ISimpleAudioVolume)))
                except Exception:
                    continue
            return result
        except Exception:
            return []
