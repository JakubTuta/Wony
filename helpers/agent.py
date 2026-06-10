"""
Agent loop: reason → call tool(s) → observe result → repeat → narrate.

Usage:
    result = run_agent(client, user_input, available_jobs, system_instructions, history)
    # result.text: final assistant answer (or clarifying question)
    # result.calls: list of {"name", "args", "result"} for logging
"""
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


def run_agent(
    client: typing.Any,
    user_input: str,
    available_jobs: typing.Dict[str, typing.Callable],
    system_instructions: str,
    history: typing.Optional[typing.List[typing.Dict[str, str]]] = None,
    max_steps: int = 5,
) -> AgentResult:
    """Run the agent loop for one user turn.

    Returns AgentResult with the final narrated text and a list of tool calls made.
    The caller is responsible for printing/speaking the result text.
    """
    available_functions = list(available_jobs.values())

    # Build initial message list from history + current user input
    messages: typing.List[typing.Dict[str, typing.Any]] = []
    for msg in (history or []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})

    calls_made: typing.List[typing.Dict[str, typing.Any]] = []

    for step in range(max_steps):
        try:
            response = helpers_model.send_agent_messages(
                client=client,
                messages=messages,
                system_instructions=system_instructions,
                available_tools=available_functions,
            )
        except Exception as e:
            logger.log_error(str(e), "agent_loop.send")
            return AgentResult(text=f"Error communicating with AI: {e}", calls=calls_made)

        # Extract all tool calls from this response
        tool_calls = _extract_all_tool_calls(response)

        if not tool_calls:
            # No tool call — model produced a text response (final answer or clarifying question)
            text = helpers_model.get_text_from_response(response) or ""
            if not text and calls_made:
                text = _fallback_from_calls(calls_made)
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
            if "_gemini_content" in tc:
                msg["_gemini_content"] = tc["_gemini_content"]
            messages.append(msg)

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            tool_id = tc["id"]

            logger.log_function_call(name, user_input, args)

            if name in available_jobs:
                try:
                    result = available_jobs[name](**args)
                    result_str = str(result) if result is not None else ""
                except Exception as e:
                    result_str = f"Error executing {name}: {e}"
                    logger.log_error(result_str, "agent_loop.execute")
            else:
                result_str = f"Unknown function: {name}"
                logger.log_error(result_str, "agent_loop.execute")

            logger.log_function_response(name, result_str[:200], user_input)
            calls_made.append({"name": name, "args": args, "result": result_str})

            messages.append({
                "role": "tool_result",
                "id": tool_id,
                "name": name,
                "content": result_str,
            })

    # Reached max_steps without a text response — ask model to summarize
    try:
        messages.append({
            "role": "user",
            "content": "Summarize what you found from the tool results above in one or two sentences.",
        })
        final_response = helpers_model.send_agent_messages(
            client=client,
            messages=messages,
            system_instructions=system_instructions,
        )
        text = helpers_model.get_text_from_response(final_response) or "Done."
    except Exception:
        text = "Done. (max steps reached)"

    return AgentResult(text=text, calls=calls_made)


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
                        "name": fc.name,
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
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    results.append({
                        "id": getattr(block, "id", str(uuid.uuid4())[:16]),
                        "name": block.name,
                        "args": dict(block.input) if block.input else {},
                    })
            return results
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
                    "name": fn.name,
                    "args": dict(fn.arguments) if fn.arguments else {},
                })
            return results
    except ImportError:
        pass

    return results
