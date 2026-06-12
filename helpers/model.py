import base64
import os
import typing
import uuid

import anthropic
import numpy as np
import ollama
from google import genai
from google.genai import types as genai_types

import helpers.tools as helpers_tools

available_models = ["gemini", "anthropic", "ollama"]

_FALLBACK_GEMINI_MODEL = "gemini-2.0-flash"
_FALLBACK_ANTHROPIC_MODEL = "claude-sonnet-4-6"

# Auto-resolved model ids, cached per process — resolving costs a models.list()
# HTTP round-trip, which would otherwise be paid on every message.
_resolved_model_cache: typing.Dict[str, str] = {}

# Models that rejected thinking_config — don't retry it on them.
_thinking_unsupported: typing.Set[str] = set()


def _get_gemini_model(client: "genai.Client") -> str:
    from helpers.config import Config

    if user_model := Config.get("ai.gemini_model"):
        return user_model
    if "gemini" in _resolved_model_cache:
        return _resolved_model_cache["gemini"]
    try:
        models = list(client.models.list())
        candidates = [
            m.name
            for m in models
            if "generateContent" in (getattr(m, "supported_actions", None) or [])
            and "gemini" in m.name
        ]
        if candidates:
            candidates.sort(reverse=True)
            resolved = candidates[0].removeprefix("models/")
            _resolved_model_cache["gemini"] = resolved
            return resolved
    except Exception:
        pass
    return _FALLBACK_GEMINI_MODEL


def _get_anthropic_model(client: "anthropic.Anthropic") -> str:
    from helpers.config import Config

    if user_model := Config.get("ai.anthropic_model"):
        return user_model
    if "anthropic" in _resolved_model_cache:
        return _resolved_model_cache["anthropic"]
    try:
        models = client.models.list()
        if models.data:
            sorted_models = sorted(models.data, key=lambda m: m.created_at, reverse=True)
            resolved = sorted_models[0].id
            _resolved_model_cache["anthropic"] = resolved
            return resolved
    except Exception:
        pass
    return _FALLBACK_ANTHROPIC_MODEL


def _should_think(has_tools: bool) -> bool:
    """Whether the model should think (reason) for this call.

    Policy (config key ai.thinking: "auto" | "off" | "on"):
      - "off": never think — lowest latency everywhere.
      - "auto" (default) / "on": think only on pure-generation calls
        (no tools). Tool-dispatch steps never think, because:
          1. They're in the voice critical path — thinking delays the first
             spoken word or the tool call with no user-visible benefit.
          2. Anthropic requires thinking blocks to be echoed back unchanged in
             a multi-turn tool loop; our provider-neutral message list doesn't
             carry them, so thinking + tools would corrupt the next request.
        Deep reasoning is reserved for direct knowledge questions
        (ask_question / screenshot), where it improves the answer and there's
        no tool loop to break.
    """
    from helpers.config import Config

    mode = str(Config.get("ai.thinking", "auto")).lower()
    if mode in ("off", "false", "none", "disabled"):
        return False
    return not has_tools


def _gemini_can_disable_thinking(model: str) -> bool:
    # Only flash/lite-class models accept thinking_budget=0; pro models reject it.
    if model in _thinking_unsupported:
        return False
    m = model.lower()
    return "flash" in m or "lite" in m


def _gemini_config(
    system_instructions: typing.Optional[str],
    parsed_tools: typing.Optional[typing.List[dict]],
    model: str,
) -> typing.Optional["genai_types.GenerateContentConfig"]:
    kwargs: typing.Dict[str, typing.Any] = {}
    if system_instructions:
        kwargs["system_instruction"] = system_instructions
    if parsed_tools:
        kwargs["tools"] = [
            genai_types.Tool(
                function_declarations=[
                    genai_types.FunctionDeclaration(**x) for x in parsed_tools
                ]
            )
        ]
    # Disable thinking for tool-dispatch steps (and globally when off); leave the
    # provider default (thinking on) for pure-generation calls.
    if not _should_think(bool(parsed_tools)) and _gemini_can_disable_thinking(model):
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=0)
    return genai_types.GenerateContentConfig(**kwargs) if kwargs else None


def _anthropic_thinking(has_tools: bool, model: str) -> typing.Any:
    """Return the Anthropic `thinking` arg, or NOT_GIVEN.

    Adaptive thinking (4.6+) only; older claude-3 families reject it. Off for
    tool calls (see _should_think) — also avoids the thinking-block echo
    requirement that our neutral message list can't satisfy.
    """
    if not _should_think(has_tools):
        return anthropic.NOT_GIVEN
    if "claude-3" in model.lower():
        return anthropic.NOT_GIVEN
    return {"type": "adaptive"}


def _ollama_think(has_tools: bool) -> typing.Optional[bool]:
    """Return True to request Ollama thinking, or None to omit the kwarg.

    Only thinking-capable local models accept `think`; callers retry without it
    on error (see _ollama_chat)."""
    return True if _should_think(has_tools) else None


def _ollama_chat(client: "ollama.Client", *, think: typing.Optional[bool], **kwargs: typing.Any) -> typing.Any:
    """client.chat with one retry dropping `think` if the model rejects it."""
    if think is not None:
        try:
            return client.chat(think=think, **kwargs)
        except Exception:
            pass  # model likely doesn't support thinking — retry without
    return client.chat(**kwargs)


def _gemini_generate(
    client: "genai.Client",
    model: str,
    contents: typing.Any,
    config: typing.Optional["genai_types.GenerateContentConfig"],
) -> "genai_types.GenerateContentResponse":
    """generate_content with one retry without thinking_config if the model rejects it."""
    try:
        return client.models.generate_content(model=model, contents=contents, config=config)
    except Exception:
        if config is not None and config.thinking_config is not None:
            _thinking_unsupported.add(model)
            config.thinking_config = None
            return client.models.generate_content(model=model, contents=contents, config=config)
        raise


def get_model() -> typing.Optional[
    typing.List[
        typing.Union[
            str,
            typing.Literal[
                "gemini",
                "anthropic",
                "ollama",
            ],
            None,
        ]
    ]
]:
    from helpers.config import Config

    configured_provider = Config.get("ai.provider")
    if configured_provider == "ollama":
        return ["ollama", None]

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if configured_provider == "gemini" and gemini_key:
        return ["gemini", gemini_key]
    if configured_provider == "anthropic" and anthropic_key:
        return ["anthropic", anthropic_key]

    # Auto-detect from available keys
    if gemini_key:
        return ["gemini", gemini_key]
    if anthropic_key:
        return ["anthropic", anthropic_key]


def send_message(
    client: typing.Optional[
        typing.Union[genai.Client, anthropic.Anthropic, ollama.Client]
    ],
    message: str,
    system_instructions: typing.Optional[str] = None,
    available_tools: typing.Optional[typing.List[typing.Callable]] = None,
    image: typing.Optional[np.ndarray] = None,
    history: typing.Optional[typing.List[typing.Dict[str, str]]] = None,
) -> typing.Union[
    genai_types.GenerateContentResponse, anthropic.types.Message, ollama.ChatResponse
]:
    if client is None:
        raise Exception(
            "AI client not initialized. Add ANTHROPIC_API_KEY or GEMINI_API_KEY to .env, "
            "or set ai.provider: ollama in config.yaml and run `ollama serve`."
        )

    parsed_tools = None
    if available_tools:
        parsed_tools = [
            helpers_tools.function_to_schema(func) for func in available_tools
        ]

    base64_image = None
    if image is not None:
        base64_image = helpers_tools.numpy_image_to_base64_bytes(image)

    if isinstance(client, genai.Client):
        model = _get_gemini_model(client)
        config = _gemini_config(system_instructions, parsed_tools, model)

        current_parts: typing.List[typing.Any] = []
        if base64_image is not None:
            current_parts.append(
                genai_types.Part.from_bytes(
                    data=base64.b64decode(base64_image), mime_type="image/jpeg"
                )
            )
        current_parts.append(genai_types.Part.from_text(text=message))

        if history:
            contents: typing.List[typing.Any] = []
            for msg in history:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append(
                    genai_types.Content(
                        role=role,
                        parts=[genai_types.Part.from_text(text=msg["content"])],
                    )
                )
            contents.append(
                genai_types.Content(role="user", parts=current_parts)
            )
        else:
            contents = current_parts if len(current_parts) > 1 else current_parts[0]

        return _gemini_generate(client, model, contents, config)

    elif isinstance(client, anthropic.Anthropic):
        messages_content: typing.Any = message
        if base64_image is not None:
            messages_content = [
                {"type": "text", "text": message},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64_image,
                    },
                },
            ]

        anthropic_messages = list(history) if history else []
        anthropic_messages.append({"role": "user", "content": messages_content})

        from helpers.config import Config
        max_tokens = int(Config.get("ai.max_tokens", 8192))
        model = _get_anthropic_model(client)
        thinking = _anthropic_thinking(bool(parsed_tools), model)

        def _create(think: typing.Any) -> typing.Any:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=anthropic_messages,
                system=(
                    system_instructions if system_instructions else anthropic.NOT_GIVEN
                ),
                tools=parsed_tools if parsed_tools else anthropic.NOT_GIVEN,  # type: ignore
                thinking=think,
            )

        try:
            return _create(thinking)
        except Exception:
            if thinking is not anthropic.NOT_GIVEN:
                return _create(anthropic.NOT_GIVEN)  # model rejected adaptive thinking
            raise

    elif isinstance(client, ollama.Client):
        ollama_messages: typing.List[typing.Dict[str, str]] = []

        if system_instructions:
            ollama_messages.append({"role": "system", "content": system_instructions})

        if history:
            ollama_messages.extend(history)

        ollama_messages.append({"role": "user", "content": message})

        messages = ollama_messages

        from helpers.config import Config

        model = Config.get("ai.ollama_model") or os.getenv("AI_MODEL")
        if not model:
            raise Exception(
                "Ollama model not configured. Set ai.ollama_model in config.yaml or AI_MODEL env var."
            )

        return _ollama_chat(
            client,
            think=_ollama_think(bool(parsed_tools)),
            model=model,
            messages=messages,
            stream=False,
        )

    raise Exception(
        "Invalid client type. Expected genai.Client, anthropic.Anthropic or ollama.Client."
    )


def _to_gemini_contents(
    messages: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Any]:
    """Convert the provider-neutral agent message list to Gemini contents."""
    contents: typing.List[typing.Any] = []
    seen_content_ids: typing.Set[int] = set()
    for msg in messages:
        role = msg["role"]
        if role == "user":
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=str(msg["content"]))],
                )
            )
        elif role == "assistant":
            contents.append(
                genai_types.Content(
                    role="model",
                    parts=[genai_types.Part.from_text(text=str(msg["content"]))],
                )
            )
        elif role == "tool_call":
            raw_content = msg.get("_gemini_content")
            if raw_content is not None:
                cid = id(raw_content)
                if cid not in seen_content_ids:
                    contents.append(raw_content)
                    seen_content_ids.add(cid)
            else:
                fc = genai_types.FunctionCall(name=msg["name"], args=msg.get("args", {}))
                contents.append(
                    genai_types.Content(role="model", parts=[genai_types.Part(function_call=fc)])
                )
        elif role == "tool_result":
            fr = genai_types.FunctionResponse(
                name=msg["name"],
                response={"result": str(msg["content"])},
            )
            contents.append(
                genai_types.Content(role="user", parts=[genai_types.Part(function_response=fr)])
            )
    return contents


def _to_anthropic_messages(
    messages: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Any]:
    """Convert the provider-neutral agent message list to Anthropic messages."""
    anthropic_messages: typing.List[typing.Any] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg["role"]

        if role == "user":
            anthropic_messages.append({"role": "user", "content": str(msg["content"])})
        elif role == "assistant":
            anthropic_messages.append({"role": "assistant", "content": str(msg["content"])})
        elif role == "tool_call":
            # Collect consecutive tool_calls + their tool_results into one assistant/user pair
            tool_uses = []
            while i < len(messages) and messages[i]["role"] == "tool_call":
                tc = messages[i]
                tool_uses.append({
                    "type": "tool_use",
                    "id": tc.get("id", f"tool_{i}"),
                    "name": tc["name"],
                    "input": tc.get("args", {}),
                })
                i += 1
            anthropic_messages.append({"role": "assistant", "content": tool_uses})

            # Corresponding tool_results
            tool_results = []
            while i < len(messages) and messages[i]["role"] == "tool_result":
                tr = messages[i]
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tr.get("id", f"tool_{i}"),
                    "content": str(tr["content"]),
                })
                i += 1
            if tool_results:
                anthropic_messages.append({"role": "user", "content": tool_results})
            continue
        i += 1
    return anthropic_messages


def _to_ollama_messages(
    messages: typing.List[typing.Dict[str, typing.Any]],
    system_instructions: typing.Optional[str],
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Convert the provider-neutral agent message list to Ollama messages."""
    ollama_messages: typing.List[typing.Dict[str, typing.Any]] = []
    if system_instructions:
        ollama_messages.append({"role": "system", "content": system_instructions})
    for msg in messages:
        role = msg["role"]
        if role in ("user", "assistant"):
            ollama_messages.append({"role": role, "content": str(msg["content"])})
        elif role == "tool_call":
            ollama_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": msg["name"], "arguments": msg.get("args", {})}
                }],
            })
        elif role == "tool_result":
            ollama_messages.append({"role": "tool", "content": str(msg["content"])})
    return ollama_messages


def _require_ollama_model() -> str:
    from helpers.config import Config

    model = Config.get("ai.ollama_model") or os.getenv("AI_MODEL")
    if not model:
        raise Exception(
            "Ollama model not configured. Set ai.ollama_model in config.yaml."
        )
    return model


def send_agent_messages(
    client: typing.Optional[
        typing.Union[genai.Client, anthropic.Anthropic, ollama.Client]
    ],
    messages: typing.List[typing.Dict[str, typing.Any]],
    system_instructions: typing.Optional[str] = None,
    available_tools: typing.Optional[typing.List[typing.Callable]] = None,
) -> typing.Union[
    genai_types.GenerateContentResponse, anthropic.types.Message, ollama.ChatResponse
]:
    """Send a full agent message list (may include tool results) to the model.

    `messages` is a provider-neutral list of dicts, each with at least:
      {"role": "user"|"assistant"|"tool_result", "content": str}
    Tool call dicts from a prior response may also appear with extra keys:
      {"role": "tool_call", "id": str, "name": str, "args": dict}

    This function converts that neutral list to the provider's native format.
    """
    if client is None:
        raise Exception("AI client not initialized.")

    parsed_tools = None
    if available_tools:
        parsed_tools = [
            helpers_tools.function_to_schema(func) for func in available_tools
        ]

    if isinstance(client, genai.Client):
        model = _get_gemini_model(client)
        config = _gemini_config(system_instructions, parsed_tools, model)
        return _gemini_generate(client, model, _to_gemini_contents(messages), config)

    elif isinstance(client, anthropic.Anthropic):
        from helpers.config import Config
        max_tokens = int(Config.get("ai.max_tokens", 8192))

        return client.messages.create(
            model=_get_anthropic_model(client),
            max_tokens=max_tokens,
            messages=_to_anthropic_messages(messages),
            system=system_instructions if system_instructions else anthropic.NOT_GIVEN,
            tools=parsed_tools if parsed_tools else anthropic.NOT_GIVEN,  # type: ignore
        )

    elif isinstance(client, ollama.Client):
        return client.chat(
            model=_require_ollama_model(),
            messages=_to_ollama_messages(messages, system_instructions),
            tools=parsed_tools if parsed_tools else None,
            stream=False,
        )

    raise Exception("Invalid client type.")


def stream_agent_step(
    client: typing.Optional[
        typing.Union[genai.Client, anthropic.Anthropic, ollama.Client]
    ],
    messages: typing.List[typing.Dict[str, typing.Any]],
    system_instructions: typing.Optional[str] = None,
    available_tools: typing.Optional[typing.List[typing.Callable]] = None,
    on_text: typing.Optional[typing.Callable[[str], None]] = None,
) -> typing.Tuple[str, typing.List[typing.Dict[str, typing.Any]]]:
    """Run one agent step with streaming: text deltas are emitted through
    on_text the moment they arrive, so TTS can start before the model finishes.

    Returns (text, tool_calls). tool_calls entries have the same shape as
    helpers.agent._extract_all_tool_calls: {"id", "name", "args"} plus
    "_gemini_content" on the first entry for faithful Gemini history replay
    (preserves thought signatures, which Gemini 3 requires).
    """
    if client is None:
        raise Exception("AI client not initialized.")

    emit = on_text if on_text is not None else (lambda _chunk: None)

    parsed_tools = None
    if available_tools:
        parsed_tools = [
            helpers_tools.function_to_schema(func) for func in available_tools
        ]

    if isinstance(client, anthropic.Anthropic):
        from helpers.config import Config
        max_tokens = int(Config.get("ai.max_tokens", 8192))

        text_parts: typing.List[str] = []
        with client.messages.stream(
            model=_get_anthropic_model(client),
            max_tokens=max_tokens,
            messages=_to_anthropic_messages(messages),
            system=system_instructions if system_instructions else anthropic.NOT_GIVEN,
            tools=parsed_tools if parsed_tools else anthropic.NOT_GIVEN,  # type: ignore
        ) as stream:
            for chunk in stream.text_stream:
                if chunk:
                    text_parts.append(chunk)
                    emit(chunk)
            final = stream.get_final_message()

        tool_calls = [
            {
                "id": getattr(block, "id", str(uuid.uuid4())[:16]),
                "name": block.name.strip(),
                "args": dict(block.input) if block.input else {},
            }
            for block in final.content
            if getattr(block, "type", None) == "tool_use"
        ]
        return "".join(text_parts), tool_calls

    elif isinstance(client, genai.Client):
        model = _get_gemini_model(client)
        contents = _to_gemini_contents(messages)
        config = _gemini_config(system_instructions, parsed_tools, model)

        for attempt in range(2):
            text_parts = []
            raw_parts: typing.List[typing.Any] = []
            tool_calls = []
            try:
                for chunk in client.models.generate_content_stream(
                    model=model, contents=contents, config=config
                ):
                    try:
                        parts = chunk.candidates[0].content.parts or []
                    except (AttributeError, IndexError, TypeError):
                        continue
                    for part in parts:
                        if getattr(part, "text", None):
                            text_parts.append(part.text)
                            emit(part.text)
                            raw_parts.append(part)
                        fc = getattr(part, "function_call", None)
                        if fc and getattr(fc, "name", None):
                            raw_parts.append(part)
                            tool_calls.append({
                                "id": str(uuid.uuid4())[:16],
                                # Gemini sometimes pads names with whitespace,
                                # which would fail the job-registry lookup.
                                "name": fc.name.strip(),
                                "args": dict(fc.args) if fc.args else {},
                            })
                break
            except Exception:
                # Retry once without thinking_config (model may reject it) —
                # but only if nothing was emitted yet, so no text repeats.
                can_retry = (
                    attempt == 0
                    and config is not None
                    and config.thinking_config is not None
                    and not text_parts
                    and not tool_calls
                )
                if not can_retry:
                    raise
                _thinking_unsupported.add(model)
                config.thinking_config = None

        if tool_calls:
            tool_calls[0]["_gemini_content"] = genai_types.Content(
                role="model", parts=raw_parts
            )
        return "".join(text_parts), tool_calls

    elif isinstance(client, ollama.Client):
        text_parts = []
        tool_calls = []
        for chunk in client.chat(
            model=_require_ollama_model(),
            messages=_to_ollama_messages(messages, system_instructions),
            tools=parsed_tools if parsed_tools else None,
            stream=True,
        ):
            content = chunk.message.content
            if content:
                text_parts.append(content)
                emit(content)
            for tc in getattr(chunk.message, "tool_calls", None) or []:
                fn = tc.function
                tool_calls.append({
                    "id": str(uuid.uuid4())[:16],
                    "name": fn.name.strip(),
                    "args": dict(fn.arguments) if fn.arguments else {},
                })
        return "".join(text_parts), tool_calls

    raise Exception("Invalid client type.")


def get_text_from_response(
    response: typing.Union[
        genai_types.GenerateContentResponse,
        anthropic.types.Message,
        ollama.ChatResponse,
    ],
) -> typing.Optional[str]:
    if isinstance(response, genai_types.GenerateContentResponse):
        return response.text

    elif isinstance(response, anthropic.types.Message):
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text  # type: ignore

    elif isinstance(response, ollama.ChatResponse):
        return response.message.content


def describe_readiness() -> typing.Tuple[bool, str]:
    """Returns (ok, message) describing AI provider availability."""
    from helpers.config import Config

    configured_provider = Config.get("ai.provider")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if configured_provider == "ollama":
        ollama_model = Config.get("ai.ollama_model")
        if not ollama_model:
            return False, (
                "ai.provider is 'ollama' but ai.ollama_model is not set. To fix:\n"
                "  1. Open config.yaml\n"
                "  2. Set ai.ollama_model, e.g.:  ollama_model: \"llama3.2\"\n"
                "  3. Make sure Ollama is running:  ollama serve\n"
                "  4. Pull the model if needed:  ollama pull llama3.2"
            )
        return True, f"Using local Ollama model ({ollama_model}, ai.provider: ollama)."
    if configured_provider == "gemini" and gemini_key:
        return True, "Gemini AI configured."
    if configured_provider == "anthropic" and anthropic_key:
        return True, "Anthropic AI configured."
    if configured_provider in ("gemini", "anthropic") and not gemini_key and not anthropic_key:
        return False, (
            f"ai.provider is '{configured_provider}' but no API key found. "
            f"Add {'GEMINI_API_KEY' if configured_provider == 'gemini' else 'ANTHROPIC_API_KEY'} to .env."
        )
    if gemini_key:
        return True, "Gemini AI configured (auto-detected)."
    if anthropic_key:
        return True, "Anthropic AI configured (auto-detected)."

    return False, (
        "No AI configured. Add ANTHROPIC_API_KEY or GEMINI_API_KEY to .env, "
        "or set ai.provider: ollama in config.yaml and run `ollama serve`."
    )
