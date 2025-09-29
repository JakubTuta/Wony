import os
import threading
import typing

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.commands import Commands
from helpers.decorators import capture_response, exit_on_exception
from helpers.logger import logger

# from helpers.recognizer import Recognizer
from helpers.registry import ServiceRegistry, register_job
from modules.ai import AI


class Employer:
    available_jobs: typing.Dict[str, typing.Callable] = {}
    _active_jobs: typing.Dict[str, threading.Thread] = {}
    _services = {}

    def __init__(self) -> None:
        self.service_instances = {}
        self.ai_model = AI()

    @exit_on_exception
    def speak(self) -> None:
        pass
        # user_input = str(Recognizer.recognize_speech_from_mic())

        # if not user_input:
        #     print("I didn't hear anything.")
        #     logger.log_system_event(
        #         "speech_recognition_failed", "No speech detected or recognized"
        #     )
        #     return

        # print(f"\nTranscribed text: {user_input}")
        # logger.log_user_input(user_input, "speech")

        # self.job_on_command(user_input)

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

    @capture_response
    @register_job
    @staticmethod
    def help() -> str:
        """
        [SYSTEM INFORMATION JOB] Provides comprehensive list of all available commands and capabilities.
        This informational task retrieves and displays all registered commands in the system,
        helping users understand what functionality is available to them.

        Use this job when the user wants to:
        - See all available commands
        - Learn about system capabilities
        - Get help with available functionality
        - Discover what the assistant can do

        Keywords: help, commands, list commands, show commands, available commands, what can you do, options, functionality, capabilities,
                 show help, list functions, available features, what commands, help menu

        Args:
            None

        Returns:
            str: Numbered list of all available commands and their descriptions.
        """

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Getting all commands...")
        print("Getting all commands...")

        commands = Commands.get_all_commands()

        list_commands = ""
        for indes, command in enumerate(commands):
            list_commands += f"{indes + 1}. {command}\n"

        return f"Available commands are: {list_commands}."

    @capture_response
    @register_job
    @staticmethod
    def stop_active_jobs() -> str:
        """
        [SYSTEM CONTROL JOB] Terminates all currently running background jobs and processes.
        This management task stops all active background threads including monitoring tasks,
        automation jobs, and continuous processes running in the system.

        Use this job when the user wants to:
        - Stop all background activities
        - End all running automated tasks
        - Cancel continuous monitoring processes
        - Clean up system resources by stopping threads

        Keywords: stop jobs, cancel tasks, terminate processes, end running jobs, abort, halt, kill processes, stop threads,
                 stop all, cancel everything, end tasks, stop background, terminate all

        Args:
            None

        Returns:
            str: Confirmation message that all active jobs have been stopped.
        """

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Stopping all active jobs...")
        print("Stopping all active jobs...")

        for job_name, job_thread in Employer._active_jobs.items():
            job_thread.join()

            del Employer._active_jobs[job_name]

        return "All active jobs have been stopped."

    @register_job
    @staticmethod
    def exit() -> None:
        """
        [APPLICATION TERMINATION JOB] Immediately terminates the entire AI assistant application.
        This emergency shutdown task forcefully exits the program without cleanup,
        ending all processes and closing the application completely.

        Use this job when the user wants to:
        - Exit the AI assistant completely
        - End the application session
        - Perform emergency shutdown
        - Quit the program entirely

        Keywords: exit, quit, close app, shutdown, terminate program, end application, goodbye, bye, shut down,
                 close assistant, end program, terminate app, stop everything

        Args:
            None

        Returns:
            None: Application will terminate immediately.
        """

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Exiting program. o7")
        print("Exiting program. o7")

        os._exit(0)

    def _refresh_available_jobs(self):
        """Refresh available jobs from registry"""
        # Get all jobs from ServiceRegistry
        all_jobs = ServiceRegistry.get_all_jobs()

        # Add new jobs to available_jobs
        for job_name, job in all_jobs.items():
            if job_name not in self.available_jobs:
                self.available_jobs[job_name] = job

        # Create service instances for service-based jobs
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
                return func()
                return func()
