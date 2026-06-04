import json
import typing


class Cache:
    _filename = "cache.json"
    _values = {}

    @staticmethod
    def load_values() -> None:
        try:
            with open(Cache._filename, "r") as file:
                Cache._values = json.load(file)
        except FileNotFoundError:
            with open(Cache._filename, "w") as file:
                json.dump({}, file, indent=4)
                Cache._values = {}
        except json.JSONDecodeError:
            with open(Cache._filename, "w") as file:
                json.dump({}, file, indent=4)
                Cache._values = {}

    @staticmethod
    def get_values() -> dict:
        if not len(Cache._values):
            Cache.load_values()

        return Cache._values

    @staticmethod
    def set_value(key: str, value: typing.Any) -> None:
        Cache._values[key] = value

        with open(Cache._filename, "w") as file:
            json.dump(Cache._values, file, indent=4)

    @staticmethod
    def get_value(key: str, default=None) -> typing.Any:
        if not len(Cache._values):
            Cache.load_values()

        return Cache._values.get(key, default)

    @staticmethod
    def set_audio(value: bool) -> None:
        Cache.set_value("audio", value)

    @staticmethod
    def get_audio() -> bool:
        return Cache.get_value("audio", default=False)

    @staticmethod
    def set_local(value: bool) -> None:
        Cache.set_value("local", value)

    @staticmethod
    def get_local() -> bool:
        return Cache.get_value("local", default=False)
