import typing


def summarize(content: str, instruction: str) -> typing.Optional[str]:
    """Pass `content` through the configured AI with `instruction`.

    Returns the AI text on success, or None on any failure so the caller
    can fall back to raw output.  Does not touch conversation history.
    """
    try:
        from helpers.registry import ServiceRegistry
        import helpers.model as helpers_model
        from modules.ai import _persona

        ai = ServiceRegistry.get_service_instance("ai")
        if ai is None or getattr(ai, "client", None) is None:
            return None

        system_prompt = (
            f"{_persona()}\n\n"
            f"{instruction}\n\n"
            "Reply in concise prose or a tight bullet list. No markdown headers."
        )

        response = helpers_model.send_message(
            client=ai.client,
            message=content,
            system_instructions=system_prompt,
        )
        return helpers_model.get_text_from_response(response)
    except Exception:
        return None
