import os
import typing

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.recognizer import Recognizer
from helpers.registry import ServiceRegistry, register_job
from modules.ai import AI


class Employer:
    available_jobs: typing.Dict[str, typing.Callable] = {}
    _services = {}

    def __init__(self) -> None:
        self.service_instances = {}
        self.ai_model = AI()

    def speak(self) -> None:
        user_input = str(Recognizer.recognize_speech_from_mic())

        if not user_input:
            print("I didn't hear anything.")
            logger.log_system_event(
                "speech_recognition_failed", "No speech detected or recognized"
            )
            return

        print(f"\nTranscribed text: {user_input}")
        logger.log_user_input(user_input, "speech")

        self.job_on_command(user_input)

    def job_on_command(self, user_input: str) -> None:
        self._refresh_available_jobs()

        if (function := self._check_if_user_input_is_command(user_input)) is not None:
            function_name = (
                function.__name__
                if hasattr(function, "__name__")
                else "unknown_command"
            )
            logger.log_function_call(function_name, user_input)
            result = function()
            logger.log_function_response(
                function_name, str(result) if result else "No response", user_input
            )
            return

        if (
            bot_response := self.ai_model.get_function_to_call(
                user_input, self.available_functions
            )
        ) is None:
            error_msg = "Error: Could not determine function to call."
            print(error_msg)
            logger.log_error(error_msg, "job_on_command")
            return

        function_name = bot_response["name"]
        function_args = bot_response["args"]

        if function_name in self.available_jobs:
            logger.log_function_call(function_name, user_input, function_args)
            try:
                result = self.available_jobs[function_name](**function_args)
                logger.log_function_response(
                    function_name, str(result) if result else "No response", user_input
                )
            except Exception as e:
                logger.log_error(
                    f"Function {function_name} failed: {str(e)}", "job_on_command"
                )
        else:
            logger.log_error(
                f"Function {function_name} not found in available jobs",
                "job_on_command",
            )

    @register_job
    @capture_response
    @staticmethod
    def help() -> str:
        """
        [SYSTEM INFORMATION JOB] Lists all currently available commands grouped by module.
        Shows only commands that are actually registered and working right now.

        Use this job when the user wants to:
        - See all available commands
        - Learn about system capabilities
        - Discover what the assistant can do

        Keywords: help, commands, list commands, show commands, available commands, what can you do,
                 options, functionality, capabilities, show help, list functions, available features

        Args:
            None

        Returns:
            str: Commands grouped by module with descriptions.
        """
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Getting all commands...")

        job_modules = ServiceRegistry.get_job_modules()
        job_summaries = ServiceRegistry.get_job_summaries()
        all_jobs = ServiceRegistry.get_all_jobs()

        # Group by module
        grouped: typing.Dict[str, typing.List[typing.Tuple[str, str]]] = {}
        for job_name in all_jobs:
            module = job_modules.get(job_name, "general")
            summary = job_summaries.get(job_name, "")
            grouped.setdefault(module, []).append((job_name, summary))

        lines = ["Available commands:"]
        for module in sorted(grouped.keys()):
            lines.append(f"\n  [{module or 'general'}]")
            for name, summary in sorted(grouped[module]):
                display = name.replace("_", " ")
                if summary:
                    lines.append(f"    {display} — {summary}")
                else:
                    lines.append(f"    {display}")

        return "\n".join(lines)

    @register_job
    @capture_response
    @staticmethod
    def stop_active_jobs() -> str:
        """
        [SYSTEM CONTROL JOB] Terminates all currently running background jobs.

        Use this job when the user wants to:
        - Stop all background activities
        - End all running automated tasks
        - Cancel continuous monitoring processes

        Keywords: stop jobs, cancel tasks, terminate processes, end running jobs, abort, halt,
                 stop all, cancel everything, stop background, terminate all

        Args:
            None

        Returns:
            str: Confirmation message.
        """
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Stopping all active jobs...")

        stopped = BackgroundJobs.stop_all()
        if stopped:
            return f"Stopped {len(stopped)} background job(s): {', '.join(stopped)}."
        return "No background jobs were running."

    @register_job
    @capture_response
    @staticmethod
    def list_active_jobs() -> str:
        """
        [SYSTEM INFORMATION JOB] Lists all currently running background jobs.

        Use this job when the user wants to:
        - See what's running in the background
        - Check active background tasks
        - Monitor running processes

        Keywords: list jobs, active jobs, running jobs, background tasks, what's running,
                 show jobs, current tasks, running tasks

        Args:
            None

        Returns:
            str: Names of active background jobs.
        """
        running = BackgroundJobs.list_jobs()
        if running:
            return f"Active background jobs: {', '.join(running)}."
        return "No background jobs are currently running."

    @register_job
    @staticmethod
    def exit() -> None:
        """
        [APPLICATION TERMINATION JOB] Exits the AI assistant application.

        Use this job when the user wants to:
        - Exit the AI assistant completely
        - End the application session
        - Quit the program

        Keywords: exit, quit, close app, shutdown, terminate program, end application, goodbye, bye,
                 close assistant, end program, terminate app, stop everything

        Args:
            None

        Returns:
            None
        """
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Exiting program. o7")
        print("Exiting program. o7")

        os._exit(0)

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
        normalized_input = user_input.lower().strip()
        for func in self.available_functions:
            func_name = func.__name__.replace("_", " ").lower()

            if normalized_input == func_name:
                return func
