import functools
import sys
import threading
import traceback
import typing

T = typing.TypeVar("T")

# Set to True by the agent loop while executing tools so capture_response
# suppresses per-tool print output. The final answer is output once.
_agent_active: bool = False

# Process-wide lock: serializes agent runs so concurrent /api/chat and tile
# calls don't interleave on shared Conversation state or _agent_active.
agent_lock = threading.Lock()


def set_agent_active(value: bool) -> None:
    global _agent_active
    _agent_active = value


def is_agent_active() -> bool:
    return _agent_active


# capture_response turns a raised exception into an ordinary string so the
# agent gets a tool result rather than a traceback. That means callers cannot
# tell success from failure by return type — this prefix is the only signal,
# so it is written once here and read through is_error_response().
_ERROR_PREFIX = "Error ("


def is_error_response(text: typing.Optional[str]) -> bool:
    """True when a job's string came from capture_response's failure path.

    Anything that stores or repeats a job's output needs this: an error cached
    for ten minutes on the idle screen is worse than an empty card.
    """
    return bool(text) and str(text).startswith(_ERROR_PREFIX)


def capture_response(
    func: typing.Callable[..., typing.Any],
) -> typing.Callable[..., typing.Optional[str]]:
    """
    Decorator that captures a job's response, logs failures, and always returns
    a string so the agent gets a tool result instead of an exception.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> typing.Optional[str]:
        # Lazy import to avoid a circular dependency at module import time.
        try:
            from helpers.logger import logger
        except ImportError:
            logger = None

        function_name = func.__name__ if hasattr(func, "__name__") else "Unknown"
        class_name = (
            args[0].__class__.__name__
            if args and hasattr(args[0], "__class__")
            else "Unknown"
        )

        try:
            response = func(*args, **kwargs)
        except Exception as e:
            error_msg = f"{_ERROR_PREFIX}{class_name}.{function_name}): {e}"
            print(error_msg)

            if logger:
                logger.log_error(traceback.format_exc(), f"{class_name}.{function_name}")

            return error_msg

        str_response = str(response) if response is not None else ""

        # Suppress per-tool output while the agent loop is running;
        # the agent reports the final answer once.
        if not _agent_active:
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
            try:
                from helpers.logger import logger
                logger.log_error(str(e), context=f"{class_name}.{function_name}")
            except Exception:
                pass

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
            try:
                from helpers.logger import logger
                logger.log_error(str(e), context=f"{class_name}.{function_name}")
            except Exception:
                pass
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
