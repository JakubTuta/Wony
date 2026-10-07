import inspect
import sys
import threading
import typing

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.conversation import Conversation
from helpers.decorators import capture_response, turn_is_quiet_success, turn_wants_one_message
from helpers.events import session_cancel
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.recognizer import Recognizer
from helpers.registry import ServiceRegistry, register_job
from helpers.turn import run_turn


# Say "one moment" if no narration has started by this point, so a slow tool
# call doesn't leave the user in silence wondering if anything happened.
# 0 disables the cue.
_THINKING_CUE_SECONDS = 6.0


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
        self._last_paused_sentences: typing.List[str] = []

    @staticmethod
    def set_exit_hook(callback: typing.Callable) -> None:
        """Register a callback invoked by the exit job instead of sys.exit (tray mode)."""
        Employer._exit_hook = callback

    def speak(self) -> None:
        first_text = str(Recognizer.recognize_speech_from_mic())
        if not first_text:
            logger.log_system_event(
                "speech_recognition_failed", "No speech detected or recognized"
            )
            if not session_cancel.is_set():
                msg = "Sorry, I couldn't process that." if Recognizer.last_call_failed else "I didn't catch that."
                Audio.play_cached(msg)
            return
        self.converse(first_text=first_text)

    def handle_utterance(self, text: str) -> None:
        """Process a transcribed speech utterance (called by wake word and push-to-talk paths)."""
        if not text:
            return
        self.converse(first_text=text)

    def converse(self, first_text: typing.Optional[str] = None) -> None:
        """Run a continuous voice conversation until silence or a stop phrase.

        Each turn: log utterance → run job → speak → listen for follow-up.
        With barge-in enabled: any speech during TTS playback stops playback immediately;
        the interruption is transcribed and branched: empty/resume-phrase → resume remaining
        text; stop phrase → end; real command → process as new turn.
        """
        from helpers.cache import Cache
        from helpers.config import Config

        audio = Cache.get_audio()
        cfg = Config.get("voice.conversation", {}) or {}
        enabled = bool(cfg.get("enabled", True))

        # Non-audio or conversation disabled: single-turn behaviour
        if not audio or not enabled:
            if first_text:
                logger.log_user_input(first_text, "speech")
                self.job_on_command(first_text)
            return

        from helpers.audio import START_TIMEOUT_SECONDS

        clarify_timeout = START_TIMEOUT_SECONDS
        follow_up_timeout = float(cfg.get("follow_up_timeout", 3.0))
        stop_phrases = [
            "thanks",
            "thank you",
            "that's all",
            "thats all",
            "that's it",
            "thats it",
            "never mind",
            "nevermind",
            "stop",
            "done",
            "goodbye",
            "shut up",
        ]

        barge_in_enabled = bool(Config.get("voice.barge_in.enabled", False))
        resume_phrases = ["continue", "go on", "keep going", "go ahead"]

        text = first_text
        while text:
            if self._is_stop_phrase(text, stop_phrases):
                break

            logger.log_user_input(text, "speech")

            if barge_in_enabled:
                interrupt_event = threading.Event()
                from helpers.audio import BargeinListener
                listener = BargeinListener(interrupt_event)
                listener.start()
                try:
                    response = self.job_on_command(text, interrupt_event=interrupt_event)
                finally:
                    listener.stop()

                paused = list(self._last_paused_sentences)
                self._last_paused_sentences = []

                if interrupt_event.is_set() and paused:
                    # Transcribe what interrupted
                    interruption = str(
                        Recognizer.recognize_speech_from_mic(start_timeout=2.0)
                    ).strip()
                    norm = interruption.lower().rstrip(".,!?")

                    if not norm or norm in resume_phrases:
                        # Resume: speak the remaining sentences
                        Audio.text_to_speech(" ".join(paused))
                        # Fall through to normal follow-up listen
                    elif self._is_stop_phrase(interruption, stop_phrases):
                        break
                    else:
                        # Genuine new command — process as next turn
                        text = interruption
                        continue
            else:
                response = self.job_on_command(text)

            if session_cancel.is_set():
                break  # deliberate stop mid-turn — don't keep listening for a follow-up

            if turn_wants_one_message():
                break  # a one_message job ran (e.g. play a song) — one action, done

            # Choose next listen timeout based on whether assistant asked a question
            if self._is_question(response):
                next_timeout = clarify_timeout
            else:
                next_timeout = follow_up_timeout

            text = str(Recognizer.recognize_speech_from_mic(start_timeout=next_timeout))

    @staticmethod
    def _is_question(response: typing.Optional[str]) -> bool:
        if not response:
            return False
        return response.strip().endswith("?")

    @staticmethod
    def _is_stop_phrase(text: str, stop_phrases: typing.List[str]) -> bool:
        normalized = text.lower().strip().rstrip(".,!?")
        return normalized in stop_phrases

    def job_on_command(
        self,
        user_input: str,
        interrupt_event: typing.Optional[threading.Event] = None,
    ) -> typing.Optional[str]:
        if not user_input or not user_input.strip():
            return None
        if session_cancel.is_set():
            return None

        self._refresh_available_jobs()
        self._last_paused_sentences = []

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

        # Always stream the model's reply. Audio mode pipes deltas into the TTS
        # pipeline (speech starts on the first sentence); console mode writes
        # them to stdout as they arrive. Either way the full answer reaches the
        # user through on_text — job_on_command never re-emits it afterwards.
        audio = Cache.get_audio()

        tts_queue = None
        tts_thread = None
        tts_result: typing.Dict[str, typing.Any] = {}
        on_text = None

        if audio:
            import queue as _queue

            from helpers.audio import stream_text_to_speech

            tts_queue = _queue.Queue()

            def _tts_worker() -> None:
                def _chunks():
                    while True:
                        item = tts_queue.get()
                        if item is None:
                            return
                        yield item

                from helpers.events import emit_state
                emit_state("speaking")
                try:
                    tts_result["value"] = stream_text_to_speech(_chunks(), interrupt_event)
                finally:
                    emit_state("idle")

            tts_thread = threading.Thread(target=_tts_worker, daemon=True, name="tts-stream")
            tts_thread.start()

            first_chunk_seen = threading.Event()

            def on_text(chunk: str) -> None:
                first_chunk_seen.set()
                # Drop speech (not the narration text itself — that's still
                # recorded/returned/shown in web) once the turn is a deliberate
                # cancel or a quiet-on-success tool outcome (e.g. "pause") that
                # doesn't need a spoken confirmation on top of the audible change.
                if session_cancel.is_set() or turn_is_quiet_success():
                    return
                tts_queue.put(chunk)
        else:
            def on_text(chunk: str) -> None:
                sys.stdout.write(chunk)
                sys.stdout.flush()

        from helpers.events import emit_state
        emit_state("thinking")

        # A long tool call (web search, a slow API) can leave the user in
        # silence wondering if anything is happening — a one-shot spoken cue
        # if no narration has started by the deadline reassures them without
        # interrupting a fast reply.
        thinking_timer: typing.Optional[threading.Timer] = None
        if audio and _THINKING_CUE_SECONDS > 0:
            def _thinking_cue() -> None:
                if not first_chunk_seen.is_set() and not session_cancel.is_set():
                    Audio.play_cached("One moment.")
            thinking_timer = threading.Timer(_THINKING_CUE_SECONDS, _thinking_cue)
            thinking_timer.daemon = True
            thinking_timer.start()

        try:
            result = run_turn(user_input, on_text=on_text, think=not audio)
        finally:
            if thinking_timer is not None:
                thinking_timer.cancel()
            if tts_queue is not None:
                tts_queue.put(None)

        if tts_thread is not None:
            tts_thread.join()
            _, paused = tts_result.get("value", ("", []))
            self._last_paused_sentences = paused
        elif result.text and not (result.error or result.timed_out):
            print()  # newline after the streamed console line

        # Nothing reached on_text on these two paths, so the message still has
        # to be delivered — and the TTS lane is free again by now.
        if result.error or result.timed_out:
            if audio:
                Audio.text_to_speech(result.text)
            else:
                print(result.text)

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

    @register_job(module_name="employer")
    @capture_response
    @staticmethod
    def undo() -> str:
        """
        [SYSTEM CONTROL JOB] Takes back the last change made at the user's request in
        the past 15 minutes: a light or device switched, an item put on or taken off a
        list, a song added to or removed from a playlist, a timer set, a fact remembered.

        Returns:
            str: What was taken back, or that there is nothing to undo.
        """
        from helpers import undo

        return undo.undo()

    @register_job(module_name="employer", confirms=True)
    @staticmethod
    def exit() -> None:
        """
        [APPLICATION TERMINATION JOB] Shuts Wony down completely.

        Returns:
            None
        """
        audio = Cache.get_audio()
        if audio:
            Audio.play_cached("Exiting program. o7")
        else:
            # SystemExit below bypasses capture_response's normal print path —
            # without this, a text-mode "exit" closes with zero visible feedback.
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
        would skip the gate. Typed "exit" is the one exception — someone at the
        console typing it is the confirmation.
        """
        from helpers import confirm

        normalized_input = user_input.lower().strip()
        confirms = ServiceRegistry.get_job_confirms()
        for func in self.available_functions:
            func_name = func.__name__.replace("_", " ").lower()
            if normalized_input != func_name:
                continue
            if func.__name__ == "exit" and not Cache.get_audio():
                return func
            # Called bare, a job runs with its defaults: a job whose default
            # action is one that confirms must not slip through with no action.
            if confirm._applies(confirms.get(func.__name__), _default_args(func)):
                return None
            return func
        return None
