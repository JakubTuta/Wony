import os
import threading
import typing

import numpy as np

_tts_warned = False
_tts_lock = threading.Lock()  # pyttsx3/SAPI5 is not re-entrant; serialize calls
_tts_singleton: typing.Optional["TTS_Engine"] = None

# Fixed-text clips rendered to WAV by scripts/render_voice_clips.py.
# Keys = exact text passed to play_cached(); values = WAV file paths.
CACHED_CLIPS: dict[str, str] = {
    "Yes?": "voice/bot/yes.wav",
    "I'm ready!": "voice/bot/ready.wav",
    "Getting all commands...": "voice/bot/getting_commands.wav",
    "Stopping all active jobs...": "voice/bot/stopping_jobs.wav",
    "Exiting program. o7": "voice/bot/exiting.wav",
    "Closing computer. o7": "voice/bot/closing_computer.wav",
    "Getting weather...": "voice/bot/getting_weather.wav",
    "Saving a screenshot...": "voice/bot/saving_screenshot.wav",
    "Taking a screenshot and explaining it...": "voice/bot/screenshot_explain.wav",
    "Turning light on...": "voice/bot/light_on.wav",
    "Turning light off...": "voice/bot/light_off.wav",
    "Toggling light...": "voice/bot/toggle_light.wav",
    "Launching League of Legends...": "voice/bot/launch_league.wav",
    "Closing League of Legends...": "voice/bot/close_league.wav",
}


def _get_tts_singleton() -> "TTS_Engine":
    global _tts_singleton
    if _tts_singleton is None:
        _tts_singleton = TTS_Engine()
    return _tts_singleton


class TTS_Engine:
    def __init__(self) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()

        from helpers.config import Config

        rate = Config.get("voice.rate", 150)
        volume = Config.get("voice.volume", 0.6)
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)

        voices = self._engine.getProperty("voices")
        voice_index = Config.get("voice.tts_voice_index", 1)
        if voices:
            if voice_index >= len(voices):
                print(
                    f"Warning: voice.tts_voice_index={voice_index} is out of range "
                    f"(only {len(voices)} voice(s) available). Using index 0. "
                    f"Run `python -c \"import pyttsx3; e=pyttsx3.init(); [print(i, v.name) for i, v in enumerate(e.getProperty('voices'))]\"` to list voices."
                )
                voice_index = 0
            self._engine.setProperty("voice", voices[voice_index].id)

    def text_to_speech(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()

    def save_text_to_file(self, text: str, filename: str) -> None:
        self._engine.save_to_file(text, filename)
        self._engine.runAndWait()


class Audio:
    @staticmethod
    def play_audio_from_file(filename: str) -> None:
        if not os.path.exists(filename):
            print(f"Audio file {filename} does not exist.")
            return
        try:
            from helpers import mic

            mic.play_wav(filename, blocking=False)
        except Exception as e:
            print(f"[audio] playback failed for {filename}: {e}")

    @staticmethod
    def save_text_to_file(text: str, filename: str) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        tts_engine = TTS_Engine()
        tts_engine.save_text_to_file(text, filename)
        del tts_engine

    @staticmethod
    def play_cached(text: str, blocking: bool = False) -> None:
        """Play a pre-rendered WAV clip for text if available, else live TTS.

        Non-blocking by default — returns immediately after starting playback.
        Run scripts/render_voice_clips.py to generate the WAV files.
        Falls back to live TTS (blocking) if the clip is missing.
        """
        from helpers.decorators import is_agent_active

        if is_agent_active():
            return

        wav = CACHED_CLIPS.get(text)
        if wav and os.path.exists(wav):
            try:
                from helpers import mic

                mic.play_wav(wav, blocking=blocking)
                return
            except Exception as e:
                print(f"[audio] cached playback failed ({e}) — falling back to TTS")

        Audio.text_to_speech(text)

    @staticmethod
    def text_to_speech(text: str) -> None:
        from helpers.decorators import is_agent_active

        if is_agent_active():
            return
        global _tts_warned
        with _tts_lock:
            try:
                engine = _get_tts_singleton()
                engine.text_to_speech(text)
            except ImportError:
                if not _tts_warned:
                    print(
                        "TTS unavailable: pyttsx3 not installed. "
                        "Run: pip install -r requirements/voice.txt"
                    )
                    _tts_warned = True
            except Exception as e:
                if not _tts_warned:
                    print(
                        f"TTS unavailable: {e} — check your audio device or voice.tts_voice_index in config.yaml."
                    )
                    _tts_warned = True
                # Engine may be broken; reset so next call tries a fresh one.
                global _tts_singleton
                _tts_singleton = None

    @staticmethod
    def record_audio(duration: int = 3) -> np.ndarray:
        """Record a fixed-length window. Returns float32 @16kHz mono numpy array."""
        from helpers import mic

        return mic.record_16k(duration)

    @staticmethod
    def record_command(start_timeout: typing.Optional[float] = None) -> np.ndarray:
        """Record a spoken command with VAD endpointing (stops on silence).

        Returns float32 @16kHz mono. Empty array if no speech was detected.
        Tunable via voice.stt.* in config.yaml.

        Args:
            start_timeout: override the config start_timeout (seconds to wait
                for speech before giving up). Useful for shorter follow-up windows.
        """
        from helpers import mic
        from helpers.config import Config

        cfg = Config.get("voice.stt", {}) or {}
        effective_timeout = start_timeout if start_timeout is not None else float(cfg.get("start_timeout", 4.0))
        return mic.record_until_silence(
            max_seconds=float(cfg.get("max_seconds", 12.0)),
            start_timeout=effective_timeout,
            silence_ms=int(cfg.get("silence_ms", 700)),
            vad_aggressiveness=int(cfg.get("vad_aggressiveness", 2)),
        )
