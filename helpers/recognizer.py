import threading
import time
import typing

import helpers.diagnostics
from helpers.audio import Audio
from helpers.compute import _GPU_FIX_HINT, stt_device
from helpers.config import Config

_model: typing.Any = None
_model_lock = threading.RLock()
_last_used: float = 0.0


def _load_whisper(model_size: str, device: str, compute_type: str) -> typing.Any:
    """Load a faster-whisper model, fully offline if already cached (see
    scripts/download_whisper.py — setup.py runs it for the Voice I/O feature).
    Falls back to a normal (network-capable) load only when the model isn't
    cached yet, so upgrading from an older setup doesn't break — it just
    downloads once here instead of failing."""
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(model_size, device=device, compute_type=compute_type, local_files_only=True)
    except Exception:
        helpers.diagnostics.add(
            "info", "STT",
            f"'{model_size}' not cached — downloading now (first run only, can take a few minutes)...",
        )
        return WhisperModel(model_size, device=device, compute_type=compute_type)


def _build_model() -> typing.Any:
    language = str(Config.get("assistant.language", "en")).lower()

    device, compute_type = stt_device()
    if device == "cuda":
        # distil-large-v3 is ~6x faster to load and run than large-v3 with
        # near-identical English accuracy, but it's an English-only
        # distillation — non-English languages need full multilingual large-v3.
        gpu_model = "distil-large-v3" if language.startswith("en") else "large-v3"
        try:
            return _load_whisper(gpu_model, device, compute_type)
        except Exception as e:
            helpers.diagnostics.add("warning", "STT", f"CUDA detected but model load failed ({e}) — falling back to CPU", hint=_GPU_FIX_HINT)

    helpers.diagnostics.add("warning", "STT", "No CUDA GPU — using CPU speech model (slower).", hint=_GPU_FIX_HINT)

    # distil-small.en is faster and more accurate than small but English-only.
    if language.startswith("en"):
        try:
            return _load_whisper("distil-small.en", "cpu", "int8")
        except Exception:
            pass
    return _load_whisper("small", "cpu", "int8")


def _get_model() -> typing.Any:
    global _model, _last_used
    with _model_lock:
        if _model is None:
            _model = _build_model()
            # Count load time as "used" — otherwise a freshly loaded but not-yet-
            # transcribed model looks infinitely idle (_last_used defaults to 0)
            # and the idle sweeper unloads it before it's ever used.
            _last_used = time.monotonic()
        return _model


def preload_model() -> None:
    _get_model()


def warm_async() -> None:
    """Kick off model load on a daemon thread if not already loaded/loading.
    Used to overlap load time with the wake ack + user speaking, when
    models.preload is off. Safe to call repeatedly."""
    if _model is not None:
        return
    threading.Thread(target=_get_model, daemon=True, name="stt-warm").start()


def unload_if_idle(idle_seconds: float) -> None:
    """Free the STT model if unused for idle_seconds. No-op if never loaded,
    or if it's currently in use (recognize_speech_from_mic holds _model_lock
    for the whole transcription, so this can never yank the model mid-use)."""
    global _model
    with _model_lock:
        if _model is None or time.monotonic() - _last_used < idle_seconds:
            return
        _model = None
    import gc
    gc.collect()
    helpers.diagnostics.add("info", "STT", "Speech model unloaded (idle).")


# Segments below this mean average token log-probability are the model guessing.
# Matches faster-whisper's own `log_prob_threshold` default.
_MIN_AVG_LOGPROB = -1.0
# Segments above this no_speech_prob are rejected even if the words themselves
# looked confident (see _drop_hallucinations). Developer knob, not user config —
# nobody should have to know what a no_speech_prob is to get a working assistant.
_MAX_NO_SPEECH_PROB = 0.6


def _drop_hallucinations(segments: typing.Iterable[typing.Any], max_no_speech: float) -> str:
    """Join the segments Whisper is actually confident about.

    Whisper answers near-silence with fluent filler — "Thank you.", "I'm going
    to be…" — not with an empty string, and it reports those with a high
    no_speech_prob while still being *lexically* confident (a good avg_logprob).
    faster-whisper's built-in no_speech_threshold only skips a segment when both
    signals agree it's bad, so exactly this case survives it. Rejecting on
    either signal alone is what stops a stray VAD trip from becoming a spoken
    command and, with continuous conversation on, a conversation with itself.
    """
    kept: typing.List[str] = []
    dropped: typing.List[str] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
        avg_logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
        if no_speech > max_no_speech or avg_logprob < _MIN_AVG_LOGPROB:
            dropped.append(f"{text!r} (no_speech={no_speech:.2f}, logprob={avg_logprob:.2f})")
            continue
        kept.append(text)

    if dropped:
        helpers.diagnostics.add(
            "info", "STT",
            "Dropped as hallucination: " + "; ".join(dropped),
            dedupe=False,
        )
    return " ".join(kept).strip()


class Recognizer:
    # True after a call that failed (STT exception), False after a call that
    # simply captured no speech. Lets callers distinguish "didn't hear you"
    # from "something broke" and pick the right spoken feedback.
    last_call_failed: bool = False

    # True after a call where the VAD never heard speech begin at all (nothing
    # to transcribe), as opposed to speech that was captured but came back
    # empty/unintelligible. A wake word followed by pure silence is almost
    # always a false trigger, and callers use this to stay quiet about it.
    last_capture_empty: bool = False

    @staticmethod
    def recognize_speech_from_mic(start_timeout: typing.Optional[float] = None) -> str:
        global _last_used
        Recognizer.last_call_failed = False
        Recognizer.last_capture_empty = False
        try:
            audio = Audio.record_command(start_timeout=start_timeout)
            if audio is None or len(audio) == 0:
                Recognizer.last_capture_empty = True
                return ""
            raw_lang = str(Config.get("assistant.language", "en")).lower()
            # Normalize "en-us" / "en_US" → "en"; faster-whisper expects ISO 639-1 codes.
            language = raw_lang.split("-")[0].split("_")[0]
            if language != raw_lang:
                helpers.diagnostics.add(
                    "info", "STT",
                    f"Language '{raw_lang}' normalized to '{language}' for faster-whisper."
                )
            with _model_lock:
                model = _get_model()
                # no vad_filter: record_command already endpoints with webrtcvad; a second pass over-trims short clips.
                segments, _ = model.transcribe(
                    audio,
                    language=language,
                    beam_size=1,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                )
                text = _drop_hallucinations(segments, _MAX_NO_SPEECH_PROB)
                _last_used = time.monotonic()
            if not text:
                # Whisper produced only filler — the same outcome as capturing
                # nothing, and callers must treat it that way (stay quiet, don't
                # start a conversation turn) rather than as a failure.
                Recognizer.last_capture_empty = True
            return text
        except Exception as e:
            helpers.diagnostics.add("error", "STT", f"Transcription failed: {e}", hint="Check GPU/CPU model load and audio input.")
            Recognizer.last_call_failed = True
            return ""
