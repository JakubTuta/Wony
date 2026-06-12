import os
import threading
import time
import typing

_lock = threading.Lock()
_singleton: typing.Optional["AudioDucker"] = None

# System/audio-infrastructure PIDs to never touch.
_SKIP_NAMES = {"audiodg.exe", "system idle process", "system"}


def duck_others() -> "AudioDucker":
    global _singleton
    with _lock:
        if _singleton is None:
            _singleton = AudioDucker()
    return _singleton


class AudioDucker:
    """
    Context manager that lowers all other apps' audio while Wony is active.
    Enumerates ALL render devices (handles SteelSeries Sonar virtual devices,
    Spotify on non-default endpoints, etc.). Refcounted — nested
    `with duck_others():` blocks duck once and restore only when the outermost
    exits. Thread-safe. Fails silently if pycaw/comtypes missing or non-Windows.
    """

    _FADE_STEPS = 20
    # Duck fast so the assistant is audible immediately; restore gently.
    _DUCK_DURATION = 0.25
    _RESTORE_DURATION = 1.0

    def __init__(self) -> None:
        self._ref_lock = threading.Lock()
        self._refcount = 0
        # list of (ISimpleAudioVolume, original_float)
        self._snapshot: list = []
        self._own_pid = os.getpid()
        self._fade_cancel = threading.Event()

    def __enter__(self) -> "AudioDucker":
        with self._ref_lock:
            self._refcount += 1
            if self._refcount == 1:
                self._duck()
        return self

    def __exit__(self, *_: object) -> None:
        with self._ref_lock:
            self._refcount -= 1
            if self._refcount == 0:
                self._restore()

    def _fade(self, targets: list, duration: float) -> None:
        """Fade each (vol_iface, start, end) over `duration` seconds."""
        cancel = self._fade_cancel
        interval = duration / self._FADE_STEPS
        for step in range(1, self._FADE_STEPS + 1):
            if cancel.is_set():
                return
            t = step / self._FADE_STEPS
            for vol_iface, start, end in targets:
                try:
                    vol_iface.SetMasterVolume(start + (end - start) * t, None)
                except Exception:
                    pass
            time.sleep(interval)

    def _cancel_fade(self) -> None:
        self._fade_cancel.set()
        self._fade_cancel = threading.Event()

    def _duck(self) -> None:
        try:
            from helpers.config import Config
            if not bool(Config.get("voice.ducking.enabled", True)):
                return
            level = float(Config.get("voice.ducking.level", 0.15))
            self._snapshot = []
            targets = []
            for vol_iface in self._get_foreign_volumes():
                try:
                    current = vol_iface.GetMasterVolume()
                    target = min(current, level)
                    self._snapshot.append((vol_iface, current))
                    targets.append((vol_iface, current, target))
                except Exception:
                    pass
            self._cancel_fade()
            threading.Thread(
                target=self._fade, args=(targets, self._DUCK_DURATION), daemon=True
            ).start()
        except Exception:
            pass

    def _restore(self) -> None:
        try:
            targets = []
            for vol_iface, original_vol in self._snapshot:
                try:
                    current = vol_iface.GetMasterVolume()
                    targets.append((vol_iface, current, original_vol))
                except Exception:
                    pass
            self._cancel_fade()
            threading.Thread(
                target=self._fade, args=(targets, self._RESTORE_DURATION), daemon=True
            ).start()
        except Exception:
            pass
        finally:
            self._snapshot = []

    def _get_foreign_volumes(self) -> list:
        """Return ISimpleAudioVolume for every foreign session across all render devices."""
        try:
            import comtypes
            from comtypes import GUID
            from pycaw.pycaw import (
                IMMDeviceEnumerator,
                IAudioSessionManager2,
                IAudioSessionControl2,
                ISimpleAudioVolume,
            )

            CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator)
            # eRender=0, DEVICE_STATE_ACTIVE=1
            collection = enumerator.EnumAudioEndpoints(0, 1)
            device_count = collection.GetCount()

            result = []
            seen_pids: set = set()

            for i in range(device_count):
                try:
                    device = collection.Item(i)
                    mgr = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
                    mgr = mgr.QueryInterface(IAudioSessionManager2)
                    sess_enum = mgr.GetSessionEnumerator()
                    sess_count = sess_enum.GetCount()

                    for j in range(sess_count):
                        try:
                            ctrl = sess_enum.GetSession(j)
                            ctrl2 = ctrl.QueryInterface(IAudioSessionControl2)

                            # get PID — skip own process and system sessions
                            try:
                                pid = ctrl2.GetProcessId()
                            except Exception:
                                continue
                            if pid == self._own_pid or pid == 0:
                                continue
                            # skip audio infrastructure
                            try:
                                import psutil
                                name = psutil.Process(pid).name().lower()
                                if name in _SKIP_NAMES:
                                    continue
                            except Exception:
                                pass
                            # deduplicate — same app may appear on multiple virtual devices
                            if pid in seen_pids:
                                continue
                            seen_pids.add(pid)

                            vol = ctrl.QueryInterface(ISimpleAudioVolume)
                            result.append(vol)
                        except Exception:
                            continue
                except Exception:
                    continue

            return result
        except Exception:
            return []
