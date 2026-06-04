import base64
import os
import typing

import anthropic
import numpy as np
import ollama
from google import genai
from google.genai import types as genai_types

import helpers.tools as helpers_tools
from helpers.cache import Cache

available_models = ["gemini", "sonnet", "ollama"]

_FALLBACK_GEMINI_MODEL = "gemini-2.0-flash"
_FALLBACK_ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _get_gemini_model(client: "genai.Client") -> str:
    from helpers.config import Config

    if user_model := Config.get("ai.gemini_model"):
        return user_model
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
            return candidates[0].removeprefix("models/")
    except Exception:
        pass
    return _FALLBACK_GEMINI_MODEL


def _get_anthropic_model(client: "anthropic.Anthropic") -> str:
    from helpers.config import Config

    if user_model := Config.get("ai.anthropic_model"):
        return user_model
    try:
        models = client.models.list()
        if models.data:
            sorted_models = sorted(models.data, key=lambda m: m.created_at, reverse=True)
            return sorted_models[0].id
    except Exception:
        pass
    return _FALLBACK_ANTHROPIC_MODEL


def get_model() -> typing.Optional[
    typing.List[
        typing.Union[
            str,
            typing.Literal[
                "gemini",
                "sonnet",
                "ollama",
            ],
            None,
        ]
    ]
]:
    from helpers.config import Config

    local = Cache.get_local()
    if local:
        return ["ollama", None]

    # Honor explicit provider from config
    configured_provider = Config.get("ai.provider")
    if configured_provider == "ollama":
        return ["ollama", None]

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if configured_provider == "gemini" and gemini_key:
        return ["gemini", gemini_key]
    if configured_provider == "anthropic" and anthropic_key:
        return ["sonnet", anthropic_key]

    # Auto-detect from available keys
    if gemini_key:
        return ["gemini", gemini_key]
    if anthropic_key:
        return ["sonnet", anthropic_key]


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
        config = None
        if system_instructions or parsed_tools:
            config = genai_types.GenerateContentConfig(
                system_instruction=system_instructions,
                tools=(
                    [
                        genai_types.Tool(
                            function_declarations=[
                                genai_types.FunctionDeclaration(**x)
                                for x in parsed_tools
                            ]
                        )
                    ]
                    if parsed_tools
                    else None
                ),
            )

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

        response = client.models.generate_content(
            model=_get_gemini_model(client),
            contents=contents,
            config=config,
        )

        return response

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

        response = client.messages.create(
            model=_get_anthropic_model(client),
            max_tokens=1024,
            messages=anthropic_messages,
            system=(
                system_instructions if system_instructions else anthropic.NOT_GIVEN
            ),
            tools=parsed_tools if parsed_tools else anthropic.NOT_GIVEN,  # type: ignore
        )

        return response

    elif isinstance(client, ollama.Client):
        ollama_messages: typing.List[typing.Dict[str, str]] = []

        if system_instructions:
            ollama_messages.append({"role": "assistant", "content": system_instructions})

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

        response = client.chat(
            model=model,
            messages=messages,
            stream=False,
        )

        return response

    raise Exception(
        "Invalid client type. Expected genai.Client, anthropic.Anthropic or ollama.Client."
    )


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
        if response.content:
            return response.content[0].text  # type: ignore

    elif isinstance(response, ollama.ChatResponse):
        return response.message.content


def get_function_from_response(
    response: typing.Union[
        genai_types.GenerateContentResponse,
        anthropic.types.Message,
        ollama.ChatResponse,
    ],
) -> typing.Optional[typing.Dict[str, typing.Any]]:
    if isinstance(response, genai_types.GenerateContentResponse):
        if (
            function_call := response.candidates[0].content.parts[0].function_call  # type: ignore
        ) is None:
            return

        function_name = function_call.name
        function_args = function_call.args

        return {
            "name": function_name,
            "args": function_args,
        }

    elif isinstance(response, anthropic.types.Message):
        tool_uses = response.content

        for block in tool_uses:
            if block.type == "tool_use":
                function_name = block.name
                function_args = block.input

                return {
                    "name": function_name,
                    "args": function_args,
                }

    elif isinstance(response, ollama.ChatResponse):
        if response.message.tool_calls is None:
            return

        for tool in response.message.tool_calls:
            function_name = tool.function.name
            function_args = tool.function.arguments

            if function_args is None:
                function_args = {}

            return {
                "name": function_name,
                "args": function_args,
            }


def describe_readiness() -> typing.Tuple[bool, str]:
    """Returns (ok, message) describing AI provider availability."""
    from helpers.config import Config

    local = Cache.get_local()
    if local:
        return True, "Using local Ollama model."

    configured_provider = Config.get("ai.provider")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if configured_provider == "ollama":
        return True, "Using local Ollama model (ai.provider: ollama)."
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
