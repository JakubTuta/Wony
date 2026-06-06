import os
import sys
import typing

from helpers.agent import run_agent
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.conversation import Conversation
from helpers.decorators import capture_response, set_agent_active
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.recognizer import Recognizer
from helpers.registry import ServiceRegistry, register_job
from modules.ai import AI, build_agent_system_prompt


class Employer:
    available_jobs: typing.Dict[str, typing.Callable] = {}
    _services = {}
    _exit_hook: typing.Optional[typing.Callable] = None

    def __init__(self) -> None:
        self.service_instances = {}
        self.ai_model = AI()

    @staticmethod
    def set_exit_hook(callback: typing.Callable) -> None:
        """Register a callback invoked by the exit job instead of sys.exit (tray mode)."""
        Employer._exit_hook = callback

    def speak(self) -> None:
        user_input = str(Recognizer.recognize_speech_from_mic())

        if not user_input:
            print("I didn't hear anything.")
            logger.log_system_event(
                "speech_recognition_failed", "No speech detected or recognized"
            )
            return

        self.handle_utterance(user_input)

    def handle_utterance(self, text: str) -> None:
        """Process a transcribed speech utterance (called by wake word and ctrl+l paths)."""
        if not text:
            return
        print(f"\nTranscribed text: {text}")
        logger.log_user_input(text, "speech")
        self.job_on_command(text)

    def job_on_command(self, user_input: str) -> None:
        self._refresh_available_jobs()

        # Fast path: exact command match (e.g. "help", "exit")
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
            Conversation.record_turn(user_input, str(result) if result else "")
            return

        from helpers.config import Config
        from helpers.decorators import agent_lock
        max_steps = int(Config.get("ai.agent.max_steps", 5))
        system_prompt = build_agent_system_prompt()

        # agent_lock serializes concurrent agent runs (wake word + web /api/chat)
        with agent_lock:
            set_agent_active(True)
            try:
                agent_result = run_agent(
                    client=self.ai_model.client,
                    user_input=user_input,
                    available_jobs=self.available_jobs,
                    system_instructions=system_prompt,
                    history=Conversation.get_messages(),
                    max_steps=max_steps,
                )
            finally:
                set_agent_active(False)

        text = agent_result.text
        if text:
            audio = Cache.get_audio()
            if audio:
                Audio.text_to_speech(text)
            else:
                print(text)

        Conversation.record_turn(user_input, text)

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
        normalized_input = user_input.lower().strip()
        for func in self.available_functions:
            func_name = func.__name__.replace("_", " ").lower()

            if normalized_input == func_name:
                return func
