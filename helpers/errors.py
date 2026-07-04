"""Shared error classification helpers for AI provider errors."""
import typing


def classify_api_error(e: Exception) -> typing.Optional[typing.Tuple[str, str]]:
    """Return (user_message, hint) for known API billing/quota errors, else None."""
    msg = str(e)
    if "credit balance is too low" in msg:
        return (
            "Anthropic API credit balance too low.",
            "Add credits at console.anthropic.com/billing, then restart the assistant.",
        )
    if "spending cap" in msg:
        return (
            "Gemini API monthly spending cap exceeded.",
            "Raise your cap at https://ai.studio/spend",
        )
    if "RESOURCE_EXHAUSTED" in msg:
        return (
            "Gemini API quota exceeded. Try again later.",
            None,
        )
    if "rate_limit_error" in msg or "Error code: 429" in msg:
        return (
            "API rate limit reached. Wait a moment and try again.",
            None,
        )
    return None


def emit_api_diagnostic(user_msg: str, hint: typing.Optional[str]) -> None:
    try:
        from helpers.diagnostics import add as _add_diag
        _add_diag("error", "AI provider", user_msg, hint)
    except Exception:
        pass
