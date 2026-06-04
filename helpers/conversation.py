import time
import typing


class Conversation:
    _turns: typing.List[typing.Dict[str, str]] = []
    _last_activity: float = 0.0

    @classmethod
    def _config(cls) -> typing.Tuple[bool, int, float]:
        try:
            from helpers.config import Config
            enabled = Config.get("ai.history.enabled", True)
            max_turns = int(Config.get("ai.history.max_turns", 5))
            timeout_min = float(Config.get("ai.history.idle_timeout_minutes", 10))
        except Exception:
            enabled, max_turns, timeout_min = True, 5, 10.0
        return enabled, max_turns, timeout_min

    @classmethod
    def _maybe_expire(cls) -> None:
        _, _, timeout_min = cls._config()
        if cls._turns and cls._last_activity > 0:
            if time.time() - cls._last_activity > timeout_min * 60:
                cls._turns = []
                cls._last_activity = 0.0

    @classmethod
    def get_messages(cls) -> typing.List[typing.Dict[str, str]]:
        enabled, _, _ = cls._config()
        if not enabled:
            return []
        cls._maybe_expire()
        messages = []
        for turn in cls._turns:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})
        return messages

    @classmethod
    def record_turn(cls, user_text: str, assistant_text: str) -> None:
        enabled, max_turns, _ = cls._config()
        if not enabled or not user_text:
            return
        cls._maybe_expire()
        cls._turns.append({
            "user": user_text,
            "assistant": assistant_text or "",
        })
        if len(cls._turns) > max_turns:
            cls._turns = cls._turns[-max_turns:]
        cls._last_activity = time.time()

    @classmethod
    def clear(cls) -> None:
        cls._turns = []
        cls._last_activity = 0.0
