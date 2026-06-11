import os
import threading
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

    def __init__(self) -> None:
        self._ref_lock = threading.Lock()
        self._refcount = 0
        # list of (ISimpleAudioVolume, original_float)
        self._snapshot: list = []
        self._own_pid = os.getpid()

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

    def _duck(self) -> None:
        try:
            from helpers.config import Config
            if not bool(Config.get("voice.ducking.enabled", True)):
                return
            level = float(Config.get("voice.ducking.level", 0.15))
            self._snapshot = []
            for vol_iface in self._get_foreign_volumes():
                try:
                    current = vol_iface.GetMasterVolume()
                    self._snapshot.append((vol_iface, current))
                    vol_iface.SetMasterVolume(min(current, level), None)
                except Exception:
                    pass
        except Exception:
            pass

    def _restore(self) -> None:
        try:
            for vol_iface, original_vol in self._snapshot:
                try:
                    vol_iface.SetMasterVolume(original_vol, None)
                except Exception:
                    pass
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
