import json
import os
import threading
import typing

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cache:
    # Repo-root anchored, not CWD — launching from another directory used to
    # fork a second cache file.
    _filename = os.path.join(_REPO_ROOT, "cache.json")
    _values = {}
    _loaded = False
    _lock = threading.Lock()

    @staticmethod
    def load_values() -> None:
        # Explicit utf-8 both ways: Python's default on Windows is the ANSI code
        # page, so a cached value with any non-ASCII character (a device name, a
        # voice name) round-trips wrong or raises on read.
        try:
            with open(Cache._filename, "r", encoding="utf-8") as file:
                Cache._values = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            with open(Cache._filename, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)
                Cache._values = {}
        Cache._loaded = True

    @staticmethod
    def get_values() -> dict:
        if not Cache._loaded:
            Cache.load_values()

        return Cache._values

    @staticmethod
    def set_value(key: str, value: typing.Any) -> None:
        with Cache._lock:
            Cache._values[key] = value
            tmp = Cache._filename + ".tmp"
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(Cache._values, file, indent=4)
            os.replace(tmp, Cache._filename)

    @staticmethod
    def get_value(key: str, default=None) -> typing.Any:
        if not Cache._loaded:
            Cache.load_values()

        return Cache._values.get(key, default)
