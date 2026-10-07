"""
One agent turn, from text in to text out.

Every input path runs through run_turn(): the voice loop, POST /api/chat, the
WebSocket chat. It owns the things that must not be duplicated per caller —
the process-wide agent lock, the cancel signal, the per-turn tool-outcome
ledger, the wall-clock backstop, and the translation of a failure into
something a human can read.

Callers keep only what is theirs: the voice path rigs TTS streaming, barge-in
and the "one moment" cue into `on_text`; every caller records its own turn into
Conversation, because the WebSocket path needs the turn id back.
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
    from_user: bool = True,
    at_machine: bool = True,
    quoted: str = "",
    think: bool = False,
) -> TurnResult:
    """Run one agent turn. Never raises — failures come back in TurnResult.error.

    think=True for a typed turn: the model reasons before it picks tools. A
    spoken turn leaves it off, because it delays the first word.

    from_user=False for turns nobody asked for (triggers): nothing in them may
    open a sign-in window or follow a link the user never mentioned.
    at_machine=False for a request from a phone: the user can confirm, but
    nothing may open a window or click on the PC.
    quoted is text someone else wrote that the user passed along (a forwarded
    message). It reaches the model fenced as data, and is not counted as
    something the user said.
    """
    from helpers import confirm, private_numbers, toolset
    from helpers.agent import _fallback_from_calls, run_agent
    from helpers.bootstrap import get_ai_client
    from helpers.conversation import Conversation
    from helpers.decorators import (
        agent_lock,
        begin_tool_outcomes,
        set_agent_active,
    )
    from helpers.events import clear_cancel, session_cancel
    from helpers.registry import ServiceRegistry
    from helpers.turn_context import mark_untrusted_read, unattended, user_request
    from helpers.untrusted import OPEN, wrap
    from modules.ai import build_agent_system_prompt

    timed_out = threading.Event()
    timer = threading.Timer(_TURN_TIMEOUT_SECONDS, timed_out.set)
    timer.daemon = True

    class _TurnCancel:
        @staticmethod
        def is_set() -> bool:
            return session_cancel.is_set() or timed_out.is_set()

    agent_result = None
    agent_err: typing.Optional[Exception] = None

    with agent_lock:
        # Inside the lock: a cancel raised against a previous turn must not
        # abort this one, but clearing it before acquiring could cancel a turn
        # that is still running. The ledger is reset here for the same reason —
        # it is read back by the voice path to decide whether to speak, and a
        # leftover entry from another turn would answer for this one.
        clear_cancel()
        set_agent_active(True)
        begin_tool_outcomes()
        # A confirmation armed in this turn may only be spent in a later one —
        # this is what stops the model from confirming itself.
        confirm.begin_turn()
        timer.start()
        presence = (
            user_request(user_input, at_machine=at_machine)
            if from_user
            else unattended()
        )
        private_numbers.begin()
        try:
            with presence:
                # A number the user says goes to the model as "[number 1]".
                said = private_numbers.mask(user_input)
                # Fenced inside the request: wrap() marks the turn as having
                # read untrusted text, which only sticks within user_request.
                prompt = f"{said}\n{wrap(quoted, 'forwarded message')}" if quoted else said
                history = Conversation.get_messages()
                # Earlier turns' email bodies and pages ride along in the history.
                # Read again here, they count as read in this turn too.
                if OPEN in prompt or any(OPEN in str(m["content"]) for m in history):
                    mark_untrusted_read()
                quick = None if quoted or not from_user else _answer_without_model(user_input)
                if quick is not None:
                    agent_result = quick
                    if on_text is not None and quick.text:
                        on_text(quick.text)
                else:
                    last_reply = history[-1]["content"] if history and history[-1]["role"] == "assistant" else ""
                    agent_result = run_agent(
                        client=get_ai_client(),
                        user_input=prompt,
                        available_jobs=toolset.pick(
                            f"{user_input}\n{last_reply[:500]}",
                            Conversation.recent_job_names() + confirm.armed_jobs(),
                        ),
                        system_instructions=build_agent_system_prompt(user_input),
                        history=history,
                        max_steps=MAX_AGENT_STEPS,
                        on_text=(lambda chunk: on_text(private_numbers.reveal(chunk))) if on_text else None,
                        cancel_event=_TurnCancel(),
                        think=think,
                        more_jobs=_more_jobs,
                    )
                    # What the user sees and what is kept locally has the digits back.
                    agent_result = agent_result._replace(
                        text=private_numbers.reveal(agent_result.text),
                        calls=[private_numbers.reveal(call) for call in agent_result.calls],
                    )
        except Exception as exc:
            agent_err = exc
        finally:
            private_numbers.end()
            timer.cancel()
            set_agent_active(False)

    if agent_err is not None:
        message = describe_failure(agent_err)
        return TurnResult(text=message, calls=[], timed_out=False, error=message)

    if timed_out.is_set() and not agent_result.text:
        import helpers.diagnostics

        helpers.diagnostics.add(
            "warning", "AI", f"Turn exceeded {_TURN_TIMEOUT_SECONDS:.0f}s — aborted."
        )
        # A tool did run and returned something before the clock ran out —
        # showing that beats showing an apology.
        fallback = _fallback_from_calls(agent_result.calls)
        if fallback == "Done.":
            fallback = "Sorry, that took too long — I'm stopping there."
        return TurnResult(
            text=fallback, calls=agent_result.calls, timed_out=True, error=None
        )

    # A stopped turn returns empty text, which the UI would render as nothing at
    # all — say what happened instead.
    if not agent_result.text and session_cancel.is_set():
        return TurnResult(
            text="Stopped.", calls=agent_result.calls, timed_out=False, error=None
        )

    return TurnResult(
        text=agent_result.text, calls=agent_result.calls, timed_out=False, error=None
    )


def _more_jobs(name: str, result: str) -> typing.Dict[str, typing.Callable]:
    """Jobs to add mid-turn (helpers/agent.py): one the model named that was not
    sent, or what the steps of a routine it just ran call for."""
    from helpers import toolset
    from helpers.agent import _resolve_job_name
    from helpers.registry import ServiceRegistry

    jobs = ServiceRegistry.get_all_jobs()
    if name == "routine" and result:
        # The routine's steps are the user's own words; only they widen the set.
        return toolset.pick(result)
    resolved = _resolve_job_name(name, jobs)
    return {resolved: jobs[resolved]} if resolved else {}


# Answers that need no model: the previous turn asked "should I…?", or the user
# wants the last change back. Saying the call again through the model costs a
# round trip, and a model that re-sends it slightly differently asks again.
_YES = {
    "yes", "yeah", "yep", "yes please", "sure", "ok", "okay", "do it", "go ahead",
    "confirm", "confirmed", "yes do it", "please do", "go for it",
}
_NO = {"no", "nope", "no thanks", "cancel", "don't", "dont", "do not", "never mind", "nevermind"}
_UNDO = {"undo", "undo that", "undo it", "take that back", "revert that"}


def _answer_without_model(user_input: str) -> typing.Optional[typing.Any]:
    """An AgentResult for a bare yes / no / undo, or None for the model."""
    import re

    from helpers import confirm, undo
    from helpers.agent import AgentResult
    from helpers.logger import logger
    from helpers.registry import ServiceRegistry

    said = " ".join(re.sub(r"[^\w' ]", " ", user_input.lower()).split())

    if said in _UNDO:
        result = undo.undo()
        return AgentResult(text=result, calls=[{"name": "undo", "args": {}, "result": result}])

    if said not in _YES and said not in _NO:
        return None
    armed = confirm.take_previous_turn()
    if not armed:
        return None
    if said in _NO:
        return AgentResult(text="Okay, I won't.", calls=[])

    jobs = ServiceRegistry.get_all_jobs()
    calls = []
    for call in armed:
        logger.log_function_call(call.job, user_input, call.args)
        func = jobs.get(call.job)
        if func is None:
            result = f"{call.job} is no longer available."
        else:
            try:
                result = str(func(**call.args) or "")
            except Exception as e:
                result = f"Error executing {call.job}: {e}"
                logger.log_error(result, "turn.confirmed")
        logger.log_function_response(call.job, result[:200], user_input)
        calls.append({"name": call.job, "args": call.args, "result": result})
    text = " ".join(c["result"] for c in calls if c["result"]) or "Done."
    return AgentResult(text=text, calls=calls)


def describe_failure(exc: Exception) -> str:
    """Turn an exception into a message worth putting on screen, and file a
    diagnostic so /api/health shows it too."""
    import helpers.diagnostics
    from helpers.bootstrap import BootstrapError
    from helpers.errors import classify_api_error, emit_api_diagnostic

    if isinstance(exc, BootstrapError):
        # Not finding an AI key is expected the first time Wony runs, not a
        # failure worth the "something went wrong" framing.
        helpers.diagnostics.add("warning", "AI", str(exc))
        return str(exc)

    classified = classify_api_error(exc)
    if classified:
        message, hint = classified
        emit_api_diagnostic(message, hint)
        return message

    message = f"Something went wrong: {exc}"
    helpers.diagnostics.add("error", "AI", message)
    return message
