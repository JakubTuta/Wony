import os
import threading
import typing

import numpy as np

_tts_warned = False
_tts_lock = threading.Lock()  # pyttsx3/SAPI5 is not re-entrant; serialize calls


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
    def text_to_speech(text: str) -> None:
        from helpers.decorators import is_agent_active
        if is_agent_active():
            return
        global _tts_warned
        with _tts_lock:
            try:
                tts_engine = TTS_Engine()
                tts_engine.text_to_speech(text)
                del tts_engine
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

    @staticmethod
    def record_audio(duration: int = 3) -> np.ndarray:
        """Record from the default mic and return float32 @16kHz mono numpy array."""
        Audio.play_audio_from_file("voice/bot/listening.wav")
        from helpers import mic
        return mic.record_16k(duration)
