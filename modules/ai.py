import typing

import anthropic
import numpy as np
import ollama
from google import genai

import helpers.model as helpers_model
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.conversation import Conversation
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import method_job, register_job, simple_service


def _persona() -> str:
    """Build persona preamble from config + persistent profile."""
    from helpers.config import Config
    from helpers.profile import Profile

    name = Config.get("assistant.name", "Wony")
    owner = Config.get("assistant.owner_name", "User")
    personality = Config.get("assistant.personality", "Friendly and concise.")
    language = Config.get("assistant.language", "en")
    base = (
        f"You are {name}, a personal AI assistant for {owner}. "
        f"{personality} Respond in {language}."
    )
    profile_text = Profile.as_text()
    if profile_text:
        base += f" {profile_text}"
    return base


def build_agent_system_prompt() -> str:
    """System prompt for the multi-step agent loop."""
    return (
        _persona()
        + "\n\nYou are an intelligent agent. For each user request:"
        "\n1. Use the available tools to fulfil the request. Chain tools when needed"
        " (e.g. read an email then create a calendar event from its content)."
        "\n2. Use conversation history and stored facts to fill in missing details"
        " before deciding a parameter is truly unknown."
        "\n3. If a REQUIRED parameter is genuinely missing and cannot be inferred,"
        " ask ONE short clarifying question in plain text and stop — no tool call."
        " Keep it direct: 'Which account?' / 'Which date?' / 'Inbox or sent?'"
        " Never ask about optional parameters that have sensible defaults."
        "\n4. When you are done with all tool calls, write a concise final answer"
        " in plain prose summarising what you did and what you found."
        " Do not dump raw tool output — narrate it naturally."
        "\n5. If the user states a preference or personal fact, call `remember` to"
        " store it for future sessions."
        "\n6. For follow-up questions about something already in the conversation"
        " ('what was it about', 'when is that'), answer directly from history"
        " without calling a tool."
        "\nReply in plain prose. No bullet points unless listing multiple items."
    )


@simple_service
class AI:
    client = None

    def __init__(self) -> None:
        local = Cache.get_local()
        if local:
            self.client = ollama.Client()
            return

        response = helpers_model.get_model()
        if response is None:
            raise Exception(
                "You need to set either the GEMINI_API_KEY or ANTHROPIC_API_KEY environment variable."
            )

        model, api_key = response
        if model == "gemini":
            self.client = genai.Client(api_key=api_key)

        elif model == "sonnet":
            self.client = anthropic.Anthropic(api_key=api_key)

    @capture_response
    @method_job
    def ask_question(
        self,
        question: str = "",
    ) -> str:
        """
        [AI SERVICE METHOD] Processes general knowledge questions through AI language models.
        This service method handles open-ended questions, information requests, and general queries
        that don't require specific system actions or external API calls.

        Use this method for: general questions, information retrieval, knowledge queries, facts,
        explanations, definitions, conversational responses, or when no other specific tool matches the query.

        Keywords: ask, question, what is, how to, explain, tell me, information, know, answer,
                 general question, inquiry, knowledge, facts, definition, explanation

        Args:
            question (str): The question to ask the AI assistant.

        Returns:
            str: The AI assistant's response to the question based on its knowledge base.
        """

        if not question:
            return "Error: No question provided."

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(f"Asking {question}...")
        print(f"Asking {question}...")

        assistant_instructions = (
            _persona()
            + " You are a knowledgeable, factual assistant."
            " Answer every question using your general knowledge: dates, names, facts, definitions, history, science, culture."
            " Always resolve pronouns and references (e.g. 'he', 'she', 'it', 'they', 'that one') using"
            " prior messages in the conversation history before answering."
            " Never refuse to answer a factual question — if you know the answer, state it directly."
            " Never describe people or objects visually (appearance, clothing, hair) unless the user"
            " explicitly asks about appearance or looks."
            " Reply in plain prose. No bullet points unless listing multiple distinct items."
            " Keep answers concise: 1-3 sentences for simple facts, more only if the question requires it."
        )

        response = helpers_model.send_message(
            client=self.client,
            message=question,
            system_instructions=assistant_instructions,
            history=Conversation.get_messages(),
        )

        answer = helpers_model.get_text_from_response(response)

        if answer is None:
            return "Error: Could not retrieve an answer."

        return answer

    @register_job
    @capture_response
    @staticmethod
    def clear_conversation() -> str:
        """
        [AI SERVICE JOB] Clears the conversation history so the assistant starts fresh.
        Useful when switching topics or wanting a clean slate.

        Use this job when the user wants to:
        - Start a new conversation
        - Reset memory
        - Forget previous messages
        - Clear chat history

        Keywords: forget, new conversation, clear chat, start over, reset memory,
                 clear history, fresh start, wipe memory, reset chat

        Args:
            None

        Returns:
            str: Confirmation that history was cleared.
        """
        Conversation.clear()
        return "Conversation history cleared."

    @register_job
    @capture_response
    @staticmethod
    def remember(fact: str = "") -> str:
        """
        [AI SERVICE JOB] Saves a personal fact or preference to persistent memory.
        Use this when the user tells you to remember something about themselves,
        their preferences, or any fact that should be recalled in future sessions.

        Use this job when the user wants to:
        - Store a personal preference ("remember I prefer metric units")
        - Save a fact ("remember my boss is Anna")
        - Set a default ("remember my default account is work")

        Keywords: remember, save fact, store preference, keep in mind, note that,
                 don't forget, memorize

        Args:
            fact (str): The fact or preference to remember, as stated by the user.

        Returns:
            str: Confirmation that the fact was saved.
        """
        from helpers.profile import Profile

        if not fact:
            return "Error: No fact provided to remember."

        # Derive a short key from the fact text
        import re
        key = re.sub(r"[^a-z0-9_]", "_", fact.lower().strip())[:40].strip("_")
        if not key:
            key = "note"
        Profile.set(key, fact)
        return f"Remembered: {fact}"

    @register_job
    @capture_response
    @staticmethod
    def forget(key: str = "") -> str:
        """
        [AI SERVICE JOB] Removes a previously remembered fact from persistent memory.
        Use this when the user wants to delete a stored preference or fact.

        Use this job when the user wants to:
        - Delete a remembered fact ("forget my preferred units")
        - Remove a stored preference
        - Clear a specific memory entry

        Keywords: forget, remove fact, delete preference, stop remembering, clear memory entry

        Args:
            key (str): The key or description of the fact to forget.

        Returns:
            str: Confirmation that the fact was removed, or notice that it was not found.
        """
        from helpers.profile import Profile

        if not key:
            return "Error: No key provided."

        removed = Profile.remove(key)
        if removed:
            return f"Forgotten: {key}"
        # Try partial match
        all_facts = Profile.all()
        matches = [k for k in all_facts if key.lower() in k.lower()]
        if matches:
            for m in matches:
                Profile.remove(m)
            return f"Forgotten: {', '.join(matches)}"
        return f"No memory found matching: {key}"

    @register_job
    @capture_response
    @staticmethod
    def list_memory() -> str:
        """
        [AI SERVICE JOB] Lists all facts and preferences stored in persistent memory.

        Use this job when the user wants to:
        - See what the assistant remembers about them
        - Review stored preferences
        - Check what facts are saved

        Keywords: list memory, show memory, what do you remember, my facts,
                 stored preferences, show facts, memory

        Args:
            None

        Returns:
            str: All stored facts and preferences.
        """
        from helpers.profile import Profile

        facts = Profile.all()
        if not facts:
            return "No facts stored in memory."
        lines = [f"  {k}: {v}" for k, v in sorted(facts.items())]
        return "Stored memory:\n" + "\n".join(lines)

    def get_function_to_call(
        self,
        user_input: str,
        available_tools: typing.List[typing.Callable],
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not user_input or not available_tools:
            return None

        logger.log_custom(
            "ai_function_selection",
            f"AI determining function for input: {user_input}",
            user_input,
            "",
            "",
        )

        assistant_instructions = build_agent_system_prompt()

        response = helpers_model.send_message(
            client=self.client,
            message=user_input,
            available_tools=available_tools,
            system_instructions=assistant_instructions,
            history=Conversation.get_messages(),
        )

        function_to_call = helpers_model.get_function_from_response(response)

        if function_to_call:
            logger.log_custom(
                "ai_function_selected",
                f"AI selected function: {function_to_call.get('name', 'unknown')}",
                user_input,
                function_to_call.get("name", "unknown"),
                str(function_to_call.get("args", {})),
            )
            return function_to_call

        # No tool selected — router replied with plain text (clarification or direct answer)
        text = helpers_model.get_text_from_response(response)
        if text:
            logger.log_custom(
                "ai_text_response",
                f"AI replied with text: {text[:80]}",
                user_input,
                "text_response",
                "",
            )
            return {"name": "__text__", "args": {}, "text": text}

        logger.log_error(
            "AI could not determine function to call", "get_function_to_call"
        )
        return None

    def explain_screenshot(
        self,
        user_input: str,
        screenshot: np.ndarray,
    ) -> str:
        assistant_instructions = (
            _persona()
            + " You are tasked with explaining what is shown in the screenshot."
            " If there is highlighted or selected text, focus on that text and explain its meaning or context."
            " If there is no highlighted text, describe what the screenshot shows: the application, content, and any"
            " notable elements visible."
            " Reply in plain prose, 1-3 sentences. Be direct and specific — avoid vague descriptions."
        )

        try:
            response = helpers_model.send_message(
                client=self.client,
                message=user_input,
                system_instructions=assistant_instructions,
                image=screenshot,
            )

        except:
            return "Error: Could not retrieve an answer."

        answer = helpers_model.get_text_from_response(response)
        if answer is None:
            return "Error: Could not retrieve an answer."

        return answer

    def find_text_in_screenshot(
        self,
        screenshot: np.ndarray,
        text: str,
    ) -> typing.Optional[typing.List[float]]:
        assistant_instructions = (
            _persona()
            + " Your only task is to locate the specified text in the screenshot and return its bounding box."
            " Output ONLY a JSON array in the format [ymin, xmin, ymax, xmax] with values normalized to 0-1000."
            " Example: [120, 340, 180, 620]"
            " Do not include any explanation, label, or extra text — just the array."
            " If the text is not visible in the screenshot, output exactly: [0, 0, 0, 0]"
        )

        try:
            response = helpers_model.send_message(
                client=self.client,
                message=text,
                system_instructions=assistant_instructions,
                image=screenshot,
            )

        except:
            return None

        answer = helpers_model.get_text_from_response(response)
        if answer is None:
            return None

        try:
            import ast
            clean = answer.strip().strip("```json").strip("```").strip()
            coordinates = ast.literal_eval(clean)

            if not isinstance(coordinates, list) or len(coordinates) != 4:
                raise ValueError("Couldn't find the text in the screenshot.")

            return coordinates
        except Exception:
            raise ValueError("Couldn't find the text in the screenshot.")
