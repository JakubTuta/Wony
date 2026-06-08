import asyncio
import os
import threading
import typing

import numpy as np

_tts_warned = False
_tts_lock = threading.Lock()  # Kokoro is not re-entrant; serialize calls
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

# Map BCP-47 language codes to Kokoro lang codes.
_LANG_MAP: dict[str, str] = {
    "en": "en-us",
    "en-us": "en-us",
    "en-gb": "en-gb",
    "fr": "fr-fr",
    "fr-fr": "fr-fr",
    "ja": "ja",
    "ko": "ko",
    "zh": "zh",
    "pt": "pt-br",
    "pt-br": "pt-br",
    "es": "es",
    "it": "it",
    "de": "de",
    "hi": "hi",
}

# Languages not supported by Kokoro v1.0 — fall back to en-us with a warning.
_UNSUPPORTED_LANG_WARNING_SHOWN = False


def _resolve_kokoro_lang(bcp47: str) -> str:
    global _UNSUPPORTED_LANG_WARNING_SHOWN
    lang = bcp47.lower()
    if lang in _LANG_MAP:
        return _LANG_MAP[lang]
    # Try prefix match (e.g. "pl" → no match → fallback)
    prefix = lang.split("-")[0]
    if prefix in _LANG_MAP:
        return _LANG_MAP[prefix]
    if not _UNSUPPORTED_LANG_WARNING_SHOWN:
        print(
            f"[TTS] Language '{bcp47}' not supported by Kokoro v1.0 — falling back to en-us. "
            "Set voice.tts_voice to an English voice or update assistant.language."
        )
        _UNSUPPORTED_LANG_WARNING_SHOWN = True
    return "en-us"


def _download_model_files(onnx_path: str, voices_path: str) -> None:
    """Download Kokoro model files if absent."""
    import urllib.request

    base_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
    files = {
        onnx_path: "kokoro-v1.0.onnx",
        voices_path: "voices-v1.0.bin",
    }
    os.makedirs(os.path.dirname(onnx_path) or ".", exist_ok=True)
    for dest, name in files.items():
        if os.path.exists(dest):
            continue
        url = base_url + name
        print(f"[TTS] Downloading {name} → {dest} …")
        urllib.request.urlretrieve(url, dest)
        print(f"[TTS] Downloaded {name}.")


def _get_tts_singleton() -> "TTS_Engine":
    global _tts_singleton
    if _tts_singleton is None:
        _tts_singleton = TTS_Engine()
    return _tts_singleton


class TTS_Engine:
    def __init__(self) -> None:
        import espeakng_loader
        from kokoro_onnx import Kokoro
        from kokoro_onnx.config import EspeakConfig

        from helpers.config import Config

        self._voice = Config.get("voice.tts_voice", "af_heart")
        self._speed = float(Config.get("voice.speed", 1.0))
        self._volume = float(Config.get("voice.volume", 0.6))
        language = str(Config.get("assistant.language", "en"))
        self._lang = _resolve_kokoro_lang(language)

        onnx_path = Config.get("voice.model_path", "models/kokoro-v1.0.onnx")
        voices_path = Config.get("voice.voices_path", "models/voices-v1.0.bin")

        _download_model_files(onnx_path, voices_path)

        espeak_cfg = EspeakConfig(
            lib_path=espeakng_loader.get_library_path(),
            data_path=espeakng_loader.get_data_path(),
        )
        self._kokoro = Kokoro(onnx_path, voices_path, espeak_config=espeak_cfg)

    async def _stream_async(self, text: str) -> None:
        import sounddevice as sd

        out_stream: typing.Optional[sd.OutputStream] = None
        try:
            async for samples, sr in self._kokoro.create_stream(
                text,
                voice=self._voice,
                speed=self._speed,
                lang=self._lang,
            ):
                if self._volume != 1.0:
                    samples = (samples * self._volume).astype(np.float32)
                if out_stream is None:
                    out_stream = sd.OutputStream(
                        samplerate=sr, channels=1, dtype="float32"
                    )
                    out_stream.start()
                out_stream.write(samples)
        finally:
            if out_stream is not None:
                out_stream.stop()
                out_stream.close()

    def text_to_speech(self, text: str) -> None:
        from helpers import mic

        try:
            asyncio.get_running_loop()
            # Already in an event loop — sync fallback
            samples, sr = self._kokoro.create(
                text, voice=self._voice, speed=self._speed, lang=self._lang
            )
            if self._volume != 1.0:
                samples = (samples * self._volume).astype(np.float32)
            mic.play_array(samples, sr, blocking=True)
        except RuntimeError:
            asyncio.run(self._stream_async(text))

    def save_to_file(self, text: str, filename: str) -> None:
        import soundfile as sf

        samples, sr = self._kokoro.create(
            text,
            voice=self._voice,
            speed=self._speed,
            lang=self._lang,
        )
        if self._volume != 1.0:
            samples = (samples * self._volume).astype(np.float32)
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        sf.write(filename, samples, sr)


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
        engine = _get_tts_singleton()
        engine.save_to_file(text, filename)

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
                        "TTS unavailable: kokoro-onnx not installed. "
                        "Run: pip install -r requirements/voice.txt"
                    )
                    _tts_warned = True
            except Exception as e:
                if not _tts_warned:
                    print(
                        f"TTS unavailable: {e} — check voice.tts_voice / voice.model_path in config.yaml."
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
        effective_timeout = (
            start_timeout
            if start_timeout is not None
            else float(cfg.get("start_timeout", 4.0))
        )
        return mic.record_until_silence(
            max_seconds=float(cfg.get("max_seconds", 12.0)),
            start_timeout=effective_timeout,
            silence_ms=int(cfg.get("silence_ms", 500)),
            vad_aggressiveness=int(cfg.get("vad_aggressiveness", 2)),
        )


def preload_tts() -> None:
    """Warm the TTS engine at startup so the first response has no cold-start lag."""
    try:
        engine = _get_tts_singleton()

        async def _warm_stream() -> None:
            async for _samples, _sr in engine._kokoro.create_stream(
                "warm up",
                voice=engine._voice,
                speed=engine._speed,
                lang=engine._lang,
            ):
                break

        try:
            asyncio.run(_warm_stream())
        except RuntimeError:
            engine._kokoro.create(
                "warm up",
                voice=engine._voice,
                speed=engine._speed,
                lang=engine._lang,
            )
        print("TTS engine loaded.")
    except Exception as e:
        print(f"[TTS] Preload failed (non-fatal): {e}")
