import typing

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement


def _web_requirement() -> Requirement:
    return Requirement(
        pip_modules=["duckduckgo_search"],
        setup_hint=(
            "pip install -r requirements/web.txt\n"
            "Optional: add TAVILY_API_KEY to .env for higher-quality search results."
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

    Use this job when the user wants to:
    - Look up current news or recent events
    - Find up-to-date facts, prices, or status
    - Research a topic with live web results
    - Ask about anything post-training-cutoff

    Keywords: search, look up, find, google, web, current, latest, news, what's happening,
             today's, recent, now, 2024, 2025, check online

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
    return "\n".join(lines)


@register_job(
    module_name="web",
    requires=Requirement(
        pip_modules=["httpx"],
        setup_hint="pip install -r requirements/web.txt",
    ),
    summary="Fetch and read the text content of a URL",
)
@capture_response
def fetch_url(url: str) -> str:
    """
    [WEB JOB] Fetches the main text content of a web page URL.
    Use this to read a specific article, documentation page, or any URL the user provides.
    Chain with web_search to first find a URL, then read its full content.

    Use this job when the user wants to:
    - Read the content of a specific URL
    - Get the full text of an article or page
    - Follow up a web search by reading one of the results

    Keywords: read, open, fetch, get content, read article, open link, visit url,
             what does this page say, read this link

    Args:
        url (str): The full URL to fetch (must start with http:// or https://). (required)

    Returns:
        str: The main text content of the page, truncated if very long.
    """
    if not url:
        return "Error: No URL provided."
    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    return _do_fetch(url)


# ------------------------------------------------------------------ internals

def _do_search(query: str, max_results: int = 5) -> typing.List[typing.Dict]:
    import os

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        try:
            return _tavily_search(query, tavily_key, max_results)
        except Exception:
            pass

    return _ddg_search(query, max_results)


def _tavily_search(query: str, api_key: str, max_results: int) -> typing.List[typing.Dict]:
    import httpx

    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"query": query, "max_results": max_results, "api_key": api_key},
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
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return results


def _do_fetch(url: str) -> str:
    from helpers.config import Config

    max_chars = int(Config.get("modules.web.max_content_chars", 3000))

    try:
        import trafilatura
        import httpx

        response = httpx.get(url, timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; WonyAssistant/1.0)"
        })
        response.raise_for_status()
        text = trafilatura.extract(response.text)
        if not text:
            text = response.text[:max_chars]
    except ImportError:
        import httpx
        response = httpx.get(url, timeout=15, follow_redirects=True)
        response.raise_for_status()
        text = _strip_html(response.text)
    except Exception as e:
        return f"Error fetching {url}: {e}"

    if not text:
        return f"Could not extract text content from {url}."

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[Content truncated at {max_chars} chars. Full page is longer.]"

    return f"Content from {url}:\n\n{text}"


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
