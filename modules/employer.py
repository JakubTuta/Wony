import inspect
import sys
import typing

from helpers.conversation import Conversation
from helpers.decorators import capture_response
from helpers.events import session_cancel
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.registry import ServiceRegistry, register_job
from helpers.turn import run_turn


def _default_args(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    """The arguments a job runs with when it is called with none."""
    return {
        name: param.default
        for name, param in inspect.signature(func).parameters.items()
        if param.default is not inspect.Parameter.empty
    }


class Employer:
    available_jobs: typing.Dict[str, typing.Callable] = {}
    _services = {}
    _exit_hook: typing.Optional[typing.Callable] = None

    def __init__(self) -> None:
        self.service_instances = {}

    @staticmethod
    def set_exit_hook(callback: typing.Callable) -> None:
        """Register a callback invoked by the exit job instead of sys.exit."""
        Employer._exit_hook = callback

    def job_on_command(
        self,
        user_input: str,
        on_text: typing.Optional[typing.Callable[[str], None]] = None,
    ) -> typing.Optional[str]:
        """Run one command and return the answer.

        on_text receives the reply in streamed chunks; the default writes them
        to stdout for the console REPL. The answer reaches the caller through
        on_text as it arrives, so this never re-prints it afterwards.
        """
        if not user_input or not user_input.strip():
            return None
        if session_cancel.is_set():
            return None

        self._refresh_available_jobs()

        # Fast path: exact command match (e.g. "help", "exit")
        if (function := self._check_if_user_input_is_command(user_input)) is not None:
            function_name = (
                function.__name__
                if hasattr(function, "__name__")
                else "unknown_command"
            )
            logger.log_function_call(function_name, user_input)
            from helpers.turn_context import user_request

            with user_request(user_input):
                result = function()
            logger.log_function_response(
                function_name, str(result) if result else "No response", user_input
            )
            result_str = str(result) if result else ""
            Conversation.record_turn(user_input, result_str)
            return result_str

        streaming_to_console = on_text is None
        if streaming_to_console:
            def on_text(chunk: str) -> None:
                sys.stdout.write(chunk)
                sys.stdout.flush()

        result = run_turn(user_input, on_text=on_text)

        if result.error is not None:
            if streaming_to_console:
                print(result.error)
            return result.error

        if streaming_to_console:
            if result.timed_out:
                # Nothing was streamed — the model never produced an answer.
                print(result.text)
            elif result.text:
                print()  # newline after the streamed console line

        Conversation.record_turn(user_input, result.text, calls=result.calls)
        return result.text

        # A failed turn is not part of the conversation; a timed-out one is,
        # because a tool did run and its result is what we just said.
        if result.error:
            return result.text

        Conversation.record_turn(user_input, result.text, calls=result.calls)
        return result.text

    @register_job(module_name="employer", confirms={"stop"})
    @capture_response
    @staticmethod
    def background_jobs(action: typing.Literal["list", "stop"] = "list") -> str:
        """
        [SYSTEM CONTROL JOB] Lists what is running in the background or stops all of
        it. Not timers and reminders (manage_reminders), and not what Wony watches for
        (manage_triggers).

        Args:
            action (str): "list" (the default) or "stop".

        Returns:
            str: The running jobs, or confirmation that they were stopped.
        """
        wanted = (action or "list").strip().lower()

        if wanted in ("stop", "cancel", "stop all"):
            stopped = BackgroundJobs.stop_all()
            if stopped:
                return f"Stopped {len(stopped)} background job(s): {', '.join(stopped)}."
            return "No background jobs were running."

        if wanted not in ("list", "show"):
            return f"Unknown action '{action}'. Use list or stop."

        running = BackgroundJobs.list_jobs()
        if running:
            return f"Active background jobs: {', '.join(running)}."
        return "No background jobs are currently running."

    @register_job(module_name="employer", confirms=True)
    @staticmethod
    def exit() -> None:
        """
        [APPLICATION TERMINATION JOB] Shuts Wony down completely.

        Returns:
            None
        """
        # SystemExit below bypasses capture_response's normal print path —
        # without this, "exit" closes with zero visible feedback.
        print("Exiting program. o7")
        logger.log_system_event("exit", "Exiting program.")

        if Employer._exit_hook is not None:
            Employer._exit_hook()
        else:
            sys.exit(0)

    def _refresh_available_jobs(self):
        """Refresh available jobs from registry"""
        all_jobs = ServiceRegistry.get_all_jobs()

        for job_name, job in all_jobs.items():
            if job_name not in self.available_jobs:
                self.available_jobs[job_name] = job

        for service_name, service_class in ServiceRegistry._services.items():
            if service_name not in self.service_instances:
                instance = ServiceRegistry.get_service_instance(service_name)
                if instance:
                    self.service_instances[service_name] = instance

        self.available_functions = list(self.available_jobs.values())

    def _check_if_user_input_is_command(
        self, user_input: str
    ) -> typing.Optional[typing.Callable]:
        """A job whose exact name was said or typed, to run without the model.

        Never one that confirms: this path has no second turn to ask in, so it
        would skip the gate.
        """
        from helpers import confirm

        normalized_input = user_input.lower().strip()
        confirms = ServiceRegistry.get_job_confirms()
        for func in self.available_functions:
            func_name = func.__name__.replace("_", " ").lower()
            if normalized_input != func_name:
                continue
            # Called bare, a job runs with its defaults: a job whose default
            # action is one that confirms must not slip through with no action.
            if confirm._applies(confirms.get(func.__name__), _default_args(func)):
                return None
            return func
        return None
