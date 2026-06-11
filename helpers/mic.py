"""
Shared audio I/O layer. Always uses the system default input/output device.

Single-input-stream contract: only one input stream may be open at a time.
WakeWordListener enforces this via pause()/resume() before STT records.
"""
import collections
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


def _play(data: np.ndarray, sr: int, blocking: bool) -> None:
    if blocking:
        sd.play(data, sr)
        sd.wait()
    else:
        def _bg() -> None:
            try:
                sd.play(data, sr)
                sd.wait()
            except Exception as e:
                print(f"[mic] playback failed: {e}")
        threading.Thread(target=_bg, daemon=True).start()


def play_wav(filename: str, blocking: bool = False) -> None:
    """Play a WAV file on the system default output device.

    blocking=False (default): spawns a daemon thread and returns immediately.
    blocking=True: blocks until playback finishes.
    """
    data, sr = sf.read(filename, dtype="float32", always_2d=False)
    _play(data, sr, blocking)


def play_array(samples: np.ndarray, sr: int, blocking: bool = True) -> None:
    """Play a numpy float32 audio array on the system default output device.

    blocking=True (default): blocks until playback finishes.
    blocking=False: spawns a daemon thread and returns immediately.
    """
    _play(samples, sr, blocking)


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


def vad_frame_stream(
    stop_event: threading.Event,
    vad_aggressiveness: int = 2,
) -> typing.Generator[typing.Tuple[bool, np.ndarray], None, None]:
    """Yield (is_speech, frame_16k_float32) for each 30ms mic frame until stop_event is set.

    Opens and owns a single InputStream; closes it on exit (GeneratorExit or StopIteration).
    Caller must ensure no other input stream is open (single-stream contract).
    Silently returns immediately if webrtcvad is not installed.
    """
    try:
        import webrtcvad
    except ImportError:
        return

    vad = webrtcvad.Vad(int(vad_aggressiveness))
    native = default_input_rate()
    frame_ms = 30
    out_frame = int(_SR_TARGET * frame_ms / 1000)  # 480 samples @16k
    native_block = int(round(native * out_frame / _SR_TARGET))

    stream = sd.InputStream(
        samplerate=native, channels=1, dtype="float32", blocksize=native_block
    )
    stream.start()
    try:
        while not stop_event.is_set():
            data, _ = stream.read(native_block)
            f16 = to_16k_mono_f32(data[:, 0], native)
            if len(f16) < out_frame:
                f16 = np.pad(f16, (0, out_frame - len(f16)))
            else:
                f16 = f16[:out_frame]
            pcm16 = np.clip(f16 * 32768.0, -32768, 32767).astype(np.int16)
            yield vad.is_speech(pcm16.tobytes(), _SR_TARGET), f16
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


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
        del webrtcvad
    except ImportError:
        return record_16k(3)

    frame_ms = 30
    preroll_frames = max(1, int(preroll_ms / frame_ms))
    silence_frames_needed = max(1, int(silence_ms / frame_ms))
    max_frames = int(max_seconds * 1000 / frame_ms)
    timeout_frames = int(start_timeout * 1000 / frame_ms)

    ring: typing.Deque[np.ndarray] = collections.deque(maxlen=preroll_frames)
    voiced: typing.List[np.ndarray] = []
    started = False
    silence_run = 0
    frames_seen = 0

    stop = threading.Event()
    gen = vad_frame_stream(stop, vad_aggressiveness)
    try:
        for is_speech, f16 in gen:
            frames_seen += 1

            if frames_seen > max_frames:
                break
            if not started and frames_seen > timeout_frames:
                break

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
        gen.close()
        stop.set()

    if not voiced:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(voiced).astype(np.float32)
