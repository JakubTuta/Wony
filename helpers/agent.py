"""
Agent loop: reason → call tool(s) → observe result → repeat → narrate.

Usage:
    result = run_agent(client, user_input, available_jobs, system_instructions, history)
    # result.text: final assistant answer (or clarifying question)
    # result.calls: list of {"name", "args", "result"} for logging
"""
import threading
import typing
import uuid

import helpers.model as helpers_model
from helpers.logger import logger


class AgentResult(typing.NamedTuple):
    text: str
    calls: typing.List[typing.Dict[str, typing.Any]]


def _fallback_from_calls(calls: typing.List[typing.Dict[str, typing.Any]]) -> str:
    """Return last non-empty tool result as the assistant text, or 'Done.'."""
    for call in reversed(calls):
        result = (call.get("result") or "").strip()
        if result:
            return result
    return "Done."


def _resolve_job_name(
    name: str,
    available_jobs: typing.Dict[str, typing.Callable],
) -> typing.Optional[str]:
    """Map a model-emitted tool name to a registered job.

    Models sometimes mangle names (Gemini has emitted 'system:greeting' and
    'greeting ' for a tool declared as 'greeting'), so fall back to the segment
    after a namespace separator before giving up.
    """
    name = name.strip()
    if name in available_jobs:
        return name
    for sep in (":", ".", "/"):
        if sep in name:
            candidate = name.rsplit(sep, 1)[-1].strip()
            if candidate in available_jobs:
                return candidate
    return None


def run_agent(
    client: typing.Any,
    user_input: str,
    available_jobs: typing.Dict[str, typing.Callable],
    system_instructions: helpers_model.SystemInstructions,
    history: typing.Optional[typing.List[typing.Dict[str, str]]] = None,
    max_steps: int = 5,
    on_text: typing.Optional[typing.Callable[[str], None]] = None,
    cancel_event: typing.Optional[threading.Event] = None,
    think: bool = False,
    more_jobs: typing.Optional[typing.Callable[[str, str], typing.Dict[str, typing.Callable]]] = None,
) -> AgentResult:
    """Run the agent loop for one user turn.

    Returns AgentResult with the final narrated text and a list of tool calls made.
    The caller is responsible for printing/speaking the result text.

    on_text: when given, each step streams from the model and text deltas are
    emitted through this callback as they arrive (for live TTS). Any text the
    model did NOT stream (fallbacks, error messages) is also emitted, so the
    callback always receives the full spoken answer.

    cancel_event: checked before each step and before each tool execution; if
    set, the turn aborts immediately with empty text rather than continuing to
    call tools or narrate a result the user already walked away from.

    think: let the model reason before it calls tools.

    more_jobs(name, result): when only some tools were sent (helpers/toolset.py),
    called with each tool name the model used and its result, and returns jobs
    to add — the one it named but was not sent, or what a routine's steps need.
    """
    available_jobs = dict(available_jobs)
    available_functions = list(available_jobs.values())

    def _widen(name: str, result: str) -> None:
        nonlocal available_functions
        if more_jobs is None:
            return
        extra = {k: v for k, v in more_jobs(name, result).items() if k not in available_jobs}
        if extra:
            available_jobs.update(extra)
            available_functions = list(available_jobs.values())

    # Build initial message list from history + current user input
    messages: typing.List[typing.Dict[str, typing.Any]] = []
    for msg in (history or []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})

    calls_made: typing.List[typing.Dict[str, typing.Any]] = []

    def _emit(text: str) -> None:
        if on_text is not None and text:
            on_text(text)

    for step in range(max_steps):
        if cancel_event is not None and cancel_event.is_set():
            return AgentResult(text="", calls=calls_made)

        text = ""
        tool_calls: typing.List[typing.Dict[str, typing.Any]] = []
        streamed = False

        if on_text is not None:
            heard: typing.List[str] = []

            def _tracked(chunk: str) -> None:
                heard.append(chunk)
                on_text(chunk)

            try:
                text, tool_calls = helpers_model.stream_agent_step(
                    client=client,
                    messages=messages,
                    system_instructions=system_instructions,
                    available_tools=available_functions,
                    on_text=_tracked,
                    think=think,
                )
                streamed = True
            except Exception as e:
                logger.log_error(f"streaming step failed: {e}", "agent_loop.stream")
                if heard:
                    # Part of the answer is already out; a retry would say all of it again.
                    tail = " — sorry, I lost the connection there."
                    _emit(tail)
                    return AgentResult(text="".join(heard) + tail, calls=calls_made)

        if not streamed:
            try:
                response = helpers_model.send_agent_messages(
                    client=client,
                    messages=messages,
                    system_instructions=system_instructions,
                    available_tools=available_functions,
                    think=think,
                )
            except Exception as e:
                logger.log_error(str(e), "agent_loop.send")
                error_text = f"Error communicating with AI: {e}"
                _emit(error_text)
                return AgentResult(text=error_text, calls=calls_made)
            tool_calls = _extract_all_tool_calls(response)
            text = helpers_model.get_text_from_response(response) or ""

        if not tool_calls:
            # No tool call — model produced a text response (final answer or clarifying question)
            if not text and calls_made:
                text = _fallback_from_calls(calls_made)
                _emit(text)
            elif not streamed:
                _emit(text)
            return AgentResult(text=text, calls=calls_made)

        # Execute each tool call and append results to messages
        # First record the assistant's tool_call turn(s)
        for tc in tool_calls:
            msg: typing.Dict[str, typing.Any] = {
                "role": "tool_call",
                "id": tc["id"],
                "name": tc["name"],
                "args": tc["args"],
            }
            for raw in ("_gemini_content", "_anthropic_content"):
                if raw in tc:
                    msg[raw] = tc[raw]
            messages.append(msg)

        if cancel_event is not None and cancel_event.is_set():
            return AgentResult(text="", calls=calls_made)

        # Checked one by one, in order: the confirm gate and the argument
        # check decide per call, and neither may race another call.
        planned = [_plan(tc, available_jobs, _widen, user_input) for tc in tool_calls]

        # Run what passed. Calls the model made in the same step do not depend
        # on each other's results, so different features run side by side; calls
        # to one feature keep their order ("add milk", then "show the list").
        _run_planned(planned, cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return AgentResult(text="", calls=calls_made)

        for plan in planned:
            tc, result_str = plan["tc"], plan["result"]
            if plan["func"] is not None:
                _widen(plan["exec_name"], result_str)
            logger.log_function_response(tc["name"], result_str[:200], user_input)
            call = {"name": tc["name"], "args": tc["args"], "result": result_str}
            if plan["needs_confirm"]:
                call["needs_confirm"] = True
            calls_made.append(call)
            messages.append({
                "role": "tool_result",
                "id": tc["id"],
                "name": tc["name"],
                "content": result_str,
            })

    # Reached max_steps without a text response — ask model to summarize.
    # The tools still go along: the history holds tool calls, and Anthropic
    # rejects those in a request that defines no tools. Any further call is ignored.
    try:
        messages.append({
            "role": "user",
            "content": "Summarize what you found from the tool results above in one or two sentences.",
        })
        if on_text is not None:
            text, _ = helpers_model.stream_agent_step(
                client=client,
                messages=messages,
                system_instructions=system_instructions,
                available_tools=available_functions,
                on_text=on_text,
                think=think,
            )
        else:
            final_response = helpers_model.send_agent_messages(
                client=client,
                messages=messages,
                system_instructions=system_instructions,
                available_tools=available_functions,
                think=think,
            )
            text = helpers_model.get_text_from_response(final_response) or ""
            _emit(text)
    except Exception as e:
        logger.log_error(str(e), "agent_loop.summary")
        text = ""
    if not text:
        text = _fallback_from_calls(calls_made)
        _emit(text)

    return AgentResult(text=text, calls=calls_made)


def _plan(
    tc: typing.Dict[str, typing.Any],
    available_jobs: typing.Dict[str, typing.Callable],
    widen: typing.Callable[[str, str], None],
    user_input: str,
) -> typing.Dict[str, typing.Any]:
    """What to do with one tool call: a job to run, or the answer already
    decided for it (unknown name, bad arguments, needs the user's go-ahead)."""
    from helpers import confirm
    from helpers.tools import validate_args

    name, args = tc["name"], tc["args"]
    plan: typing.Dict[str, typing.Any] = {
        "tc": tc, "args": args, "exec_name": None, "func": None, "result": "", "needs_confirm": False,
    }
    logger.log_function_call(name, user_input, args)

    exec_name = _resolve_job_name(name, available_jobs)
    if exec_name is None:
        # A real job that was not sent this turn (it is named in the system
        # prompt, or was used earlier) is still the user's to run.
        widen(name.strip(), "")
        exec_name = _resolve_job_name(name, available_jobs)
    if exec_name is None:
        plan["result"] = f"Unknown function: {name}"
        logger.log_error(plan["result"], "agent_loop.execute")
        return plan

    plan["exec_name"] = exec_name
    invalid = validate_args(available_jobs[exec_name], args)
    if invalid is not None:
        plan["result"] = invalid
        return plan

    needs_ok = confirm.check(exec_name, args)
    if needs_ok is not None:
        plan["result"], plan["needs_confirm"] = needs_ok, True
        return plan

    plan["func"] = available_jobs[exec_name]
    return plan


def _lane(plan: typing.Dict[str, typing.Any]) -> str:
    from helpers.registry import ServiceRegistry

    return ServiceRegistry.get_job_modules().get(plan["exec_name"]) or plan["exec_name"]


def _run_planned(
    planned: typing.List[typing.Dict[str, typing.Any]],
    cancel_event: typing.Any,
) -> None:
    """Run every planned job, filling in its result. One lane per feature;
    lanes run on their own threads when there is more than one."""
    from helpers import turn_context

    lanes: typing.Dict[str, typing.List[typing.Dict[str, typing.Any]]] = {}
    for plan in planned:
        if plan["func"] is not None:
            lanes.setdefault(_lane(plan), []).append(plan)

    def run_lane(queue: typing.List[typing.Dict[str, typing.Any]]) -> None:
        for plan in queue:
            if cancel_event is not None and cancel_event.is_set():
                plan["result"] = "Stopped before it ran."
                continue
            plan["result"] = _execute(plan["exec_name"], plan["func"], plan["args"])

    if len(lanes) <= 1:
        for queue in lanes.values():
            run_lane(queue)
        return

    import concurrent.futures

    # The workers act as this turn: who is present, and what they read
    # (an email opened on a worker still counts as read in this turn).
    state = turn_context.capture()

    def run_carried(queue: typing.List[typing.Dict[str, typing.Any]]) -> typing.Dict[str, typing.Any]:
        with turn_context.carried(state) as seen:
            run_lane(queue)
        return seen

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(lanes), thread_name_prefix="tool") as pool:
        for seen in pool.map(run_carried, lanes.values()):
            turn_context.absorb(seen)


def _execute(exec_name: str, func: typing.Callable, args: typing.Dict[str, typing.Any]) -> str:
    try:
        result = func(**args)
        return str(result) if result is not None else ""
    except Exception as e:
        message = f"Error executing {exec_name}: {e}"
        logger.log_error(message, "agent_loop.execute")
        return message


def _extract_all_tool_calls(
    response: typing.Any,
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Extract all tool calls from any provider's response as a list."""
    results = []

    try:
        from google.genai import types as genai_types
        if isinstance(response, genai_types.GenerateContentResponse):
            try:
                raw_content = response.candidates[0].content
                parts = raw_content.parts or []
            except (AttributeError, IndexError):
                return []
            first = True
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    entry: typing.Dict[str, typing.Any] = {
                        "id": str(uuid.uuid4())[:16],
                        # Gemini sometimes pads names with whitespace,
                        # which would fail the job-registry lookup.
                        "name": fc.name.strip(),
                        "args": dict(fc.args) if fc.args else {},
                    }
                    if first:
                        entry["_gemini_content"] = raw_content
                        first = False
                    results.append(entry)
            return results
    except ImportError:
        pass

    try:
        import anthropic as _anthropic
        if isinstance(response, _anthropic.types.Message):
            return helpers_model._anthropic_tool_calls(response)
    except ImportError:
        pass

    try:
        import ollama as _ollama
        if isinstance(response, _ollama.ChatResponse):
            tool_calls = getattr(response.message, "tool_calls", None) or []
            for tc in tool_calls:
                fn = tc.function
                results.append({
                    "id": str(uuid.uuid4())[:16],
                    "name": fn.name.strip(),
                    "args": dict(fn.arguments) if fn.arguments else {},
                })
            return results
    except ImportError:
        pass

    return results
