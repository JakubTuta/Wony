"""
One agent turn, from text in to text out.

Every input path on this device — the console REPL, POST /api/chat, the
WebSocket chat, a typed message from the touch screen — runs through
run_turn(). It owns the things that must not be duplicated per caller: the
process-wide agent lock, the cancel signal, the wall-clock backstop, and the
translation of a failure into something a human can read.

Recording the turn into Conversation is deliberately left to the caller: the
WebSocket path needs the turn id and needs to suppress the automatic broadcast
so it can send one enriched with its session id.
"""

import threading
import typing

# How many tool calls the agent may chain before it has to answer. Deep enough
# for the real chains ("read that email, then put it in my calendar"), shallow
# enough that a confused model can't spend a minute looping.
MAX_AGENT_STEPS = 5

# Wall-clock backstop for one turn (LLM + tool calls). Checked between agent
# steps and before each tool call — not a hard preempt of a call already in
# flight, which is what the AI client / helpers.net timeouts are for. Without
# it a stuck tool loop holds agent_lock, and so every other turn, until the
# process is restarted.
_TURN_TIMEOUT_SECONDS = 120.0


class TurnResult(typing.NamedTuple):
    text: str
    calls: typing.List[typing.Dict[str, typing.Any]]
    # True when the turn was cut short by the backstop above. `text` still
    # carries something useful (the last tool result, or an apology).
    timed_out: bool
    # Set when the turn failed outright. `text` is the same message, so a
    # caller that only wants something to show can ignore this field.
    error: typing.Optional[str]


def run_turn(
    user_input: str,
    on_text: typing.Optional[typing.Callable[[str], None]] = None,
) -> TurnResult:
    """Run one agent turn. Never raises — failures come back in TurnResult.error."""
    from helpers.agent import run_agent
    from helpers.bootstrap import get_ai_client
    from helpers.conversation import Conversation
    from helpers.decorators import agent_lock, set_agent_active
    from helpers.events import clear_cancel, emit_state, session_cancel
    from helpers.registry import ServiceRegistry
    from modules.ai import build_agent_system_prompt

    timed_out = threading.Event()
    timer = threading.Timer(_TURN_TIMEOUT_SECONDS, timed_out.set)
    timer.daemon = True

    class _TurnCancel:
        @staticmethod
        def is_set() -> bool:
            return session_cancel.is_set() or timed_out.is_set()

    emit_state("thinking")
    agent_result = None
    agent_err: typing.Optional[Exception] = None

    try:
        with agent_lock:
            # Inside the lock: a cancel raised against a previous turn must not
            # abort this one, but clearing it before acquiring could cancel a
            # turn that is still running.
            clear_cancel()
            set_agent_active(True)
            timer.start()
            try:
                agent_result = run_agent(
                    client=get_ai_client(),
                    user_input=user_input,
                    available_jobs=ServiceRegistry.get_all_jobs(),
                    system_instructions=build_agent_system_prompt(),
                    history=Conversation.get_messages(),
                    max_steps=MAX_AGENT_STEPS,
                    on_text=on_text,
                    cancel_event=_TurnCancel(),
                )
            except Exception as exc:
                agent_err = exc
            finally:
                timer.cancel()
                set_agent_active(False)
    finally:
        emit_state("idle")

    if agent_err is not None:
        return TurnResult(text=_describe_failure(agent_err), calls=[],
                          timed_out=False, error=_describe_failure(agent_err))

    if timed_out.is_set() and not agent_result.text:
        import helpers.diagnostics

        helpers.diagnostics.add(
            "warning", "AI",
            f"Turn exceeded {_TURN_TIMEOUT_SECONDS:.0f}s — aborted.",
        )
        # A tool did run and returned something before the clock ran out —
        # showing that beats showing an apology.
        fallback = ""
        for call in reversed(agent_result.calls):
            result = (call.get("result") or "").strip()
            if result:
                fallback = result
                break
        return TurnResult(
            text=fallback or "Sorry, that took too long — I'm stopping there.",
            calls=agent_result.calls,
            timed_out=True,
            error=None,
        )

    # A stopped turn returns empty text, which the UI would render as nothing at
    # all — say what happened instead.
    if not agent_result.text and session_cancel.is_set():
        return TurnResult(text="Stopped.", calls=agent_result.calls,
                          timed_out=False, error=None)

    return TurnResult(
        text=agent_result.text,
        calls=agent_result.calls,
        timed_out=False,
        error=None,
    )


def _describe_failure(exc: Exception) -> str:
    """Turn an exception into a message worth putting on screen, and file a
    diagnostic so /api/health shows it too."""
    import helpers.diagnostics
    from helpers.errors import classify_api_error, emit_api_diagnostic

    classified = classify_api_error(exc)
    if classified:
        message, hint = classified
        emit_api_diagnostic(message, hint)
        return message

    message = f"Something went wrong: {exc}"
    helpers.diagnostics.add("error", "AI", message)
    return message
