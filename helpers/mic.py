"""
Shared audio I/O layer.

Always uses the system default input/output device — works with any physical
or virtual device regardless of native sample rate.

Single-input-stream contract: only one input stream may be open at a time.
WakeWordListener enforces this via pause()/resume() before STT records.
"""
import threading
import time
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


def record_until_silence(
    max_seconds: float = 12.0,
    start_timeout: float = 4.0,
    silence_ms: int = 700,
    vad_aggressiveness: int = 2,
    preroll_ms: int = 300,
) -> np.ndarray:
    """Record until trailing silence (VAD endpointing). Returns 16k mono float32.

    Uses webrtcvad to detect speech start/end so commands aren't clipped (long
    ones) or padded (short ones). Captures a short pre-roll so word onsets are
    preserved. Returns whatever was captured — empty array if no speech.

    Args:
        max_seconds: hard cap on total capture length.
        start_timeout: give up if no speech begins within this window.
        silence_ms: trailing silence that ends the utterance.
        vad_aggressiveness: webrtcvad 0..3 (higher = more aggressive filtering).
        preroll_ms: audio kept before detected speech onset.

    Caller must ensure no other input stream is open (single-stream contract).
    Falls back to a fixed 3 s window if webrtcvad is unavailable.
    """
    try:
        import webrtcvad
    except ImportError:
        return record_16k(3)

    from collections import deque

    vad = webrtcvad.Vad(int(vad_aggressiveness))
    native = default_input_rate()
    frame_ms = 30  # webrtcvad accepts 10/20/30 ms frames only
    out_frame = int(_SR_TARGET * frame_ms / 1000)  # 480 samples @16k
    native_block = int(round(native * out_frame / _SR_TARGET))

    preroll_frames = max(1, int(preroll_ms / frame_ms))
    silence_frames_needed = max(1, int(silence_ms / frame_ms))

    ring: typing.Deque[np.ndarray] = deque(maxlen=preroll_frames)
    voiced: typing.List[np.ndarray] = []
    started = False
    silence_run = 0
    start_deadline = time.monotonic() + start_timeout
    max_deadline = time.monotonic() + max_seconds

    stream = sd.InputStream(
        samplerate=native, channels=1, dtype="float32", blocksize=native_block
    )
    stream.start()
    try:
        while True:
            now = time.monotonic()
            if now > max_deadline:
                break
            if not started and now > start_deadline:
                break

            data, _overflowed = stream.read(native_block)
            f16 = to_16k_mono_f32(data[:, 0], native)
            # webrtcvad needs an exact 480-sample frame
            if len(f16) < out_frame:
                f16 = np.pad(f16, (0, out_frame - len(f16)))
            else:
                f16 = f16[:out_frame]

            pcm16 = np.clip(f16 * 32768.0, -32768, 32767).astype(np.int16)
            is_speech = vad.is_speech(pcm16.tobytes(), _SR_TARGET)

            if not started:
                ring.append(f16)
                if is_speech:
                    started = True
                    voiced.extend(ring)
                    ring.clear()
                    silence_run = 0
            else:
                voiced.append(f16)
                if is_speech:
                    silence_run = 0
                else:
                    silence_run += 1
                    if silence_run >= silence_frames_needed:
                        break
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    if not voiced:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(voiced).astype(np.float32)
