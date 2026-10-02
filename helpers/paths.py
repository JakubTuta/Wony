"""Repo-root anchored paths.

Every data file Wony owns (db, cache, credentials, logs, models) must resolve
against the repo, not the process CWD — the tray is launched by Task Scheduler
and `wony.py text` can be run from anywhere, and both used to fork their own
copy of wony.db / cache.json wherever they happened to start.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_path(*parts: str) -> str:
    """Join `parts` under the repo root."""
    return os.path.join(REPO_ROOT, *parts)


def downloads_dir() -> str:
    """The user's Downloads folder, wherever Windows has moved it."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
        folder = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        found = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(found)) == 0:  # type: ignore[attr-defined]
            path = found.value or ""
            ctypes.windll.ole32.CoTaskMemFree(found)  # type: ignore[attr-defined]
            if path:
                return path
    return os.path.join(os.path.expanduser("~"), "Downloads")


def resolve(path: str) -> str:
    """Resolve a config-supplied path: absolute stays, relative anchors to repo."""
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
