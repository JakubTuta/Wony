import typing

import anthropic
import numpy as np
import ollama
from google import genai

import helpers.model as helpers_model
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import method_job, simple_service


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

        assistant_instructions = _persona() + " Answer the question as if you are a human. Keep the answer short and simple."

        response = helpers_model.send_message(
            client=self.client,
            message=question,
            system_instructions=assistant_instructions,
        )

        answer = helpers_model.get_text_from_response(response)

        if answer is None:
            return "Error: Could not retrieve an answer."

        return answer

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
            + " You are tasked with determining the function to call based on the user's input."
            " Make use of the keywords in the input to identify the appropriate function."
            " If no function is applicable, return 'ask_question' as the default function."
        )

        response = helpers_model.send_message(
            client=self.client,
            message=user_input,
            available_tools=available_tools,
            system_instructions=assistant_instructions,
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
            + " You are tasked with explaining the contents of the screenshot."
            " If there is highlighted text, focus on that and provide a concise explanation."
            " Keep the answer short and simple."
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
            + " You are tasked with finding the text specified by user in the screenshot."
            " Provide the bounding box coordinates in the format [ymin, xmin, ymax, xmax] normalized to 0-1000."
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
