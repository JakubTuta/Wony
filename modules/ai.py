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
    """Build persona preamble from config."""
    from helpers.config import Config

    name = Config.get("assistant.name", "Wony")
    owner = Config.get("assistant.owner_name", "User")
    personality = Config.get("assistant.personality", "Friendly and concise.")
    language = Config.get("assistant.language", "en")
    return (
        f"You are {name}, a personal AI assistant for {owner}. "
        f"{personality} Respond in {language}."
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

        assistant_instructions = (
            _persona()
            + " Your ONLY task is to select and call the correct function — you must ALWAYS call a function."
            " Never reply with plain text. Never refuse to call a function."
            "\n\nRouting rules (apply in order):"
            "\n1. If the input requests a SPECIFIC ACTION (play music, set timer, check weather, control lights,"
            " open app, send email, skip song, etc.) — call the matching action function."
            "\n2. If the input is a QUESTION, a request for information, general knowledge, a follow-up"
            " to a previous message, or anything that does not map to a specific action — call 'ask_question'."
            "\n3. If you are uncertain — call 'ask_question'. It is always safe and correct as a fallback."
            "\n\nExamples that must use 'ask_question':"
            " 'who is Einstein', 'when was he born', 'what year did WW2 end', 'explain quantum physics',"
            " 'what does this mean', 'tell me more', follow-up pronouns like 'he/she/it/they'."
            "\n\nYou MUST call a function on every single input. Calling no function is never correct."
        )

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
        else:
            logger.log_error(
                "AI could not determine function to call", "get_function_to_call"
            )

        return function_to_call

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
