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
        + "\n\nYou are an intelligent agent with access to tools for music (Spotify),"
        " email (Gmail), calendar (Google Calendar), web search, desktop control,"
        " persistent memory, reminders, and general knowledge."
        " Follow these rules for every user request:"

        "\n\n1. GREET AND ORIENT: If the user greets you (hello, hi, hey, good morning,"
        " good afternoon, good evening, greetings, what's up, morning briefing, daily briefing),"
        " call the `greeting` tool immediately — do NOT generate your own greeting."
        " The `greeting` tool returns real-time time, date, weather, unread emails, and today's meetings."
        " After the tool returns, relay its output verbatim."

        "\n\n2. CLARIFY MISSING REQUIRED INFO: Before calling any tool, check whether all"
        " required information is known. Required fields are marked '(required)' in the"
        " tool descriptions. If a required field is missing and cannot be inferred from"
        " conversation history or stored facts, ask ONE short question that names exactly"
        " what you need — e.g. 'What song would you like to play?' or"
        " 'Who should I send the email to, and what should it say?'."
        " Ask no more than one question per turn. Then stop and wait for the answer."

        "\n\n3. DISAMBIGUATE VAGUE REQUESTS: If the user's request could match several"
        " different actions, briefly list the options and ask which one they mean."
        " Example: 'I can either send a new email, or add a new Google account."
        " Which did you mean?'"

        "\n\n4. EXPLAIN ON REQUEST: If the user asks 'how do I X', 'what do you need to X',"
        " or 'what information do you need', explain what fields that job requires"
        " (drawn from the tool description) rather than attempting the action."

        "\n\n5. USE TOOLS: Once all required info is known, call the appropriate tool(s)."
        " Chain tools when needed (e.g. read an email then create a calendar event from it,"
        " or web_search then fetch_url to read a specific article)."
        " Use conversation history and stored facts to fill in details before asking."

        "\n\n6. NARRATE RESULTS: When done, write a concise answer in plain prose"
        " summarising what you did and found. Do not dump raw tool output."

        "\n\n7. REMEMBER FACTS: If the user states a personal preference or fact,"
        " call `remember` to store it for future sessions."

        "\n\n8. ANSWER FROM HISTORY: For follow-up questions about something already in"
        " the conversation ('what was it about', 'when is that'),"
        " answer directly from history without calling a tool."

        "\n\n9. RECALL FROM PERSISTENT HISTORY: If the user asks about past conversations"
        " across sessions ('what did we discuss last week', 'did I mention X before',"
        " 'what did we talk about on Monday'), call `search_history` or `recall_on_date`"
        " to query the persistent SQLite conversation database. Do NOT claim you cannot"
        " remember past sessions — use these tools first."

        "\n\n10. USE WEB FOR CURRENT INFO: If the user asks about recent events, current"
        " news, live data, or anything that may have changed since your training cutoff,"
        " call `web_search`. Do not fabricate current information — search for it."
        " Chain `fetch_url` after a search to read the full content of a specific result."

        "\n\n11. DESKTOP CONTROL: If the user asks to open an app, switch windows, read"
        " the clipboard, find a file, or type/click on screen, use the desktop tools."
        " Actions that modify state (type_text, click_at, set_clipboard, open_file) require"
        " allow_actions to be enabled in config — if disabled, explain this to the user."

        "\nReply in plain prose. No bullet points unless listing multiple items."
    )


@simple_service
class AI:
    client = None

    def __init__(self) -> None:
        response = helpers_model.get_model()
        if response is None:
            raise Exception(
                "You need to set either the GEMINI_API_KEY or ANTHROPIC_API_KEY environment variable."
            )

        model, api_key = response
        if model == "gemini":
            self.client = genai.Client(api_key=api_key)
        elif model == "anthropic":
            self.client = anthropic.Anthropic(api_key=api_key)
        elif model == "ollama":
            self.client = ollama.Client()

    @capture_response
    @method_job
    def ask_question(
        self,
        question: str,
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
            question (str): The question to ask the AI assistant. (required)

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

    @register_job
    @capture_response
    @staticmethod
    def search_history(keyword: str = "", days_back: int = 30, limit: int = 5) -> str:
        """
        [AI SERVICE JOB] Searches persistent conversation history for past exchanges matching a keyword.
        Queries the local SQLite database of all past conversations that survive restarts.

        Use this job when the user wants to:
        - Find what was discussed about a topic ("what did we say about the dentist")
        - Recall a past conversation by keyword
        - Look up something mentioned in a previous session

        Keywords: what did we discuss, do you remember, look up history, past conversation,
                 recall, find in history, search history, previous session

        Args:
            keyword (str): Word or phrase to search for in past conversations. (required)
            days_back (int): How many days back to search (default 30).
            limit (int): Max number of results to return (default 5).

        Returns:
            str: Matching past exchanges with timestamps, or a message if nothing found.
        """
        from helpers.memory_db import search_turns

        if not keyword:
            return "Error: No keyword provided."

        results = search_turns(keyword, days_back=int(days_back), limit=int(limit))
        if not results:
            return f"No past conversations found matching '{keyword}' in the last {days_back} days."

        lines = [f"Found {len(results)} past exchange(s) matching '{keyword}':"]
        for r in results:
            ts = r.get("ts", "")[:16].replace("T", " ")
            lines.append(f"\n[{ts}]")
            lines.append(f"  You: {r['user_text']}")
            if r.get("assistant_text"):
                preview = r["assistant_text"][:200]
                if len(r["assistant_text"]) > 200:
                    preview += "…"
                lines.append(f"  Assistant: {preview}")
        return "\n".join(lines)

    @register_job
    @capture_response
    @staticmethod
    def recall_on_date(date_str: str = "") -> str:
        """
        [AI SERVICE JOB] Retrieves all conversation exchanges from a specific date.
        Queries the persistent SQLite conversation history.

        Use this job when the user wants to:
        - See what was discussed on a specific day ("what did we talk about Tuesday")
        - Review a day's conversation history
        - Look up exchanges from a date like "last Monday" or "2024-12-25"

        Keywords: what did we talk about on, conversations from, history on, recall Tuesday,
                 what happened on, exchanges on date

        Args:
            date_str (str): Date to retrieve history for, e.g. "yesterday", "last Monday",
                           "2024-12-25". (required)

        Returns:
            str: All exchanges from that date, or a message if none found.
        """
        from helpers.memory_db import turns_on_date

        if not date_str:
            return "Error: No date provided."

        results = turns_on_date(date_str)
        if not results:
            return f"No conversation history found for '{date_str}'."

        lines = [f"Conversation history for '{date_str}' ({len(results)} exchange(s)):"]
        for r in results:
            ts = r.get("ts", "")[:16].replace("T", " ")
            lines.append(f"\n[{ts}]")
            lines.append(f"  You: {r['user_text']}")
            if r.get("assistant_text"):
                preview = r["assistant_text"][:200]
                if len(r["assistant_text"]) > 200:
                    preview += "…"
                lines.append(f"  Assistant: {preview}")
        return "\n".join(lines)

    @register_job
    @capture_response
    @staticmethod
    def recent_history(limit: int = 10) -> str:
        """
        [AI SERVICE JOB] Retrieves the most recent conversation exchanges from persistent history,
        including exchanges from previous sessions that survive restarts.

        Use this job when the user wants to:
        - See the last N conversation exchanges across all sessions
        - Review recent history beyond the current session window
        - Check what was discussed recently

        Keywords: recent history, last conversations, what did we talk about recently,
                 show recent, last N exchanges, history

        Args:
            limit (int): Number of most recent exchanges to return (default 10).

        Returns:
            str: The most recent conversation exchanges with timestamps.
        """
        from helpers.memory_db import recent_turns

        results = recent_turns(limit=int(limit))
        if not results:
            return "No conversation history found."

        lines = [f"Most recent {len(results)} exchange(s):"]
        for r in results:
            ts = r.get("ts", "")[:16].replace("T", " ")
            lines.append(f"\n[{ts}]")
            lines.append(f"  You: {r['user_text']}")
            if r.get("assistant_text"):
                preview = r["assistant_text"][:200]
                if len(r["assistant_text"]) > 200:
                    preview += "…"
                lines.append(f"  Assistant: {preview}")
        return "\n".join(lines)

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
        except Exception:
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
        except Exception:
            return None

        answer = helpers_model.get_text_from_response(response)
        if answer is None:
            return None

        try:
            import ast
            clean = answer.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
            coordinates = ast.literal_eval(clean)

            if not isinstance(coordinates, list) or len(coordinates) != 4:
                raise ValueError("Couldn't find the text in the screenshot.")

            return coordinates
        except Exception:
            raise ValueError("Couldn't find the text in the screenshot.")
