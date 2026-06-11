import typing

import helpers.diagnostics
from helpers.audio import Audio
from helpers.compute import _GPU_FIX_HINT, ctranslate2_cuda_count
from helpers.config import Config

_model: typing.Any = None


def _build_model() -> typing.Any:
    import ctranslate2
    from faster_whisper import WhisperModel

    language = str(Config.get("assistant.language", "en")).lower()

    if ctranslate2_cuda_count() > 0:
        try:
            print("Loading speech model (first run downloads ~1 GB, please wait)...")
            return WhisperModel("large-v3", device="cuda", compute_type="float16")
        except Exception as e:
            helpers.diagnostics.add("warning", "STT", f"CUDA detected but model load failed ({e}) — falling back to CPU", hint=_GPU_FIX_HINT)

    helpers.diagnostics.add("warning", "STT", "No CUDA GPU — using CPU speech model (slower).", hint=_GPU_FIX_HINT)

    # distil-small.en is faster and more accurate than small but English-only.
    if language.startswith("en"):
        try:
            print("Loading speech model (first run downloads ~0.5 GB, please wait)...")
            return WhisperModel("distil-small.en", device="cpu", compute_type="int8")
        except Exception:
            pass
    print("Loading speech model (first run downloads ~0.5 GB, please wait)...")
    return WhisperModel("small", device="cpu", compute_type="int8")


def _get_model() -> typing.Any:
    global _model
    if _model is None:
        _model = _build_model()
    return _model


def preload_model() -> None:
    _get_model()


class Recognizer:
    @staticmethod
    def recognize_speech_from_mic(start_timeout: typing.Optional[float] = None) -> str:
        try:
            audio = Audio.record_command(start_timeout=start_timeout)
            if audio is None or len(audio) == 0:
                return ""
            language = Config.get("assistant.language", "en")
            model = _get_model()
            # no vad_filter: record_command already endpoints with webrtcvad; a second pass over-trims short clips.
            segments, _ = model.transcribe(
                audio,
                language=language,
                beam_size=1,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
            )
            return " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            print(f"Couldn't capture audio — check your microphone. ({e})")
            return ""
