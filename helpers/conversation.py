import typing

# How many of the most recent turns carry their tool results forward as context.
# Deeper costs tokens on every request for data the model rarely revisits.
_TOOL_RESULT_TURNS = 2
# Per-result cap inside that block.
_TOOL_RESULT_MAX_CHARS = 800


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


def _format_calls(
    calls: typing.List[typing.Dict[str, typing.Any]],
    max_chars: int,
) -> str:
    """Format tool call results as a context block appended to assistant message."""
    lines = ["\n\n[Data retrieved this turn — reuse instead of re-calling tools:]"]
    for c in calls:
        name = c.get("name", "?")
        args = c.get("args") or {}
        result = str(c.get("result") or "").strip()
        if not result:
            continue
        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items()) if args else ""
        call_sig = f"{name}({arg_str})" if arg_str else name
        if len(result) > max_chars:
            result = result[:max_chars] + "…"
        lines.append(f"• {call_sig} → {result}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


class Conversation:
    _turns: typing.List[typing.Dict[str, typing.Any]] = []

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
        turns = cls._turns
        results_start = max(0, len(turns) - _TOOL_RESULT_TURNS)
        for i, turn in enumerate(turns):
            messages.append({"role": "user", "content": turn["user"]})
            assistant_content = turn["assistant"]
            if i >= results_start:
                calls = turn.get("calls") or []
                block = _format_calls(calls, _TOOL_RESULT_MAX_CHARS)
                if block:
                    assistant_content = assistant_content + block
            messages.append({"role": "assistant", "content": assistant_content})
        return messages

    @classmethod
    def record_turn(
        cls,
        user_text: str,
        assistant_text: str,
        calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
        emit: bool = True,
    ) -> typing.Optional[int]:
        enabled, max_turns = cls._config()
        if not enabled or not user_text:
            return None
        cls._turns.append({
            "user": user_text,
            "assistant": assistant_text or "",
            "calls": calls or [],
        })
        if len(cls._turns) > max_turns:
            cls._turns = cls._turns[-max_turns:]
        turn_id = _try_persist(user_text, assistant_text or "", calls=calls)
        if emit:
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
