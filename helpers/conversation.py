import typing


def _try_persist(
    user_text: str,
    assistant_text: str,
    calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
) -> typing.Optional[int]:
    try:
        from helpers.memory_db import insert_turn
        turn_id = insert_turn(user_text, assistant_text, calls=calls)
    except Exception:
        turn_id = None

    # Embed in background — never blocks the response path.
    try:
        from helpers import semantic
        if semantic.is_available() and turn_id is not None:
            semantic.store_turn(turn_id, user_text, assistant_text or "")
    except Exception:
        pass

    return turn_id


class Conversation:
    _turns: typing.List[typing.Dict[str, str]] = []

    @classmethod
    def _config(cls) -> typing.Tuple[bool, int]:
        try:
            from helpers.config import Config
            enabled = Config.get("ai.history.enabled", True)
            max_turns = int(Config.get("ai.history.max_turns", 5))
        except Exception:
            enabled, max_turns = True, 5
        return enabled, max_turns

    @classmethod
    def get_messages(cls) -> typing.List[typing.Dict[str, str]]:
        enabled, _ = cls._config()
        if not enabled:
            return []
        messages = []
        for turn in cls._turns:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})
        return messages

    @classmethod
    def record_turn(
        cls,
        user_text: str,
        assistant_text: str,
        calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
    ) -> typing.Optional[int]:
        enabled, max_turns = cls._config()
        if not enabled or not user_text:
            return None
        cls._turns.append({
            "user": user_text,
            "assistant": assistant_text or "",
        })
        if len(cls._turns) > max_turns:
            cls._turns = cls._turns[-max_turns:]
        turn_id = _try_persist(user_text, assistant_text or "", calls=calls)
        try:
            from helpers.events import emit_turn
            from datetime import datetime
            emit_turn({
                "id": turn_id,
                "user": user_text,
                "assistant": assistant_text or "",
                "calls": calls or [],
                "ts": datetime.now().isoformat(timespec="seconds"),
            })
        except Exception:
            pass
        return turn_id

    @classmethod
    def clear(cls) -> None:
        cls._turns = []
