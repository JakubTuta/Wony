import functools
import os
import sys
import threading
import traceback
import typing

T = typing.TypeVar("T")

# Set to True by the agent loop while executing tools so capture_response
# suppresses per-tool print/TTS output. The final narrated answer is output once.
_agent_active: bool = False

# Process-wide lock: serializes agent runs so wake-word and web /api/chat
# calls don't interleave on shared Conversation state or _agent_active.
agent_lock = threading.Lock()


def set_agent_active(value: bool) -> None:
    global _agent_active
    _agent_active = value


def is_agent_active() -> bool:
    return _agent_active


# ── Per-turn tool outcome ledger ────────────────────────────────────────────
# Gates whether the agent's final narration gets spoken: if every tool call
# this turn was a quiet-on-success job (mute=True) that actually succeeded,
# the outcome is already audible/visible on its own (e.g. music started) and
# narrating it too just wastes time under a duck. Only ever touched while
# agent_lock is held (agent runs are serialized process-wide), so a plain
# module-level list is safe without its own lock.
_tool_outcomes: typing.List[typing.Tuple[str, bool, bool]] = []  # (name, quiet, ok)


def begin_tool_outcomes() -> None:
    global _tool_outcomes
    _tool_outcomes = []


def record_tool_outcome(name: str, quiet: bool, ok: bool) -> None:
    _tool_outcomes.append((name, quiet, ok))


def turn_is_quiet_success() -> bool:
    """True if at least one tool ran this turn and every one was quiet-on-
    success and actually succeeded. False (speak) for zero tool calls, any
    non-quiet job, any failure, or any untracked/unwrapped call — the gate
    must never silence a call it didn't fully account for."""
    if not _tool_outcomes:
        return False
    return all(quiet and ok for _, quiet, ok in _tool_outcomes)


def capture_response(
    func: typing.Callable[..., typing.Any] = None,
    *,
    mute: bool = False,
) -> typing.Callable[..., typing.Optional[str]]:
    """
    Decorator that captures the response, prints it to console, and handles audio output.
    Always returns a string response.

    Args:
        mute: When True, suppresses TTS on success but still vocalizes errors.
              Use for actions with immediate audible feedback (play, pause, volume).
    """

    def decorator(f: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Optional[str]]:
        @functools.wraps(f)
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

            function_name = f.__name__ if hasattr(f, "__name__") else "Unknown"
            class_name = (
                args[0].__class__.__name__
                if args and hasattr(args[0], "__class__")
                else "Unknown"
            )

            try:
                response = f(*args, **kwargs)
            except Exception as e:
                error_msg = f"Error ({class_name}.{function_name}): {e}"
                print(error_msg)

                if logger:
                    logger.log_error(traceback.format_exc(), f"{class_name}.{function_name}")

                if _agent_active:
                    record_tool_outcome(function_name, mute, False)
                # Always vocalize errors so user knows the action failed.
                elif Cache and Audio and Cache.get_audio():
                    Audio.text_to_speech(error_msg)

                return error_msg

            str_response = str(response) if response is not None else ""

            # Suppress per-tool output while the agent loop is running;
            # the agent will narrate the final answer once.
            if _agent_active:
                record_tool_outcome(function_name, mute, True)
            else:
                if not mute and Cache and Audio and Cache.get_audio():
                    Audio.text_to_speech(str_response)
                print(str_response)

            return str_response

        wrapper._quiet_success = bool(mute)
        return wrapper

    if func is not None:
        # Used as @capture_response (no parentheses)
        return decorator(func)
    # Used as @capture_response(...) (with parentheses)
    return decorator


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
