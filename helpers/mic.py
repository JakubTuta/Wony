"""
Shared audio I/O layer.

Always uses the system default input/output device — works with any physical
or virtual device regardless of native sample rate.

Single-input-stream contract: only one input stream may be open at a time.
WakeWordListener enforces this via pause()/resume() before STT records.
"""
import threading
import typing

import numpy as np
import sounddevice as sd
import soundfile as sf

_SR_TARGET = 16000


def default_input_rate() -> int:
    """Return the native sample rate of the system default input device."""
    idx = sd.default.device[0]
    info = sd.query_devices(idx, "input")
    return int(info["default_samplerate"])


def to_16k_mono_f32(samples: np.ndarray, in_rate: int) -> np.ndarray:
    """Resample mono float32 array to 16 kHz. Uses soxr; falls back to linear interp."""
    if in_rate == _SR_TARGET:
        return samples.astype(np.float32)
    try:
        import soxr
        return soxr.resample(samples.astype(np.float32), in_rate, _SR_TARGET)
    except Exception:
        n = int(round(len(samples) * _SR_TARGET / in_rate))
        return np.interp(
            np.linspace(0, len(samples), n, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)


def play_wav(filename: str, blocking: bool = False) -> None:
    """Play a WAV file on the system default output device.

    blocking=False (default): spawns a daemon thread and returns immediately.
    blocking=True: blocks until playback finishes.
    """
    data, sr = sf.read(filename, dtype="float32", always_2d=False)
    if blocking:
        sd.play(data, sr)
        sd.wait()
    else:
        def _play() -> None:
            try:
                sd.play(data, sr)
                sd.wait()
            except Exception as e:
                print(f"[mic] playback failed: {e}")
        threading.Thread(target=_play, daemon=True).start()


def record_native(seconds: float) -> typing.Tuple[np.ndarray, int]:
    """Record from the default input at its native sample rate.

    Returns (mono float32 ndarray, native_rate_hz).
    Caller must ensure no other input stream is open (single-stream contract).
    """
    native = default_input_rate()
    frames = int(native * seconds)
    recording = sd.rec(frames, samplerate=native, channels=1, dtype="float32")
    sd.wait()
    return recording[:, 0], native


def record_16k(seconds: float) -> np.ndarray:
    """Record from the default input and resample to 16 kHz mono float32."""
    raw, rate = record_native(seconds)
    return to_16k_mono_f32(raw, rate)
