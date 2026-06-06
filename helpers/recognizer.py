import typing

from helpers.audio import Audio
from helpers.config import Config

_model: typing.Any = None


def _build_model() -> typing.Any:
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() > 0:
        try:
            print("Loading speech model (first run downloads ~1 GB, please wait)...")
            return WhisperModel("large-v3", device="cuda", compute_type="float16")
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
    def recognize_speech_from_mic() -> str:
        try:
            audio = Audio.record_audio()  # np.float32 @16kHz mono
            language = Config.get("assistant.language", "en")
            model = _get_model()
            segments, _ = model.transcribe(audio, language=language, beam_size=5)
            return " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            print(f"Couldn't capture audio — check your microphone. ({e})")
            return ""
