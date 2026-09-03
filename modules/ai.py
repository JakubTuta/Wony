import typing

import anthropic
import ollama
from google import genai
from google.genai import types as genai_types

import helpers.model as helpers_model
from helpers.conversation import Conversation
from helpers.decorators import capture_response
from helpers.registry import method_job, register_job, simple_service

_AI_CLIENT_TIMEOUT_SECONDS = 45.0
_ANTHROPIC_MAX_RETRIES = 1


def _extract_text(path: str) -> str:
    """Extract plain text from a file. Supports .txt/.md/plain and .pdf."""
    import os

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            try:
                import pdfminer.high_level

                return pdfminer.high_level.extract_text(path)
            except ImportError:
                pass
            try:
                from pypdf import PdfReader

                reader = PdfReader(path)
                return "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                pass
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


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


def build_agent_system_prompt() -> typing.List[str]:
    """System prompt for the multi-step agent loop, as [stable, volatile] blocks.

    Split so the stable half can sit inside the provider's cached prefix: the
    clock ticks every minute and would otherwise invalidate the whole prompt —
    and everything after it — on every single request.
    """
    import datetime

    now = datetime.datetime.now().astimezone()
    volatile = (
        f"Current local date and time: {now.strftime('%A, %B %d, %Y, %H:%M')} ({now.tzname()})."
        " Use this for any time, date, or scheduling reasoning — never guess the date."
    )
    stable = (
        _persona()
        + "\n\nYou are an intelligent agent with access to tools for music (Spotify),"
        " email (Gmail), calendar (Google Calendar), the smart home, web search,"
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
        " Do not write any narration text in the same step as a tool call —"
        " no 'Let me check that' or 'Playing that now' before calling a tool."
        " Call the tool silently, then narrate only in the final step once you"
        " have its result."
        "\n\n7. REMEMBER FACTS: If the user states a personal preference or fact,"
        " call `memory` with action 'save' to store it for future sessions."
        "\n\n8. ANSWER FROM HISTORY — BUT FETCH WHEN ASKED FOR MORE: For a follow-up"
        " whose answer is already fully present in the conversation ('what was it about',"
        " 'when is that'), answer directly from history. But if the user asks for detail"
        " you do NOT already have — e.g. the briefing listed unread senders and they now"
        " ask to read those emails, see the bodies, or get details of today's meetings —"
        " call the matching email/calendar tool to fetch it (find_emails, read_email,"
        " find_events, etc.). You DO have access to the user's Gmail and Calendar via"
        " these tools: never reply that you cannot access their email or calendar. A tool"
        " returning zero results is a valid answer ('no unread emails'), not an error."
        " This applies to timers/reminders too — 'how much time is left' or 'is my alarm"
        " still running' means call `list_reminders` for the real remaining time. Never"
        " compute or guess a countdown yourself from when it was set."
        "\n\n9. RECALL FROM PERSISTENT HISTORY: If the user asks about past conversations"
        " across sessions ('what did we discuss last week', 'did I mention X before',"
        " 'what did we talk about on Monday'), call `recall` — pass `query` for a topic,"
        " `date` for a specific day, or neither for the latest exchanges."
        " Do NOT claim you cannot remember past sessions — use that tool first."
        "\n\n10. USE WEB FOR CURRENT INFO: If the user asks about recent events, current"
        " news, live data, or anything that may have changed since your training cutoff,"
        " call `web_search`. Do not fabricate current information — search for it."
        " Chain `fetch_url` after a search to read the full content of a specific result."
        "\n\n11. NEVER FABRICATE AN ACTION OR A LIVE VALUE: If the user asks you to do"
        " something (open an app, play music, control a device, send something) or asks"
        " for a value that can change over time (time remaining, what's playing, current"
        " state of a device), you MUST call the matching tool and base your reply on its"
        " actual result. Do not say something was done, or give a number or status, unless"
        " a tool call in this turn returned it — a plausible-sounding guess is worse than"
        " asking a clarifying question or saying you're not sure."
        " A setting the user can also change outside Wony — playback volume, a light's"
        " brightness, a thermostat — is one of those live values: call the tool again"
        " even if it was set or read earlier in this conversation, and never compute a"
        " relative change ('a bit louder') from the number you saw last time."
        "\nReply in plain prose. No bullet points unless listing multiple items."
    )
    return [stable, volatile]


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
            self.client = genai.Client(
                api_key=api_key,
                http_options=genai_types.HttpOptions(
                    timeout=int(_AI_CLIENT_TIMEOUT_SECONDS * 1000)
                ),
            )
        elif model == "anthropic":
            self.client = anthropic.Anthropic(
                api_key=api_key,
                timeout=_AI_CLIENT_TIMEOUT_SECONDS,
                max_retries=_ANTHROPIC_MAX_RETRIES,
            )
        elif model == "ollama":
            self.client = ollama.Client(timeout=_AI_CLIENT_TIMEOUT_SECONDS)

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

        explanations, definitions, conversational responses, or when no other specific tool matches the query.

        Args:
            question (str): The question to ask the AI assistant. (required)

        Returns:
            str: The AI assistant's response to the question based on its knowledge base.
        """

        if not question:
            return "Error: No question provided."

        assistant_instructions = (
            _persona() + " You are a knowledgeable, factual assistant."
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

        Returns:
            str: Confirmation that history was cleared.
        """
        Conversation.clear()
        return "Conversation history cleared."

    @register_job
    @capture_response
    @staticmethod
    def memory(action: str = "list", fact: str = "", topic: str = "") -> str:
        """
        [AI SERVICE JOB] The assistant's long-term memory of personal facts and
        preferences: save one, forget one, or list everything stored. Saved facts are
        available in every future session.

        Args:
            action (str): "list" (the default), "save", or "forget".
            fact (str): The fact to save, as the user stated it. (required when saving)
            topic (str): Short snake_case subject the fact is about, e.g. "preferred_units",
                "boss". Reuse the same topic when updating a fact so it overwrites rather
                than duplicates; derived from the fact text if omitted. Names which fact
                to remove when forgetting.

        Returns:
            str: The stored memory, or confirmation of the change.
        """
        import re

        from helpers.profile import Profile

        wanted = (action or "list").strip().lower()

        if wanted in ("list", "show", "all"):
            facts = Profile.all()
            if not facts:
                return "No facts stored in memory."
            return "Stored memory:\n" + "\n".join(
                f"  {key}: {value}" for key, value in sorted(facts.items())
            )

        if wanted in ("save", "remember", "store", "add"):
            if not fact:
                return "Error: No fact provided to remember."
            # A model-supplied topic is what makes "I like tea" overwrite "I like
            # coffee" instead of accumulating a near-duplicate on every restatement.
            key = re.sub(r"[^a-z0-9_]+", "_", (topic or fact).lower().strip())[:40].strip("_")
            Profile.set(key or "note", fact)
            return f"Remembered ({key or 'note'}): {fact}"

        if wanted in ("forget", "remove", "delete"):
            key = topic or fact
            if not key:
                return "Error: Say which fact to forget."
            if Profile.remove(key):
                return f"Forgotten: {key}"
            matches = [k for k in Profile.all() if key.lower() in k.lower()]
            for match in matches:
                Profile.remove(match)
            if matches:
                return f"Forgotten: {', '.join(matches)}"
            return f"No memory found matching: {key}"

        return f"Unknown action '{action}'. Use list, save or forget."

    @register_job
    @capture_response
    @staticmethod
    def recall(query: str = "", date: str = "", limit: int = 5) -> str:
        """
        [AI SERVICE JOB] Searches past conversations, including ones from earlier
        sessions that the current chat no longer holds. Searches by meaning as well as
        by wording, so it answers "what did we say about the dentist", "what did we talk
        about on Tuesday", and "what were we just discussing" alike.

        Args:
            query (str): What to look for. Leave empty to get the most recent exchanges.
            date (str): Restrict to a single day, e.g. "yesterday", "last Monday", "2024-12-25".
            limit (int): How many exchanges to return (default 5).

        Returns:
            str: Matching past exchanges with timestamps.
        """
        from helpers.memory_db import recent_turns, search_turns, turns_on_date

        count = max(1, int(limit or 5))

        if date:
            turns = turns_on_date(date)
            if not turns:
                return f"No conversation history found for '{date}'."
            return AI._render_turns(turns, f"Conversation history for '{date}'")

        if not query:
            turns = recent_turns(limit=count)
            if not turns:
                return "No conversation history found."
            return AI._render_turns(turns, f"Most recent {len(turns)} exchange(s)")

        semantic_lines = AI._semantic_matches(query, count)
        if semantic_lines:
            return semantic_lines

        turns = search_turns(query, days_back=365, limit=count)
        if not turns:
            return f"Nothing in past conversations matches '{query}'."
        return AI._render_turns(turns, f"Past exchanges matching '{query}'")

    @staticmethod
    def _semantic_matches(query: str, count: int) -> str:
        """Meaning-based hits from the embedding store, or "" when it is unavailable
        or finds nothing — the caller then falls back to a keyword search."""
        from helpers import semantic as _sem

        if not _sem.is_available():
            return ""
        try:
            results = _sem.retrieve(query, k=count)
        except Exception:
            return ""
        if not results:
            return ""

        lines = [f"Past exchanges about '{query}' ({len(results)} result(s)):"]
        for result in results:
            text = result["text"]
            preview = text[:300] + ("…" if len(text) > 300 else "")
            lines.append(f"\n[{result['source_type']}]")
            lines.append(f"  {preview}")
        return "\n".join(lines)

    @staticmethod
    def _render_turns(turns: typing.List[typing.Dict], header: str) -> str:
        lines = [f"{header} ({len(turns)} exchange(s)):"]
        for turn in turns:
            stamp = turn.get("ts", "")[:16].replace("T", " ")
            lines.append(f"\n[{stamp}]")
            lines.append(f"  You: {turn['user_text']}")
            answer = turn.get("assistant_text") or ""
            if answer:
                preview = answer[:200] + ("…" if len(answer) > 200 else "")
                lines.append(f"  Assistant: {preview}")
        return "\n".join(lines)

    @register_job
    @capture_response
    @staticmethod
    def index_document(path: str = "") -> str:
        """
        [AI SERVICE JOB] Indexes a local file for semantic recall via ask_my_docs.
        Extracts text from the file and embeds it for future retrieval.
        Supports text files, PDFs (via pdfminer/pypdf2 if available), and plain text.

        Args:
            path (str): Absolute or home-relative path to the file to index. (required)

        Returns:
            str: Confirmation with character count, or error.
        """
        import os

        from helpers import semantic as _sem

        if not path:
            return "Error: No file path provided."

        if not _sem.is_available():
            return "Semantic indexing unavailable — install fastembed: pip install fastembed"

        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            return f"Error: File not found: '{path}'"

        text = _extract_text(path)
        if not text:
            return f"Could not extract text from '{path}'."

        chunks = _sem.store_doc(path, text)
        return (
            f"Indexing '{os.path.basename(path)}' ({len(text)} chars, {chunks} chunk(s)). "
            "Use ask_my_docs to query it."
        )

    @register_job
    @capture_response
    @staticmethod
    def ask_my_docs(query: str = "") -> str:
        """
        [AI SERVICE JOB] Answers a question using semantically indexed personal documents.
        Retrieves the most relevant document chunks and synthesises an answer.

        Args:
            query (str): The question to answer from indexed documents. (required)

        Returns:
            str: Answer synthesised from the most relevant document chunks.
        """
        from helpers import semantic as _sem

        if not query:
            return "Error: No query provided."

        if not _sem.is_available():
            return (
                "Document search unavailable — install fastembed: pip install fastembed"
            )

        results = _sem.retrieve(query, k=5, source_types=["doc"])
        if not results:
            return "No indexed documents found. Use index_document to add files first."

        import os

        blocks = []
        for r in results:
            # ref_key is "<path>#<chunk index>" — name the file so the model can
            # attribute the answer instead of quoting anonymous text.
            source = str(r.get("ref_key") or "").rsplit("#", 1)[0]
            label = os.path.basename(source) or "document"
            blocks.append(f"[{label}]\n{r['text']}")
        return (
            f"From indexed documents (top {len(results)} chunk(s)):\n\n"
            + "\n\n".join(blocks)
        )
