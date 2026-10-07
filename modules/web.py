import re
import typing
from urllib.parse import urlsplit

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.net import is_public_url
from helpers.requirements import Requirement
from helpers.untrusted import wrap


# How much of a fetched page reaches the model. A tuning knob, not a setting:
# the tradeoff is answer quality against tokens per request, and a user has no
# way to judge where that line sits.
_MAX_CONTENT_CHARS = 6000


def _web_requirement() -> Requirement:
    return Requirement(
        # `ddgs` is the current name of the package formerly published as
        # duckduckgo-search, which is no longer maintained under the old name.
        pip_modules=["ddgs"],
        setup_hint=(
            "Run install.bat again and tick Web search + URL fetch. "
            "Optional: paste a Tavily key here for better search results."
        ),
    )


@register_job(
    module_name="web",
    requires=_web_requirement(),
    summary="Search the web for current information",
)
@capture_response
def web_search(query: str) -> str:
    """
    [WEB JOB] Searches the web for current, up-to-date information on any topic.
    Use this to answer questions about recent events, current news, facts that may
    have changed since the AI's training cutoff, or anything requiring live data.

    Args:
        query (str): The search query. Be specific for better results. (required)

    Returns:
        str: Summarized web search results with source titles and snippets.
    """
    if not query:
        return "Error: No search query provided."

    results = _do_search(query)
    if not results:
        return f"No results found for '{query}'."

    from helpers.turn_context import record_search_hrefs

    record_search_hrefs(r.get("href", r.get("url", "")) for r in results)

    lines = [f"Web search results for '{query}':"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        body = r.get("body", r.get("snippet", "")).strip()
        url = r.get("href", r.get("url", ""))
        lines.append(f"\n{i}. {title}")
        if body:
            preview = body[:300]
            if len(body) > 300:
                preview += "…"
            lines.append(f"   {preview}")
        if url:
            lines.append(f"   Source: {url}")
    # Titles and snippets are whatever the page authors wrote.
    return lines[0] + "\n" + wrap("\n".join(lines[1:]), "web search")


_BROWSE_JOB = "browse"
# Static text shorter than this usually means the page builds itself with
# JavaScript, so it is rendered in a real browser instead.
_RENDER_BELOW_CHARS = 200


def _host_named(host: str, text: str) -> bool:
    """Whether `host` appears in `text` as a whole domain, not merely as a
    substring of a longer one ("evil-example.com" naming "example.com")."""
    pattern = r"(?<![\w.-])" + re.escape(host) + r"(?![\w.-])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _needs_ok(args: typing.Dict[str, typing.Any]) -> bool:
    """A page the user never asked for needs their go-ahead before Wony visits
    it — with or without a task. An email or a page can carry a link built to
    leak data ("visit evil.example/?inbox=..."), and reading it is exactly as
    able to carry that data out as clicking through it is.

    No confirm is needed when the URL is one `web_search` itself returned
    this turn (the search was the ask), or when the user's own words name the
    site.
    """
    url = str(args.get("url", "")).strip()
    if not url:
        return False

    from helpers.turn_context import search_hrefs

    if url in search_hrefs():
        return False

    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return True
    from helpers.conversation import Conversation
    from helpers.turn_context import user_text
    from helpers.untrusted import without_fenced

    said = [user_text()] + [m["content"] for m in Conversation.get_messages() if m["role"] == "user"]
    # A forwarded message is stored beside the user's words, fenced. A link in
    # it is exactly the kind this check exists to ask about.
    return not any(_host_named(host, without_fenced(str(text))) for text in said)


@register_job(
    module_name="web",
    requires=Requirement(
        pip_modules=["httpx"],
        setup_hint="Run install.bat again and tick Web search + URL fetch.",
    ),
    summary="Read a web page, or click through it to find something",
    confirms=_needs_ok,
)
@capture_response
def browse(url: str, task: str = "", offset: int = 0) -> str:
    """
    [WEB JOB] Opens a web page. Without a task it returns the page's text. With a task
    ("open the Specs tab and find the battery size", "search the site for X") it
    works through the page in a real browser — clicking, typing, scrolling — in the
    background, and reports back when done. It is logged out: it cannot sign in, buy
    anything or download files.

    Args:
        url (str): The full URL, starting with http:// or https://. (required)
        task (str): What to do or find on the page. Empty just reads it.
        offset (int): When reading, where to continue a page that was cut short.

    Returns:
        str: The page text, or confirmation that the task is under way.
    """
    if not url:
        return "Error: No URL provided."
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"
    if not is_public_url(url):
        return f"I don't open {url}: it points at this computer or the local network."

    if task.strip():
        return _start_task(url, task.strip())
    return _do_fetch(url, max(0, int(offset or 0)))


def _start_task(url: str, task: str) -> str:
    from helpers import browser
    from helpers.jobs import BackgroundJobs

    if not browser.available():
        return (
            "Clicking through pages needs the browser feature: run python setup.py "
            "and tick 'Web browsing'. I can still read the page without a task."
        )
    if BackgroundJobs.is_running(_BROWSE_JOB):
        return "I'm already working through a page. Ask me to stop background jobs to cancel it."

    def work(stop: typing.Any) -> None:
        answer = _run_task(browser, url, task, stop)
        _deliver(url, task, answer)

    BackgroundJobs.start(_BROWSE_JOB, work, pass_stop_event=True)
    return f"On it — I'll open {url} and tell you what I find."


def _run_task(browser: typing.Any, url: str, task: str, stop: typing.Any) -> str:
    import threading

    from helpers.events import session_cancel

    timed_out = threading.Event()
    timer = threading.Timer(browser.TIMEOUT_SECONDS, timed_out.set)
    timer.daemon = True

    class _Cancel:
        @staticmethod
        def is_set() -> bool:
            return stop.is_set() or session_cancel.is_set() or timed_out.is_set()

    timer.start()
    try:
        answer = browser.run_task(url, task, _Cancel())
    except browser.BrowserUnavailable as e:
        return str(e)
    except Exception as e:
        logger.log_error(str(e), "browse")
        return f"I couldn't finish that on {url}: {e}"
    finally:
        timer.cancel()
    if timed_out.is_set():
        return f"I ran out of time on {url}. So far: {answer}"
    return answer


def _deliver(url: str, task: str, answer: str) -> None:
    """Say the result, and put it in the conversation so "what was it?" works."""
    from helpers.conversation import Conversation
    from helpers.decorators import agent_lock
    from helpers.notify import notify

    notify(answer, kind="info", source="browse")
    # Under agent_lock: a turn in progress owns the conversation history.
    with agent_lock:
        Conversation.record_turn(f"(Wony browsed {url} for: {task})", wrap(answer, url))


# ------------------------------------------------------------------ internals


def _do_search(query: str, max_results: int = 5) -> typing.List[typing.Dict]:
    import os

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        try:
            return _tavily_search(query, tavily_key, max_results)
        except Exception as e:
            # Falling back to DuckDuckGo is right, but doing it silently meant a
            # bad TAVILY_API_KEY looked exactly like a working one.
            import helpers.diagnostics
            helpers.diagnostics.add(
                "warning", "Web", f"Tavily search failed, using DuckDuckGo: {e}"
            )

    return _ddg_search(query, max_results)


def _tavily_search(query: str, api_key: str, max_results: int) -> typing.List[typing.Dict]:
    import httpx

    # Bearer header, not an api_key field in the body — the body form is the
    # legacy contract and is no longer what Tavily documents.
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"query": query, "max_results": max_results},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    return [
        {"title": r.get("title", ""), "body": r.get("content", ""), "href": r.get("url", "")}
        for r in results
    ]


def _ddg_search(query: str, max_results: int) -> typing.List[typing.Dict]:
    from ddgs import DDGS

    return list(DDGS().text(query, max_results=max_results))


def _do_fetch(url: str, offset: int = 0) -> str:
    max_chars = _MAX_CONTENT_CHARS
    try:
        text = _static_text(url)
    except Exception as e:
        text, problem = "", f"Error fetching {url}: {e}"
    else:
        problem = ""

    # Pages built by JavaScript come back near-empty, and some sites refuse
    # plain HTTP clients outright; a real browser gets both.
    if len(text.strip()) < _RENDER_BELOW_CHARS:
        from helpers import browser

        if browser.available():
            try:
                text = browser.render_text(url)
            except Exception as e:
                logger.log_error(str(e), "browse.render")
    if problem and not text.strip():
        return problem

    if not text.strip():
        return f"Could not extract text content from {url}."

    if offset >= len(text):
        return f"{url} has only {len(text)} characters — nothing at offset {offset}."

    page = text[offset:offset + max_chars]
    end = offset + len(page)
    suffix = (
        f"\n\n[Characters {offset}–{end} of {len(text)}. Read on with offset={end}.]"
        if end < len(text) else ""
    )
    return f"Content from {url}:\n\n{wrap(page, url)}{suffix}"


def _static_text(url: str) -> str:
    import httpx

    response = httpx.get(
        url,
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WonyAssistant/1.0)"},
        # Every hop, so a public page cannot redirect into the local network.
        event_hooks={"request": [_refuse_private_hop]},
    )
    response.raise_for_status()
    try:
        import trafilatura

        return trafilatura.extract(response.text) or _strip_html(response.text)
    except ImportError:
        return _strip_html(response.text)


def _refuse_private_hop(request: typing.Any) -> None:
    if not is_public_url(str(request.url)):
        raise ValueError(f"redirected to {request.url}, which is on this computer or the local network")


def _strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except ImportError:
        import re
        return re.sub(r"<[^>]+>", " ", html)
