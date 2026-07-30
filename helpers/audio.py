import importlib
import os
import queue
import re
import sys
import threading
import time
import typing
import urllib.request

import numpy as np

import helpers.diagnostics
from helpers.compute import _GPU_FIX_HINT, select_onnx_provider
from helpers.config import Config
from helpers.decorators import is_agent_active

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs_path(path: str) -> str:
    """Resolve a config-supplied relative path against the repo root, not the process CWD."""
    return path if os.path.isabs(path) else os.path.join(_REPO_ROOT, path)

_tts_warned = False
_tts_lock = threading.Lock()  # Kokoro is not re-entrant; serialize calls
_tts_singleton: typing.Optional["TTS_Engine"] = None

# Only one speech session (streamed reply, cached clip, or notification) plays
# at a time. RLock because play_cached()'s live-TTS fallback calls
# stream_text_to_speech() on the same thread while already holding the lane.
_playback_lane = threading.RLock()

# Track the active TTS interrupt event so external callers can stop speech.
# Registration only ever happens while _playback_lane is held, so there is
# provably only one speech session — a single slot is correct.
_active_tts_interrupt: typing.Optional[threading.Event] = None
_active_tts_interrupt_lock = threading.Lock()


def interrupt_current_speech() -> None:
    """Interrupt the currently playing TTS stream, if any."""
    with _active_tts_interrupt_lock:
        ev = _active_tts_interrupt
    if ev is not None:
        ev.set()

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
    "I didn't catch that.": "voice/bot/didnt_catch.wav",
    "Sorry, I couldn't process that.": "voice/bot/couldnt_process.wav",
    "One moment.": "voice/bot/one_moment.wav",
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
        helpers.diagnostics.add(
            "warning", "TTS",
            f"Language '{bcp47}' not supported by Kokoro v1.0 — falling back to en-us.",
            hint="Set voice.tts_voice to an English voice or update assistant.language.",
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
        helpers.diagnostics.add("info", "TTS", f"Downloading {name} → {dest} …")
        tmp_dest = dest + ".part"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                with open(tmp_dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
            os.replace(tmp_dest, dest)
        except Exception:
            if os.path.exists(tmp_dest):
                os.remove(tmp_dest)
            raise
        helpers.diagnostics.add("info", "TTS", f"Downloaded {name}.")


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


def _ort_version() -> str:
    try:
        import onnxruntime as ort
        return str(ort.__version__)
    except Exception:
        return ""


def _setup_onnx_provider() -> None:
    """Set ONNX_PROVIDER env var before Kokoro() construction.

    Must be called before constructing Kokoro() since the ONNX session is built inside its constructor.
    """
    device = str(Config.get("voice.tts_device", "auto")).lower()
    provider = select_onnx_provider(device)
    if provider and device != "cuda":
        # A prior genuine CUDA failure was recorded for this onnxruntime build —
        # skip straight to CPU instead of paying the failed-attempt cost again
        # every time the engine is (re)built. An explicit voice.tts_device: cuda
        # always overrides this and tries CUDA anyway.
        from helpers.cache import Cache
        failed = Cache.get_value("tts_cuda_failed")
        if failed and failed.get("ort_version") == _ort_version():
            helpers.diagnostics.add(
                "info", "TTS",
                f"Skipping CUDA (previously failed: {failed.get('reason')}) — using CPU.",
            )
            provider = None
    if provider:
        os.environ["ONNX_PROVIDER"] = provider
        helpers.diagnostics.add("info", "TTS", f"Using {provider} (GPU).")
    else:
        os.environ.pop("ONNX_PROVIDER", None)
        if device == "cuda":
            helpers.diagnostics.add("warning", "TTS", "CUDA requested but CUDAExecutionProvider unavailable — using CPU.", hint=_GPU_FIX_HINT)


_tts_last_used: float = 0.0


def _get_tts_singleton() -> "TTS_Engine":
    global _tts_singleton, _tts_last_used
    if _tts_singleton is None:
        _tts_singleton = TTS_Engine()
        # Count load time as "used" — otherwise a freshly loaded but not-yet-
        # synthesized engine looks infinitely idle (_tts_last_used defaults to
        # 0) and the idle sweeper unloads it before it's ever used.
        _tts_last_used = time.monotonic()
    return _tts_singleton


def warm_tts_async() -> None:
    """Kick off TTS engine load on a daemon thread if not already loaded/loading.
    Used to overlap load time with the wake ack + user speaking, when
    models.preload is off. Safe to call repeatedly."""
    if _tts_singleton is not None:
        return

    def _warm() -> None:
        with _tts_lock:
            _get_tts_singleton()

    threading.Thread(target=_warm, daemon=True, name="tts-warm").start()


def unload_tts_if_idle(idle_seconds: float) -> None:
    """Free the TTS engine if unused for idle_seconds. No-op if never loaded,
    or if it's currently in use (synthesis holds _tts_lock for its duration,
    so this can never yank the engine mid-use)."""
    global _tts_singleton
    with _tts_lock:
        if _tts_singleton is None or time.monotonic() - _tts_last_used < idle_seconds:
            return
        _tts_singleton = None
    import gc
    gc.collect()
    helpers.diagnostics.add("info", "TTS", "Engine unloaded (idle).")


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

        onnx_path = _abs_path(Config.get("voice.model_path", "models/kokoro-v1.0.onnx"))
        voices_path = _abs_path(Config.get("voice.voices_path", "models/voices-v1.0.bin"))

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
                from helpers.cache import Cache
                Cache.set_value("tts_cuda_failed", {"reason": type(e).__name__, "ort_version": _ort_version()})
                os.environ.pop("ONNX_PROVIDER", None)
                self._kokoro = Kokoro(onnx_path, voices_path, espeak_config=espeak_cfg)
            else:
                raise

    def _rebuild_on_cpu(self, reason: str) -> None:
        from kokoro_onnx import Kokoro

        helpers.diagnostics.add("warning", "TTS", f"CUDA inference failed ({reason}) — rebuilt on CPU.", hint=_GPU_FIX_HINT)
        from helpers.cache import Cache
        Cache.set_value("tts_cuda_failed", {"reason": reason, "ort_version": _ort_version()})
        os.environ.pop("ONNX_PROVIDER", None)
        self._kokoro = Kokoro(self._onnx_path, self._voices_path, espeak_config=self._espeak_cfg)

    def synthesize(self, text: str) -> typing.Tuple[np.ndarray, int]:
        try:
            samples, sr = self._kokoro.create(
                text, voice=self._voice, speed=self._speed, lang=self._lang
            )
        except Exception as e:
            # Only a genuine CUDA/cuDNN/cuBLAS failure warrants a CPU rebuild —
            # any other synthesis error (e.g. an unphonemizable fragment) would
            # just fail identically again on CPU, so don't misdiagnose it as a
            # GPU problem and churn the engine.
            msg = str(e).lower()
            if os.environ.get("ONNX_PROVIDER", "") and any(tok in msg for tok in ("cuda", "cudnn", "cublas")):
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


_notify_q: "queue.Queue[str]" = queue.Queue()
_notify_dispatcher_thread: typing.Optional[threading.Thread] = None
_notify_dispatcher_lock = threading.Lock()


def _lane_busy() -> bool:
    acquired = _playback_lane.acquire(blocking=False)
    if acquired:
        _playback_lane.release()
        return False
    return True


def _ensure_notify_dispatcher() -> None:
    global _notify_dispatcher_thread
    with _notify_dispatcher_lock:
        if _notify_dispatcher_thread is not None and _notify_dispatcher_thread.is_alive():
            return
        _notify_dispatcher_thread = threading.Thread(
            target=_notify_dispatcher_loop, daemon=True, name="notify-dispatcher"
        )
        _notify_dispatcher_thread.start()


def _notify_dispatcher_loop() -> None:
    from helpers import mic

    while True:
        text = _notify_q.get()
        batch = [text]
        while True:
            try:
                batch.append(_notify_q.get_nowait())
            except queue.Empty:
                break

        # Defer until any active conversation/push-to-talk session and any
        # in-progress speech finish — talking over the user is strictly worse
        # than a short delay. No max-defer timeout: conversations self-end on
        # the follow-up silence timeout, so the wait is bounded in practice.
        while mic.voice_session.locked() or _lane_busy():
            time.sleep(0.5)

        combined = " ".join(t for t in batch if t)
        if combined:
            stream_text_to_speech([combined])


def _play_cached_wav(path: str) -> None:
    """Play a WAV file with the same interrupt-slot registration as streamed
    TTS, so tray "Stop speaking" / web `stop` can interrupt cached clips too."""
    import soundfile as sf

    from helpers import mic

    samples, sr = sf.read(path, dtype="float32", always_2d=False)

    interrupt_event = threading.Event()
    with _active_tts_interrupt_lock:
        global _active_tts_interrupt
        _active_tts_interrupt = interrupt_event
    try:
        with mic.playback_session() as out:
            out.play(samples, sr, interrupt_event)
    finally:
        with _active_tts_interrupt_lock:
            if _active_tts_interrupt is interrupt_event:
                _active_tts_interrupt = None


class Audio:
    @staticmethod
    def save_text_to_file(text: str, filename: str) -> None:
        engine = _get_tts_singleton()
        engine.save_to_file(text, filename)

    @staticmethod
    def play_cached(text: str) -> None:
        """Play a pre-rendered WAV clip if available, else live TTS. Run scripts/render_voice_clips.py to generate clips."""
        if is_agent_active():
            return
        from helpers.cache import Cache
        if not Cache.get_audio():
            return

        with _playback_lane:
            from helpers.ducking import duck_others
            with duck_others():
                wav = CACHED_CLIPS.get(text)
                wav_path = _abs_path(wav) if wav else None
                if wav_path and os.path.exists(wav_path):
                    try:
                        _play_cached_wav(wav_path)
                        return
                    except Exception as e:
                        helpers.diagnostics.add("warning", "Audio", f"Cached playback failed ({e}) — falling back to TTS")

                stream_text_to_speech([text])

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
    def notify(text: typing.Union[str, typing.List[str]]) -> None:
        """Queue a proactive background notification (timer, reminder, poller)
        to be spoken once any active conversation/speech finishes — never
        talks over the user. No-op when audio is off. Accepts a list to batch
        multiple messages under one duck."""
        from helpers.cache import Cache

        if not text or not Cache.get_audio():
            return
        combined = " ".join(t for t in text if t) if isinstance(text, list) else str(text)
        if not combined:
            return
        _ensure_notify_dispatcher()
        _notify_q.put(combined)

    @staticmethod
    def record_audio(duration: int = 3) -> np.ndarray:
        """Record a fixed-length window. Returns float32 @16kHz mono numpy array."""
        from helpers import mic

        return mic.record_16k(duration)

    @staticmethod
    def record_command(start_timeout: typing.Optional[float] = None) -> np.ndarray:
        """Record a spoken command with VAD endpointing. Returns float32 @16kHz mono."""
        from helpers import events, mic

        cfg = Config.get("voice.stt", {}) or {}
        effective_timeout = (
            start_timeout
            if start_timeout is not None
            else float(cfg.get("start_timeout", 4.0))
        )
        return mic.record_until_silence(
            max_seconds=float(cfg.get("max_seconds", 12.0)),
            start_timeout=effective_timeout,
            silence_ms=int(cfg.get("silence_ms", 700)),
            vad_aggressiveness=int(cfg.get("vad_aggressiveness", 2)),
            cancel_event=events.session_cancel,
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

    Echo guard: requires `sustain_frames` consecutive speech frames (default 15,
    ~450ms) to avoid false triggers from speaker bleed. Configurable via
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
    """Emit one actionable TTS failure diagnostic and reset a broken engine."""
    global _tts_warned, _tts_singleton
    if isinstance(e, ImportError):
        if not _tts_warned:
            helpers.diagnostics.add(
                "error", "TTS", "kokoro-onnx not installed.",
                hint="pip install -r requirements/voice.txt",
            )
            _tts_warned = True
        return
    if not _tts_warned:
        helpers.diagnostics.add(
            "error", "TTS", f"Unavailable: {e}",
            hint="Check voice.tts_voice / voice.model_path in config.yaml.",
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

    Runs inside the single playback lane — only one speech session (streamed
    reply, cached clip, or deferred notification) plays at a time.

    Returns:
        (spoken_text, remaining_sentences)
        spoken_text: everything that was actually spoken aloud
        remaining_sentences: unspoken sentences buffered when interrupted
    """
    from helpers import mic

    if interrupt_event is None:
        interrupt_event = threading.Event()

    with _playback_lane:
        # Follow the OS default output device across sessions (mirrors input's
        # runtime rediscovery). Cheap: one sub-ms COM call, done once per
        # session rather than per chunk.
        if mic.output_endpoint_stale():
            if not mic.try_reinitialize_portaudio():
                mic.request_portaudio_reinit()

        with _active_tts_interrupt_lock:
            global _active_tts_interrupt
            _active_tts_interrupt = interrupt_event

        spoken_parts: typing.List[str] = []
        pending_playback: typing.List[str] = []  # reached playback but interrupted
        pending_synth: typing.List[str] = []     # never reached playback
        buffer = ""

        # Bounded so synthesis stays at most a few sentences ahead of playback
        # (keeps barge-in responsive and memory flat on long answers).
        audio_q: "queue.Queue" = queue.Queue(maxsize=3)

        def _playback() -> None:
            interrupted = False

            # Prebuffer a short run of sentences before the first sample plays,
            # so a slow first synthesis doesn't leave the stream starved right
            # out of the gate (the audible "pause every couple words" stutter).
            # Skipped on CUDA — GPU synthesis is fast enough that buffering only
            # adds onset latency without preventing any real underrun.
            prebuffer_ms = int(Config.get("voice.tts.prebuffer_ms", 600) or 0)
            if os.environ.get("ONNX_PROVIDER", "") == "CUDAExecutionProvider":
                prebuffer_ms = 0
            prebuffering = prebuffer_ms > 0
            prebuffered: typing.List[typing.Tuple[str, np.ndarray, int]] = []
            prebuffered_ms = 0.0

            def _emit(out, item) -> None:
                nonlocal interrupted
                sentence, samples, sr = item
                if interrupted or interrupt_event.is_set():
                    pending_playback.append(sentence)
                    return
                try:
                    # The session adapts 24 kHz Kokoro output to the endpoint's
                    # native mix format and ramps the session's edges — no
                    # per-sentence stream handling here any more.
                    if out.play(samples, sr, interrupt_event):
                        spoken_parts.append(sentence)
                    else:
                        interrupted = True
                        pending_playback.append(sentence)
                except Exception as e:
                    # Output device failure — surface it, ask the wake loop to
                    # reinit PortAudio, and keep draining so the producer never blocks.
                    helpers.diagnostics.add("error", "Audio", f"Output device failed: {e}")
                    mic.request_portaudio_reinit()
                    interrupted = True
                    pending_playback.append(sentence)

            def _consume(out) -> None:
                nonlocal prebuffering, prebuffered, prebuffered_ms
                while True:
                    item = audio_q.get()

                    if item is None:
                        for pending_item in prebuffered:
                            _emit(out, pending_item)
                        prebuffered = []
                        return

                    if prebuffering:
                        prebuffered.append(item)
                        prebuffered_ms += (len(item[1]) / item[2]) * 1000.0
                        if interrupted or interrupt_event.is_set() or prebuffered_ms >= prebuffer_ms:
                            prebuffering = False
                            for pending_item in prebuffered:
                                _emit(out, pending_item)
                            prebuffered = []
                        continue

                    _emit(out, item)

            # One session for the whole reply, so sentences play back-to-back
            # with no gap and no device transition. An empty queue between
            # sentences is harmless: the hub's callback emits silence rather
            # than underrunning, which is what the old "write zeros to keep the
            # stream primed" loop existed to do by hand.
            try:
                with mic.playback_session() as out:
                    _consume(out)
            except Exception as e:
                # The producer blocks on a bounded audio_q, so this thread dying
                # quietly would deadlock the whole reply. Report, ask for a
                # PortAudio reinit, then keep draining to the end marker so the
                # text is still returned as unspoken rather than lost.
                helpers.diagnostics.add("error", "Audio", f"Playback unavailable: {e}")
                mic.request_portaudio_reinit()
                for sentence, _samples, _sr in iter(audio_q.get, None):
                    pending_playback.append(sentence)

        def _synth_and_queue(sentence: str) -> None:
            global _tts_last_used
            if interrupt_event.is_set():
                pending_synth.append(sentence)
                return
            if not any(ch.isalnum() for ch in sentence):
                return  # nothing phonemizable (e.g. a lone trailing emoji) — nothing to speak

            try:
                with _tts_lock:
                    engine = _get_tts_singleton()
            except Exception as e:
                _warn_tts_unavailable(e)  # engine itself is broken — reset for next call
                return

            try:
                with _tts_lock:
                    samples, sr = engine.synthesize(sentence)
                    _tts_last_used = time.monotonic()
            except Exception as e:
                # A single fragment failing to synthesize doesn't mean the engine
                # is broken — skip it and keep the (working) engine for the rest
                # of the reply instead of forcing a full rebuild.
                helpers.diagnostics.add("warning", "TTS", f"Skipping fragment ({e}).")
                return

            audio_q.put((sentence, samples, sr))

        from helpers.ducking import duck_others
        with duck_others():
            player = threading.Thread(target=_playback, daemon=True, name="tts-playback")
            player.start()

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

        with _active_tts_interrupt_lock:
            if _active_tts_interrupt is interrupt_event:
                _active_tts_interrupt = None

        return " ".join(spoken_parts), pending_playback + pending_synth


def play_earcon() -> None:
    """Short non-verbal acknowledgement tone (~120ms). Used when the wake word
    lands while audio is muted — confirms the assistant heard the user without
    a spoken "Yes?" that the mute toggle is meant to suppress."""
    from helpers import mic

    sr = 24000
    duration = 0.12
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    tone = (0.15 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
    fade = min(200, len(tone) // 4)  # short fade in/out to avoid a click
    if fade > 0:
        tone[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        tone[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    try:
        mic.play_array(tone, sr, blocking=True)
    except Exception:
        pass


def preload_tts() -> None:
    """Warm the TTS engine at startup so the first response has no cold-start lag."""
    try:
        engine = _get_tts_singleton()
        engine.synthesize("warm up")  # loads ONNX session into memory, no playback needed
        helpers.diagnostics.add("info", "TTS", "Engine loaded.")
    except Exception as e:
        helpers.diagnostics.add("warning", "TTS", f"Preload failed (non-fatal): {e}")


def cleanup() -> None:
    """Release TTS resources on shutdown. Safe to call multiple times."""
    global _tts_singleton
    with _tts_lock:
        _tts_singleton = None
