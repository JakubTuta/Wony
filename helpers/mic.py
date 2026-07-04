"""
Shared audio I/O layer. All input capture uses resolve_input_device() to pick
a genuine physical microphone and avoid virtual/loopback devices (SteelSeries
Sonar, VoiceMeeter, VB-Cable, Stereo Mix, NVIDIA Broadcast, …) that can carry
system audio and cause false wake-word triggers.

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

# Substrings (lowercase) whose presence in a device name marks it as a
# virtual/loopback/mixer source that should never be the mic capture device.
# Two groups — both are excluded as the *resolved* device:
#   1. Pure loopback / system-audio captures (stereo mix etc.)
#   2. Virtual routing layers (Sonar, VoiceMeeter, NVIDIA Broadcast, …)
_EXCLUDED_INPUT_PATTERNS: typing.Tuple[str, ...] = (
    # system-audio / loopback
    "stereo mix",
    "miks stereo",
    "stereomix",
    "what u hear",
    "what you hear",
    "loopback",
    "wave out mix",
    "rec. playback",
    "miksaż",
    "summe",
    # virtual / aggregate / mapper
    "virtual audio",
    "virtual cable",
    "vb-audio",
    "voicemeeter",
    "cable output",
    "nvidia broadcast",
    "wave link",
    "soundflower",
    "blackhole",
    "sound mapper",
    "primary sound capture",
    "primary sound driver",
)

_resolved_input_device: typing.Optional[int] = None
_resolved_input_lock = threading.Lock()


def _is_excluded_input(name: str) -> bool:
    n = name.lower()
    return any(pat in n for pat in _EXCLUDED_INPUT_PATTERNS)


def _get_extended_names(base_name: str, all_devs: typing.List[dict]) -> typing.List[str]:
    """Return longer names for this device from other host APIs (e.g. WASAPI suffix).

    On Windows, MME names are short; WASAPI names include the full device string
    (e.g. "(SteelSeries Sonar Virtual Audio Device)"). Cross-referencing lets us
    classify a device correctly even when the short MME name omits that info.
    """
    base = base_name.strip()
    return [
        d["name"]
        for d in all_devs
        if d["max_input_channels"] > 0 and d["name"].startswith(base) and len(d["name"]) > len(base)
    ]


def _find_wasapi_counterpart(base_name: str, all_devs: typing.List[dict]) -> typing.Optional[int]:
    """Return the index of the WASAPI version of a device identified by its short name.

    MME devices have truncated names; their WASAPI counterpart has the same prefix but
    a longer name and runs in native-format shared mode (better capture quality, no
    risk of forcing the audio engine to change shared-mode format for other streams).
    Returns None if no WASAPI counterpart exists or if the counterpart is excluded.
    """
    base = base_name.strip()
    try:
        hostapis = list(sd.query_hostapis())
        wasapi_idx = next(
            (i for i, ha in enumerate(hostapis) if "wasapi" in ha.get("name", "").lower()),
            None,
        )
    except Exception:
        return None
    if wasapi_idx is None:
        return None
    for idx, dev in enumerate(all_devs):
        if (
            dev["max_input_channels"] > 0
            and dev.get("hostapi") == wasapi_idx
            and dev["name"].startswith(base)
            and not _is_excluded_input(dev["name"])
        ):
            return idx
    return None


def _invalidate_input_device() -> None:
    """Clear cached resolve result (call after a device open/read failure)."""
    global _resolved_input_device
    with _resolved_input_lock:
        _resolved_input_device = None


def resolve_input_device() -> int:
    """Return the index of the best physical mic input device.

    Respects optional config key voice.input_device (int index or name substring).
    When unset or null, auto-selects: keeps the OS default input if it looks like
    a genuine mic; otherwise substitutes the best non-virtual input device found.
    Falls back to the OS default if no physical mic can be identified (never breaks).
    Result is cached; call _invalidate_input_device() after device open failures.
    """
    global _resolved_input_device
    with _resolved_input_lock:
        if _resolved_input_device is not None:
            return _resolved_input_device

        import helpers.diagnostics as diagnostics

        # ── Optional manual override (voice.input_device in config.yaml) ──────
        try:
            from helpers.config import Config
            override = Config.get("voice.input_device", None)
        except Exception:
            override = None

        if override is not None:
            try:
                if isinstance(override, int):
                    info = sd.query_devices(override, "input")
                    _resolved_input_device = override
                    diagnostics.add("info", "MIC", f"Using configured input device [{override}] {info['name']}")
                    return _resolved_input_device
                else:
                    # substring match
                    needle = str(override).lower()
                    all_devs = list(sd.query_devices())
                    for idx, dev in enumerate(all_devs):
                        if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                            _resolved_input_device = idx
                            diagnostics.add("info", "MIC", f"Using configured input device [{idx}] {dev['name']}")
                            return _resolved_input_device
                    diagnostics.add("warning", "MIC", f"voice.input_device '{override}' not found — falling back to auto-select")
            except Exception as e:
                diagnostics.add("warning", "MIC", f"voice.input_device override failed ({e}) — falling back to auto-select")

        # ── Auto-select ───────────────────────────────────────────────────────
        default_idx = sd.default.device[0]
        try:
            default_info = sd.query_devices(default_idx, "input")
            default_name = default_info["name"]
        except Exception:
            _resolved_input_device = default_idx
            return _resolved_input_device

        all_devs = list(sd.query_devices())

        def _device_is_excluded(name: str) -> bool:
            """Check name + any longer counterpart names (e.g. WASAPI full name).

            On Windows, MME names are short; WASAPI names include the full device
            string (e.g. "(SteelSeries Sonar Virtual Audio Device)").
            Cross-referencing lets us classify a device correctly even when the
            short MME name omits that info.
            """
            if _is_excluded_input(name):
                return True
            return any(_is_excluded_input(n) for n in _get_extended_names(name, all_devs))

        if not _device_is_excluded(default_name):
            # OS default is a real mic — still prefer its WASAPI counterpart if one
            # exists, to avoid MME-induced format changes degrading playback quality.
            wasapi_counterpart = _find_wasapi_counterpart(default_name, all_devs)
            if wasapi_counterpart is not None:
                _resolved_input_device = wasapi_counterpart
            else:
                _resolved_input_device = default_idx
            return _resolved_input_device

        # OS default is a virtual/loopback device — find a physical mic
        default_hostapi = default_info.get("hostapi", -1)

        candidates = [
            (idx, dev)
            for idx, dev in enumerate(all_devs)
            if dev["max_input_channels"] > 0 and not _device_is_excluded(dev["name"])
        ]

        if not candidates:
            # No physical mic found — keep the OS default (capture must not break)
            diagnostics.add(
                "warning", "MIC",
                f"Default input [{default_idx}] '{default_name}' looks virtual but no "
                "physical mic found — capture may include system audio."
            )
            _resolved_input_device = default_idx
            return _resolved_input_device

        # Prefer WASAPI shared mode — it runs at the device's native format and
        # doesn't force the Windows audio engine to change shared-mode format for
        # other streams (unlike MME, which can cause playback quality degradation).
        # Fall back to WDM-KS, then MME/DirectSound, tiebreak by index.
        def _rank(item: typing.Tuple[int, dict]) -> typing.Tuple[int, int]:
            idx, dev = item
            ha = dev.get("hostapi", -1)
            try:
                ha_info = sd.query_hostapis(ha)
                name_lower = ha_info.get("name", "").lower()
            except Exception:
                name_lower = ""
            if "wasapi" in name_lower:
                api_rank = 0
            elif "wdm" in name_lower or "ks" in name_lower:
                api_rank = 1
            elif "mme" in name_lower or "directsound" in name_lower:
                api_rank = 2
            else:
                api_rank = 3
            return (api_rank, idx)

        best_idx, best_dev = min(candidates, key=_rank)
        diagnostics.add(
            "info", "MIC",
            f"Default input '{default_name}' is virtual — using [{best_idx}] '{best_dev['name']}' instead."
        )
        _resolved_input_device = best_idx
        return _resolved_input_device


def default_input_rate() -> int:
    """Return the native sample rate of the resolved physical mic input device."""
    idx = resolve_input_device()
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
    channels = 1 if data.ndim == 1 else data.shape[1]
    arr = data.reshape(-1, 1) if data.ndim == 1 else data.astype("float32")

    def _do_play() -> None:
        try:
            stream = sd.OutputStream(samplerate=sr, channels=channels, dtype="float32")
            stream.start()
            stream.write(arr)
            stream.stop()
            stream.close()
        except Exception as e:
            print(f"[mic] playback failed: {e}")

    if blocking:
        _do_play()
    else:
        threading.Thread(target=_do_play, daemon=True).start()


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
    """Record from the resolved physical mic at its native sample rate.

    Returns (mono float32 ndarray, native_rate_hz).
    Caller must ensure no other input stream is open (single-stream contract).
    """
    device = resolve_input_device()
    native = default_input_rate()
    frames = int(native * seconds)
    recording = sd.rec(frames, samplerate=native, channels=1, dtype="float32", device=device)
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
    device = resolve_input_device()
    native = default_input_rate()
    frame_ms = 30
    out_frame = int(_SR_TARGET * frame_ms / 1000)  # 480 samples @16k
    native_block = int(round(native * out_frame / _SR_TARGET))

    stream = sd.InputStream(
        samplerate=native, channels=1, dtype="float32", blocksize=native_block, device=device
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
