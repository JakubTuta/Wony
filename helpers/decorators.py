import functools
import os
import sys
import typing

T = typing.TypeVar("T")

# Set to True by the agent loop while executing tools so capture_response
# suppresses per-tool print/TTS output. The final narrated answer is output once.
_agent_active: bool = False


def set_agent_active(value: bool) -> None:
    global _agent_active
    _agent_active = value


def is_agent_active() -> bool:
    return _agent_active


def capture_response(
    func: typing.Callable[..., typing.Any],
) -> typing.Callable[..., typing.Optional[str]]:
    """
    Decorator that captures the response, prints it to console, and handles audio output.
    Always returns a string response.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> typing.Optional[str]:
        # Lazy imports to avoid circular dependencies
        try:
            from helpers.audio import Audio
            from helpers.cache import Cache
            from helpers.logger import logger
        except ImportError:
            logger = None
            Audio = None
            Cache = None

        function_name = func.__name__ if hasattr(func, "__name__") else "Unknown"
        class_name = (
            args[0].__class__.__name__
            if args and hasattr(args[0], "__class__")
            else "Unknown"
        )

        try:
            response = func(*args, **kwargs)
        except Exception as e:
            error_msg = f"\n[{class_name} - {function_name}]: {e}"
            print(error_msg)

            if logger:
                logger.log_error(str(e), f"{class_name}.{function_name}")
            return error_msg

        str_response = str(response) if response is not None else ""

        # Suppress per-tool output while the agent loop is running;
        # the agent will narrate the final answer once.
        if not _agent_active:
            if Cache and Audio:
                audio = Cache.get_audio()
                if audio:
                    Audio.text_to_speech(str_response)
            print(str_response)

        return str_response

    return wrapper


def capture_exception(
    func: typing.Callable[..., T],
) -> typing.Callable[..., typing.Union[T, None]]:
    """
    Decorator that captures all exceptions and returns them as error messages.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> typing.Union[T, None]:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            class_name = (
                args[0].__class__.__name__
                if args and hasattr(args[0], "__class__")
                else "Unknown"
            )
            function_name = func.__name__ if hasattr(func, "__name__") else "Unknown"

            error_message = f"\n[{class_name} - {function_name}]: {e}"
            print(error_message)

            return None

    return wrapper


def exit_on_exception(func: typing.Callable[..., T]) -> typing.Callable[..., T]:
    """
    Decorator that captures all exceptions and exits the program.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            class_name = (
                args[0].__class__.__name__
                if args and hasattr(args[0], "__class__")
                else "Unknown"
            )
            function_name = func.__name__ if hasattr(func, "__name__") else "Unknown"
            print(f"\n[{class_name} - {function_name}]: {e}")
            sys.exit(1)

    return wrapper


def retry_on_unauthorized(refresh_method_name: str):
    """
    Decorator that retries the function if a 401 or 403 error occurs.
    Calls the refresh token method before retrying.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            import requests

            try:
                return func(self, *args, **kwargs)
            except requests.exceptions.RequestException as e:
                if hasattr(e, "response") and getattr(
                    e.response, "status_code", None
                ) in [401, 403]:
                    # Try to refresh token
                    refresh_method = getattr(self, refresh_method_name, None)
                    if refresh_method:
                        refresh_method(getattr(self, "refresh_token", None))
                        return func(self, *args, **kwargs)

                # Re-raise if not authorization error or refresh failed
                raise

        return wrapper

    return decorator
