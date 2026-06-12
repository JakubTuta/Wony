import importlib
import os
import re
import sys
import threading
import typing
import urllib.request

import numpy as np

import helpers.diagnostics
from helpers.compute import _GPU_FIX_HINT
from helpers.config import Config
from helpers.decorators import is_agent_active

_tts_warned = False
_tts_lock = threading.Lock()  # Kokoro is not re-entrant; serialize calls
_tts_singleton: typing.Optional["TTS_Engine"] = None

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

_UNSUPPORTED_LANG_WARNING_SHOWN = False


def _resolve_kokoro_lang(bcp47: str) -> str:
    global _UNSUPPORTED_LANG_WARNING_SHOWN
    lang = bcp47.lower()
    if lang in _LANG_MAP:
        return _LANG_MAP[lang]
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


def _add_nvidia_dll_dirs() -> None:
    """Register nvidia pip-wheel DLL dirs so onnxruntime's CUDA loader finds them.

    Must be called before onnxruntime/kokoro_onnx are imported.
    nvidia.* are namespace packages (__file__ is None); use __path__ to locate them.
    """
    for pkg_name in ("nvidia.cudnn", "nvidia.cublas", "nvidia.cuda_runtime"):
        try:
            pkg = importlib.import_module(pkg_name)
            pkg_root = next(iter(getattr(pkg, "__path__", [])), None)
            if not pkg_root:
                continue
            dll_dir = os.path.join(pkg_root, "bin")
            if not os.path.isdir(dll_dir):
                continue
            os.add_dll_directory(dll_dir)
            if dll_dir.lower() not in os.environ.get("PATH", "").lower():
                os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        except (ImportError, StopIteration, OSError):
            pass


def _setup_onnx_provider() -> None:
    """Set ONNX_PROVIDER env var before Kokoro() construction.

    Must be called before constructing Kokoro() since the ONNX session is built inside its constructor.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return

    device = str(Config.get("voice.tts_device", "auto")).lower()
    if device != "cpu" and "CUDAExecutionProvider" in ort.get_available_providers():
        os.environ["ONNX_PROVIDER"] = "CUDAExecutionProvider"
        helpers.diagnostics.add("info", "TTS", "Using CUDAExecutionProvider (GPU).")
    else:
        os.environ.pop("ONNX_PROVIDER", None)
        if device == "cuda":
            helpers.diagnostics.add("warning", "TTS", "CUDA requested but CUDAExecutionProvider unavailable — using CPU.", hint=_GPU_FIX_HINT)


def _get_tts_singleton() -> "TTS_Engine":
    global _tts_singleton
    if _tts_singleton is None:
        _tts_singleton = TTS_Engine()
    return _tts_singleton


def _play_samples(
    samples: np.ndarray,
    sr: int,
    interrupt_event: typing.Optional[threading.Event] = None,
    out_stream=None,
) -> bool:
    """Play samples in 50ms chunks. Returns True if fully played, False if interrupted.

    If out_stream is provided, caller owns its lifecycle; on interrupt it is aborted.
    """
    import sounddevice as sd

    own_stream = out_stream is None
    if own_stream:
        out_stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
        out_stream.start()

    chunk_size = int(sr * 0.05)  # 50ms chunks for responsive interruption
    completed = True
    try:
        for i in range(0, len(samples), chunk_size):
            if interrupt_event is not None and interrupt_event.is_set():
                out_stream.abort()  # discard buffered audio immediately
                completed = False
                break
            out_stream.write(samples[i : i + chunk_size])
    except Exception:
        completed = False

    if own_stream:
        if completed:
            try:
                out_stream.stop()  # drain remaining buffered audio
            except Exception:
                pass
        out_stream.close()

    return completed


class TTS_Engine:
    def __init__(self) -> None:
        # Must register nvidia DLL dirs before kokoro_onnx/onnxruntime import.
        if sys.platform == "win32":
            _add_nvidia_dll_dirs()

        import espeakng_loader
        from kokoro_onnx import Kokoro
        from kokoro_onnx.config import EspeakConfig

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

        # Store for inference-time CPU fallback (cuDNN errors surface on first create() call,
        # not during session construction, so we need to be able to rebuild here too).
        self._onnx_path = onnx_path
        self._voices_path = voices_path
        self._espeak_cfg = espeak_cfg

        _setup_onnx_provider()
        try:
            self._kokoro = Kokoro(onnx_path, voices_path, espeak_config=espeak_cfg)
        except Exception as e:
            if os.environ.get("ONNX_PROVIDER", ""):
                helpers.diagnostics.add("warning", "TTS", f"GPU provider init failed ({e}) — retrying on CPU.", hint=_GPU_FIX_HINT)
                os.environ.pop("ONNX_PROVIDER", None)
                self._kokoro = Kokoro(onnx_path, voices_path, espeak_config=espeak_cfg)
            else:
                raise

    def _rebuild_on_cpu(self, reason: str) -> None:
        from kokoro_onnx import Kokoro

        helpers.diagnostics.add("warning", "TTS", f"CUDA inference failed ({reason}) — rebuilt on CPU.", hint=_GPU_FIX_HINT)
        os.environ.pop("ONNX_PROVIDER", None)
        self._kokoro = Kokoro(self._onnx_path, self._voices_path, espeak_config=self._espeak_cfg)

    def synthesize(self, text: str) -> typing.Tuple[np.ndarray, int]:
        try:
            samples, sr = self._kokoro.create(
                text, voice=self._voice, speed=self._speed, lang=self._lang
            )
        except Exception as e:
            # cuDNN errors surface on first inference when nvidia-cudnn-cu12 is missing.
            if os.environ.get("ONNX_PROVIDER", "") or "cuda" in str(e).lower() or "cudnn" in str(e).lower():
                self._rebuild_on_cpu(type(e).__name__)
                samples, sr = self._kokoro.create(
                    text, voice=self._voice, speed=self._speed, lang=self._lang
                )
            else:
                raise
        if self._volume != 1.0:
            samples = (samples * self._volume).astype(np.float32)
        return samples, sr

    def save_to_file(self, text: str, filename: str) -> None:
        import soundfile as sf

        samples, sr = self.synthesize(text)
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
        """Play a pre-rendered WAV clip if available, else live TTS. Run scripts/render_voice_clips.py to generate clips."""
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
    def text_to_speech(
        text: str,
        interrupt_event: typing.Optional[threading.Event] = None,
    ) -> None:
        if is_agent_active():
            return
        if not text or not str(text).strip():
            return
        # Pipelined sentence-by-sentence path: first audio after one sentence's
        # synthesis instead of the whole text's.
        stream_text_to_speech([str(text)], interrupt_event)

    @staticmethod
    def notify(text: str) -> None:
        """Speak a proactive background notification (timer, reminder, poller),
        ducking other apps' audio for the duration. No-op when audio is off."""
        from helpers.cache import Cache

        if not text or not Cache.get_audio():
            return
        try:
            from helpers.ducking import duck_others

            with duck_others():
                Audio.text_to_speech(text)
        except Exception:
            Audio.text_to_speech(text)

    @staticmethod
    def record_audio(duration: int = 3) -> np.ndarray:
        """Record a fixed-length window. Returns float32 @16kHz mono numpy array."""
        from helpers import mic

        return mic.record_16k(duration)

    @staticmethod
    def record_command(start_timeout: typing.Optional[float] = None) -> np.ndarray:
        """Record a spoken command with VAD endpointing. Returns float32 @16kHz mono."""
        from helpers import mic

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


def _split_sentences(text: str) -> typing.List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


class BargeinListener:
    """
    Lightweight VAD listener that monitors the mic during TTS playback.
    When sustained speech is detected, sets `interrupt_event` so the caller
    can stop TTS immediately.

    Respects the single-input-stream contract: the vad_frame_stream generator
    closes its stream before _listen returns, so the caller can open a fresh
    stream for STT.

    Echo guard: requires `sustain_frames` consecutive speech frames (default 5,
    ~150ms) to avoid false triggers from speaker bleed. Configurable via
    voice.barge_in.sustain_frames in config.yaml.
    """

    def __init__(self, interrupt_event: threading.Event) -> None:
        self._interrupt = interrupt_event
        self._stop = threading.Event()
        self._thread: typing.Optional[threading.Thread] = None
        self.captured: typing.Optional[str] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True, name="barge-in-vad")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _listen(self) -> None:
        try:
            from helpers import mic
        except ImportError:
            return

        cfg = Config.get("voice.barge_in", {}) or {}
        sustain_frames = int(cfg.get("sustain_frames", 15))

        speech_frames = 0
        gen = mic.vad_frame_stream(self._stop, vad_aggressiveness=2)
        try:
            for is_speech, _ in gen:
                if is_speech:
                    speech_frames += 1
                    if speech_frames >= sustain_frames:
                        self._interrupt.set()
                        break
                else:
                    speech_frames = max(0, speech_frames - 1)
        except Exception:
            pass
        finally:
            gen.close()


def _warn_tts_unavailable(e: Exception) -> None:
    """Print one actionable TTS failure message and reset a broken engine."""
    global _tts_warned, _tts_singleton
    if isinstance(e, ImportError):
        if not _tts_warned:
            print(
                "TTS unavailable: kokoro-onnx not installed. "
                "Run: pip install -r requirements/voice.txt"
            )
            _tts_warned = True
        return
    if not _tts_warned:
        print(
            f"TTS unavailable: {e} — check voice.tts_voice / voice.model_path in config.yaml."
        )
        _tts_warned = True
    # Engine may be broken; reset so the next call builds a fresh one.
    _tts_singleton = None


def stream_text_to_speech(
    text_gen: typing.Union[typing.Generator[str, None, None], typing.Iterable[str]],
    interrupt_event: typing.Optional[threading.Event] = None,
) -> typing.Tuple[str, typing.List[str]]:
    """
    Stream model text deltas to TTS sentence-by-sentence, pipelined.

    Accumulates chunks until a sentence boundary is detected, then synthesizes
    that sentence and hands it to a playback thread. Synthesis of the next
    sentence overlaps playback of the current one, so the only wait the user
    hears is the synthesis of the very first sentence. A single persistent
    OutputStream is reused across sentences — no gaps or device re-init.

    Checks interrupt_event every 50ms during playback so the assistant can be
    stopped mid-sentence, not just between sentences.

    Returns:
        (spoken_text, remaining_sentences)
        spoken_text: everything that was actually spoken aloud
        remaining_sentences: unspoken sentences buffered when interrupted
    """
    import queue

    import sounddevice as sd

    if interrupt_event is None:
        interrupt_event = threading.Event()

    spoken_parts: typing.List[str] = []
    pending_playback: typing.List[str] = []  # reached playback but interrupted
    pending_synth: typing.List[str] = []     # never reached playback
    buffer = ""

    # Bounded so synthesis stays at most a few sentences ahead of playback
    # (keeps barge-in responsive and memory flat on long answers).
    audio_q: "queue.Queue" = queue.Queue(maxsize=3)

    def _playback() -> None:
        out_stream = None
        interrupted = False
        try:
            while True:
                item = audio_q.get()
                if item is None:
                    return
                sentence, samples, sr = item
                if interrupted or interrupt_event.is_set():
                    pending_playback.append(sentence)
                    continue
                try:
                    if out_stream is None:
                        out_stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
                        out_stream.start()
                    if _play_samples(samples, sr, interrupt_event, out_stream=out_stream):
                        spoken_parts.append(sentence)
                    else:
                        interrupted = True
                        pending_playback.append(sentence)
                except Exception:
                    # Output device failure — keep draining so the producer never blocks.
                    interrupted = True
                    pending_playback.append(sentence)
        finally:
            if out_stream is not None:
                if not interrupted:
                    try:
                        out_stream.stop()  # drain remaining buffered audio before closing
                    except Exception:
                        pass
                try:
                    out_stream.close()
                except Exception:
                    pass

    player = threading.Thread(target=_playback, daemon=True, name="tts-playback")
    player.start()

    def _synth_and_queue(sentence: str) -> None:
        if interrupt_event.is_set():
            pending_synth.append(sentence)
            return
        try:
            with _tts_lock:
                engine = _get_tts_singleton()
                samples, sr = engine.synthesize(sentence)
        except Exception as e:
            _warn_tts_unavailable(e)
            return
        audio_q.put((sentence, samples, sr))

    try:
        for chunk in text_gen:
            buffer += chunk
            if interrupt_event.is_set():
                continue  # keep buffering; remainder lands in pending below

            sentences = _split_sentences(buffer)
            if len(sentences) > 1:
                buffer = sentences[-1]
                for s in sentences[:-1]:
                    _synth_and_queue(s)

        if buffer.strip():
            if interrupt_event.is_set():
                pending_synth.append(buffer.strip())
            else:
                _synth_and_queue(buffer.strip())
                buffer = ""
    finally:
        audio_q.put(None)
        player.join()

    return " ".join(spoken_parts), pending_playback + pending_synth


def preload_tts() -> None:
    """Warm the TTS engine at startup so the first response has no cold-start lag."""
    try:
        engine = _get_tts_singleton()
        engine.synthesize("warm up")  # loads ONNX session into memory, no playback needed
        print("TTS engine loaded.")
    except Exception as e:
        print(f"[TTS] Preload failed (non-fatal): {e}")


def cleanup() -> None:
    """Release TTS resources on shutdown. Safe to call multiple times."""
    global _tts_singleton
    with _tts_lock:
        _tts_singleton = None
