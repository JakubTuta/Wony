import json
import threading
import typing
from datetime import datetime

from helpers.untrusted import truncate, unfence, without_fenced

# How many of the most recent turns carry their tool results forward as context.
# Deeper costs tokens on every request for data the model rarely revisits.
_TOOL_RESULT_TURNS = 2
# Per-result cap inside that block.
_TOOL_RESULT_MAX_CHARS = 800
# Results that are stale by the next turn. Offered as "reuse this", yesterday's
# clock reading made the model correct itself against the prompt's live clock.
_NEVER_REUSED = {"get_datetime"}
# Each past message is stamped with when it was said, so a date or time in an
# old reply reads as history rather than as a claim about now.
_STAMP_FORMAT = "%a %b %d, %H:%M"
# Stands where the user's message would be, ahead of something Wony said on its
# own, so the model reads what follows as its own words and not as an answer.
_UNPROMPTED = "(Nobody asked. You said this on your own: {source}.)"

# Turns trimmed off the window are folded into a short summary, a few at a time
# (one model call per batch), so a long chat does not forget how it started.
_SUMMARIZE_EVERY = 3
_MAX_SUMMARY_CHARS = 800
_SUMMARY_PROMPT = (
    "You keep a running summary of a conversation between a personal assistant and"
    " its user, for the assistant's own reference. Update it with the exchanges"
    " below. Keep what later turns may need: what the user asked for, decisions,"
    " names, numbers, and anything still open. Under 100 words, plain prose, no"
    " preamble.\n\nSummary so far: {previous}\n\nNew exchanges:\n{turns}"
)


def sanitize_calls(
    calls: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Ensure every call is JSON-serializable (coerce non-serializable args to str).

    record_turn stores calls as JSON; one unserializable argument would
    otherwise drop the whole turn from the database without a word.
    """
    safe = []
    for c in calls:
        safe_args: typing.Dict[str, typing.Any] = {}
        for k, v in (c.get("args") or {}).items():
            try:
                json.dumps(v)
                safe_args[k] = v
            except (TypeError, ValueError):
                safe_args[k] = str(v)
        entry = {"name": c.get("name", ""), "args": safe_args, "result": str(c.get("result", ""))}
        if c.get("needs_confirm"):
            entry["needs_confirm"] = True
        safe.append(entry)
    return safe


def _try_persist(
    user_text: str,
    assistant_text: str,
    calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
    source: str = "",
) -> typing.Optional[int]:
    try:
        from helpers.memory_db import insert_turn
        turn_id = insert_turn(user_text, assistant_text, calls=calls, source=source)
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
        if name in _NEVER_REUSED:
            continue
        args = c.get("args") or {}
        result = str(c.get("result") or "").strip()
        if not result:
            continue
        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items()) if args else ""
        call_sig = f"{name}({arg_str})" if arg_str else name
        result = truncate(result, max_chars)
        lines.append(f"• {call_sig} → {result}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


class Conversation:
    _turns: typing.List[typing.Dict[str, typing.Any]] = []
    _dropped: typing.List[typing.Dict[str, typing.Any]] = []
    _summary: str = ""
    # Bumped by clear(), so a summary still being written lands nowhere.
    _generation: int = 0
    _summarizing = threading.Lock()
    # Not agent_lock: notify() records from any thread, including a job's
    # mid-turn, where agent_lock is already held by that same thread.
    _lock = threading.Lock()

    @classmethod
    def _max_turns(cls) -> int:
        try:
            from helpers.config import Config
            return int(Config.get("ai.history.max_turns", 5))
        except Exception:
            return 5

    @classmethod
    def get_messages(cls) -> typing.List[typing.Dict[str, str]]:
        """The history as the model gets it — with no phone number in it
        (helpers/private_numbers.py); the turns themselves keep the digits."""
        from helpers.private_numbers import hide

        messages = []
        turns = cls._turns
        results_start = max(0, len(turns) - _TOOL_RESULT_TURNS)
        for i, turn in enumerate(turns):
            if turn.get("source"):
                user_content = _UNPROMPTED.format(source=turn["source"])
            else:
                user_content = hide(turn["user"])
            if turn.get("at"):
                user_content = f"[{turn['at'].strftime(_STAMP_FORMAT)}] {user_content}"
            messages.append({"role": "user", "content": user_content})
            assistant_content = turn["assistant"]
            if i >= results_start:
                calls = turn.get("calls") or []
                block = _format_calls(calls, _TOOL_RESULT_MAX_CHARS)
                if block:
                    assistant_content = assistant_content + block
            messages.append({"role": "assistant", "content": hide(assistant_content)})
        return messages

    @classmethod
    def record_turn(
        cls,
        user_text: str,
        assistant_text: str,
        calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
        emit: bool = True,
    ) -> typing.Optional[int]:
        if not user_text:
            return None
        return cls._record(user_text, assistant_text or "", calls or [], "", emit)

    @classmethod
    def record_notice(cls, text: str, source: str) -> typing.Optional[int]:
        """Something Wony said without being asked (helpers/notify.py), kept
        in order with the turns so "what time is that?" has something to refer
        to. `source` names who raised it ("scheduler", "trigger:new_event")."""
        if not text:
            return None
        return cls._record("", text, [], source or "notification", emit=True)

    @classmethod
    def _record(
        cls,
        user_text: str,
        assistant_text: str,
        calls: typing.List[typing.Dict[str, typing.Any]],
        source: str,
        emit: bool,
    ) -> typing.Optional[int]:
        max_turns = cls._max_turns()
        said_at = datetime.now()
        with cls._lock:
            cls._turns.append({
                "user": user_text,
                "assistant": assistant_text,
                "calls": calls,
                "source": source,
                "at": said_at,
            })
            fold = False
            if len(cls._turns) > max_turns:
                cls._dropped.extend(cls._turns[:-max_turns])
                cls._turns = cls._turns[-max_turns:]
                fold = len(cls._dropped) >= _SUMMARIZE_EVERY
        if fold:
            threading.Thread(target=cls._fold, daemon=True, name="conversation-summary").start()
        turn_id = _try_persist(user_text, assistant_text, calls=calls, source=source)
        if emit:
            try:
                from helpers.events import emit_turn
                emit_turn({
                    "id": turn_id,
                    "user": unfence(user_text),
                    "assistant": unfence(assistant_text),
                    "calls": calls,
                    "source": source,
                    "ts": said_at.isoformat(timespec="seconds"),
                })
            except Exception:
                pass
        return turn_id

    @classmethod
    def recent_job_names(cls) -> typing.List[str]:
        """Jobs called in the turns whose results the model still sees — a
        follow-up ("read it", "yes") is usually about one of them."""
        return [
            call.get("name", "")
            for turn in cls._turns[-_TOOL_RESULT_TURNS:]
            for call in turn.get("calls") or []
        ]

    @classmethod
    def record_confirmed(cls, job_name: str, args: typing.Dict[str, typing.Any], result: str) -> bool:
        """A call the model asked about was confirmed with the web page's button.
        Without this the history still says "NOT DONE", and the next turn tries
        again or tells the user it never happened."""
        from helpers.confirm import normalize

        wanted = normalize(job_name, args)
        for turn in reversed(cls._turns):
            for call in turn.get("calls") or []:
                if (
                    call.get("needs_confirm")
                    and call.get("name") == job_name
                    and normalize(job_name, call.get("args") or {}) == wanted
                ):
                    call.pop("needs_confirm")
                    call["result"] = result
                    turn["assistant"] += f"\n(The user confirmed this with the button. Result: {result})"
                    return True
        return False

    @classmethod
    def summary(cls) -> str:
        """What happened earlier in this chat than the turns still in the window."""
        return cls._summary

    @classmethod
    def _fold(cls) -> None:
        """Fold the trimmed turns into the summary. Runs off the reply path."""
        if not cls._summarizing.acquire(blocking=False):
            return  # the running fold picks these up next time
        try:
            generation = cls._generation
            with cls._lock:
                pending, cls._dropped = cls._dropped, []
            if not pending:
                return
            # Fenced text stays out: a summary is read as Wony's own notes, and
            # an email's instructions must not turn into those.
            from helpers.private_numbers import hide

            def exchange(t: typing.Dict[str, typing.Any]) -> str:
                said = without_fenced(t["assistant"])[:600]
                if t.get("source"):
                    return f"Assistant, unprompted ({t['source']}): {said}"
                return f"User: {without_fenced(t['user'])}\nAssistant: {said}"

            turns = hide("\n".join(exchange(t) for t in pending))
            from helpers.model import ask_plain

            folded = ask_plain(_SUMMARY_PROMPT.format(previous=cls._summary or "(nothing yet)", turns=turns)).strip()
            if folded and generation == cls._generation:
                cls._summary = folded[:_MAX_SUMMARY_CHARS]
        except Exception as e:
            from helpers.logger import logger

            logger.log_error(str(e), "conversation.summary")
        finally:
            cls._summarizing.release()

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._turns = []
            cls._dropped = []
        cls._summary = ""
        cls._generation += 1
