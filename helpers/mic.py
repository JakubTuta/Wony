"""
Shared audio I/O layer. Input capture trusts the OS default input device —
which respects the user's routing (SteelSeries Sonar, VoiceMeeter, NVIDIA
Broadcast, … expose the user's *real* processed mic as a virtual device, and
that virtual device is the correct one to record from). We only reject the
default when it is a pure loopback / system-audio capture (Stereo Mix, "what
you hear", Sonar's system mix), which would carry playback audio and cause
false wake-word triggers.

Rationale for trusting the default: on a virtual-audio-mixer setup the physical
"raw" mic endpoint is often taken over and muted by the mixer, so picking it
yields near-silence; the browser and every other app capture the default and
work. Matching that behaviour is both simpler and more portable than trying to
out-guess the OS.

Single-input-stream contract: only one input stream may be open at a time.
WakeWordListener enforces this via pause()/resume() before STT records.
Any external caller that needs the mic outside that flow (tray "Listen now",
Ctrl+L) should hold `voice_session` for the duration.

PortAudio stream lifetime must be tracked via pa_stream_guard() around every
open stream, so try_reinitialize_portaudio() can safely re-enumerate devices
(sd._terminate()/_initialize() destroys ALL open PortAudio streams
process-wide — it must only run when nothing is open). This lets the never-die
capture loop rediscover a changed OS default (Windows switches the default
input when devices connect/disconnect, but PortAudio freezes its list at init).
Lock-ordering rule: never take _resolved_input_lock while holding _pa_lock.
"""
import contextlib
import collections
import os
import queue
import threading
import typing

import numpy as np
import sounddevice as sd
import soundfile as sf

_SR_TARGET = 16000
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Probe tuning: short enough to not stall startup/recovery, long enough to
# average out a couple of audio blocks.
_PROBE_SECONDS = 0.35
_PROBE_DEADLINE = 1.5

# Substrings (lowercase) marking a device that carries system-PLAYBACK audio
# (loopback / mix). These are the only genuine false-wake risk and the only
# hard exclusion for capture. NOTE: virtual *microphone* endpoints (Sonar
# Microphone, VoiceMeeter Out, NVIDIA Broadcast mic) are deliberately NOT here
# — on those setups they carry the user's real processed mic and are the
# correct capture device.
_LOOPBACK_PATTERNS: typing.Tuple[str, ...] = (
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
    "sonar - stream",   # SteelSeries Sonar system/game mix (playback), not the mic
    "sonar - game",
    "sonar - chat",     # chat mix aggregate, not the raw mic
)

# Aggregate / mapper pseudo-devices — not real capture endpoints; never choose
# them, but they are never the OS default either.
_MAPPER_PATTERNS: typing.Tuple[str, ...] = (
    "sound mapper",
    "primary sound capture",
    "primary sound driver",
)

_resolved_input_device: typing.Optional[int] = None
_resolved_input_lock = threading.Lock()
_resolution_degraded = False

_resolved_output_device: typing.Optional[int] = None
_resolved_output_lock = threading.Lock()

# Default render endpoint ID as of the last PortAudio (re)init. Compared
# against the live default at playback time so output can follow the OS
# default (e.g. plugging in headphones) the same way input already does.
_pa_render_id: typing.Optional[str] = None
_reinit_requested = threading.Event()

# Process-wide arbiter for anything that wants exclusive mic access outside
# the wake-word loop's own pause()/resume() handshake (tray "Listen now",
# global Ctrl+L hotkey). Non-blocking acquire — skip cleanly if busy.
voice_session = threading.Lock()

_pa_lock = threading.Lock()
_pa_stream_count = 0


def _is_loopback(name: str) -> bool:
    n = name.lower()
    return any(pat in n for pat in _LOOPBACK_PATTERNS)


def _is_excluded_input(name: str) -> bool:
    """True when a device must never be a capture source (loopback or mapper)."""
    n = name.lower()
    return any(pat in n for pat in _LOOPBACK_PATTERNS) or any(pat in n for pat in _MAPPER_PATTERNS)


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


def _device_is_excluded(name: str, all_devs: typing.List[dict]) -> bool:
    """Check name + any longer counterpart names (e.g. WASAPI full name)."""
    if _is_excluded_input(name):
        return True
    return any(_is_excluded_input(n) for n in _get_extended_names(name, all_devs))


def device_is_excluded(name: str, all_devs: typing.List[dict]) -> bool:
    """Public: True if `name` would never be picked as a capture device
    (loopback/mix/mapper). Used by callers reporting the device matrix (doctor)."""
    return _device_is_excluded(name, all_devs)


def default_devices() -> typing.Tuple[int, int]:
    """Return (default_input_index, default_output_index) as PortAudio sees them."""
    return sd.default.device[0], sd.default.device[1]


def _rank_candidate(item: typing.Tuple[int, dict]) -> typing.Tuple[int, int]:
    """WASAPI > WDM-KS > MME/DirectSound > other, tiebreak by device index.

    WASAPI shared mode runs at the device's native format and doesn't force
    the Windows audio engine to change shared-mode format for other streams
    (unlike MME, which can degrade playback quality elsewhere).
    """
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


def _invalidate_input_device() -> None:
    """Clear cached resolve result (call after a device open/read failure)."""
    global _resolved_input_device
    with _resolved_input_lock:
        _resolved_input_device = None


def resolution_is_degraded() -> bool:
    """True when we had to override the OS default input (it was a loopback
    device) and fall back to a substitute mic — kept for the periodic
    upgrade-recheck in the wake loop."""
    return _resolution_degraded


def _invalidate_output_device() -> None:
    global _resolved_output_device
    with _resolved_output_lock:
        _resolved_output_device = None


def _get_default_render_endpoint_id() -> typing.Optional[str]:
    """Return the OS default output endpoint's stable ID via one cheap COM call.

    Used only at playback-session boundaries (not per-chunk) to detect a
    default-device change (e.g. headphones plugged in) — a full
    IMMNotificationClient callback registration would need a persistent
    COM-registered listener object for a fact only needed at stream-open time.
    """
    try:
        import comtypes
        from comtypes import GUID
        from pycaw.pycaw import IMMDeviceEnumerator

        comtypes.CoInitialize()
        try:
            CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator)
            # eRender=0, eConsole=0
            device = enumerator.GetDefaultAudioEndpoint(0, 0)
            return str(device.GetId())
        finally:
            comtypes.CoUninitialize()
    except Exception:
        return None


def output_endpoint_stale() -> bool:
    """True if the OS default render device has changed since the last
    PortAudio (re)init — i.e. output is still bound to a stale/possibly-dead
    device and should be reinitialized before the next playback session."""
    if _pa_render_id is None:
        return False
    current = _get_default_render_endpoint_id()
    return current is not None and current != _pa_render_id


def request_portaudio_reinit() -> None:
    """Ask the wake-word loop to reinit PortAudio on its next idle iteration
    (it holds the only long-lived input stream, so it's the one place a
    reinit can safely run — see pa_stream_guard's stream-count == 0 rule)."""
    _reinit_requested.set()


def consume_reinit_request() -> bool:
    """True (once) if a reinit was requested. Clears the flag."""
    if _reinit_requested.is_set():
        _reinit_requested.clear()
        return True
    return False


# ── PortAudio stream registry ────────────────────────────────────────────────


@contextlib.contextmanager
def pa_stream_guard() -> typing.Generator[None, None, None]:
    """Hold for the full lifetime of any sounddevice stream.

    Lets try_reinitialize_portaudio() know it's safe to call sd._terminate()/
    sd._initialize() (which destroys every open PortAudio stream process-wide).
    """
    global _pa_stream_count
    with _pa_lock:
        _pa_stream_count += 1
    try:
        yield
    finally:
        with _pa_lock:
            _pa_stream_count -= 1


def try_reinitialize_portaudio() -> bool:
    """Re-enumerate PortAudio's device list (frozen at process init).

    Only runs when no stream is currently open — returns False otherwise so
    the caller can retry later instead of tearing down active audio.
    """
    global _pa_render_id
    with _pa_lock:
        if _pa_stream_count > 0:
            return False
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            return False
    _invalidate_input_device()
    _invalidate_output_device()
    _pa_render_id = _get_default_render_endpoint_id()
    return True


# ── Signal probe ──────────────────────────────────────────────────────────────


def probe_input_device(
    idx: int, seconds: float = _PROBE_SECONDS, deadline: float = _PROBE_DEADLINE
) -> typing.Tuple[bool, str]:
    """Briefly open device `idx` and check it delivers finite, non-silent audio.

    Callback-based InputStream + Event.wait(deadline) — a blocking stream.read()
    can hang indefinitely on a device whose backend died; this cannot.
    Returns (ok, detail); detail explains the rejection for diagnostics.
    """
    try:
        info = sd.query_devices(idx, "input")
    except Exception as e:
        return False, f"query failed: {e}"

    rate = int(info["default_samplerate"]) or 16000
    frames_needed = int(rate * seconds)
    collected: typing.List[np.ndarray] = []
    done = threading.Event()

    def _callback(indata, frames, time_info, status) -> None:
        if done.is_set():
            return
        collected.append(indata[:, 0].copy())
        if sum(len(c) for c in collected) >= frames_needed:
            done.set()

    with pa_stream_guard():
        stream = None
        try:
            stream = sd.InputStream(
                samplerate=rate, channels=1, dtype="float32", device=idx, callback=_callback,
            )
            stream.start()
            if not done.wait(deadline):
                return False, "timeout — device did not deliver audio"
        except Exception as e:
            return False, f"open failed: {e}"
        finally:
            if stream is not None:
                try:
                    stream.abort()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

    if not collected:
        return False, "no audio delivered"
    samples = np.concatenate(collected)
    if not np.all(np.isfinite(samples)):
        return False, "non-finite samples (garbage device)"
    rms = float(np.sqrt(np.mean(np.square(samples))))
    # We deliberately do NOT reject on low RMS. A wireless headset mic
    # (SteelSeries Arctis) powers down when idle and delivers near-silent
    # buffers for the first moments after a stream opens; a quiet room reads
    # near-silent too. Neither is distinguishable from a truly dead endpoint by
    # amplitude alone — rejecting on it throws away the real mic. The actual
    # false-wake risk (virtual/system-audio devices) is handled by the
    # name-exclusion list, so the probe only confirms the device opens and
    # delivers finite audio. `quiet` is surfaced in the detail for diagnostics.
    tag = "ok" if rms >= 1e-4 else "ok, quiet"
    return True, f"{tag} (rms={rms:.6f})"


class FrameReader:
    """Bounded-timeout frame reader backed by a callback InputStream.

    Manual `sd.InputStream(...).read(blocksize)` has been observed to hang
    indefinitely on some WASAPI endpoints (live case: SteelSeries Arctis Nova
    5) even though the same device delivers audio fine through a callback —
    sounddevice's own `rec()`/`play()` helpers and probe_input_device() are
    both callback-based internally and do not exhibit the hang. This gives
    callers the same "read one block" shape but backed by a callback + queue,
    so a stalled device raises queue.Empty instead of blocking the calling
    thread (and anything coordinating with it — e.g. the wake-word pause()
    handshake) forever.
    """

    def __init__(self, samplerate: int, blocksize: int, device: int, timeout: float = 3.0) -> None:
        self._queue: "queue.Queue" = queue.Queue(maxsize=8)
        self._timeout = timeout
        self._guard = pa_stream_guard()
        self._guard.__enter__()
        try:
            self._stream = sd.InputStream(
                samplerate=samplerate, channels=1, dtype="float32",
                blocksize=blocksize, device=device, callback=self._on_data,
            )
            self._stream.start()
        except Exception:
            self._guard.__exit__(None, None, None)
            raise

    def _on_data(self, indata, frames, time_info, status) -> None:
        try:
            self._queue.put_nowait(indata[:, 0].copy())
        except Exception:
            pass  # queue full — drop the frame rather than block the PortAudio callback thread

    def read(self) -> np.ndarray:
        """Return the next block. Raises queue.Empty if the device stalls."""
        return self._queue.get(timeout=self._timeout)

    def close(self) -> None:
        try:
            self._stream.abort()
        except Exception:
            pass
        try:
            self._stream.close()
        except Exception:
            pass
        try:
            self._guard.__exit__(None, None, None)
        except Exception:
            pass


def resolve_output_device() -> typing.Optional[int]:
    """Return the index of the output device to play through, or None for the
    OS default (sounddevice's device=None binds to sd.default.device[1]).

    Mirrors resolve_input_device(): trusts the OS default unless
    voice.output_device names a specific device. Cached; invalidated on
    PortAudio reinit.
    """
    global _resolved_output_device
    with _resolved_output_lock:
        if _resolved_output_device is not None:
            return _resolved_output_device

        import helpers.diagnostics as diagnostics

        try:
            from helpers.config import Config
            override = Config.get("voice.output_device", None)
        except Exception:
            override = None

        if override is None:
            return None  # OS default — sounddevice resolves this itself

        try:
            if isinstance(override, int):
                info = sd.query_devices(override, "output")
                _resolved_output_device = override
                diagnostics.add("info", "Audio", f"Using configured output device [{override}] {info['name']}")
                return _resolved_output_device
            needle = str(override).lower()
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_output_channels"] > 0 and needle in dev["name"].lower():
                    _resolved_output_device = i
                    diagnostics.add("info", "Audio", f"Using configured output device [{i}] {dev['name']}")
                    return _resolved_output_device
            diagnostics.add("warning", "Audio", f"voice.output_device '{override}' not found — falling back to OS default")
        except Exception as e:
            diagnostics.add("warning", "Audio", f"voice.output_device override failed ({e}) — falling back to OS default")

        return None


def resolve_input_device() -> int:
    """Return the index of the input device to capture from.

    Policy: trust the OS default input (it respects the user's audio routing —
    Sonar/VoiceMeeter/NVIDIA-Broadcast expose the real processed mic as the
    default). Only override it when the default is a pure loopback / system-
    audio capture, in which case pick the first non-loopback real mic instead.
    No liveness probing at resolve time — the never-die capture loop handles a
    dead/stalled device via read-failure recovery + PortAudio reinit.

    Respects optional config key voice.input_device (int index or name substring).
    Result is cached; call _invalidate_input_device() after device open/read
    failures to force re-resolution.
    """
    global _resolved_input_device, _resolution_degraded
    with _resolved_input_lock:
        if _resolved_input_device is not None:
            return _resolved_input_device

        import helpers.diagnostics as diagnostics

        all_devs = list(sd.query_devices())

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
                    _resolution_degraded = False
                    diagnostics.add("info", "MIC", f"Using configured input device [{override}] {info['name']}")
                    return _resolved_input_device
                needle = str(override).lower()
                for i, dev in enumerate(all_devs):
                    if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                        _resolved_input_device = i
                        _resolution_degraded = False
                        diagnostics.add("info", "MIC", f"Using configured input device [{i}] {dev['name']}")
                        return _resolved_input_device
                diagnostics.add("warning", "MIC", f"voice.input_device '{override}' not found — falling back to OS default")
            except Exception as e:
                diagnostics.add("warning", "MIC", f"voice.input_device override failed ({e}) — falling back to OS default")

        # ── Trust the OS default unless it carries system-playback audio ──────
        default_idx = sd.default.device[0]
        try:
            default_info = sd.query_devices(default_idx, "input")
            default_name = default_info["name"]
        except Exception:
            _resolved_input_device = default_idx
            _resolution_degraded = False
            return _resolved_input_device

        if not _is_loopback(default_name) and not any(
            _is_loopback(n) for n in _get_extended_names(default_name, all_devs)
        ):
            _resolved_input_device = default_idx
            _resolution_degraded = False
            diagnostics.add("info", "MIC", f"Using OS default input [{default_idx}] '{default_name}'")
            return _resolved_input_device

        # Default is a loopback/mix — substitute the first real (non-loopback,
        # non-mapper) mic, WASAPI-preferred.
        candidates = [
            (idx, dev)
            for idx, dev in enumerate(all_devs)
            if dev["max_input_channels"] > 0 and not _device_is_excluded(dev["name"], all_devs)
        ]
        candidates.sort(key=_rank_candidate)
        if candidates:
            idx, dev = candidates[0]
            _resolved_input_device = idx
            _resolution_degraded = True
            diagnostics.add(
                "warning", "MIC",
                f"OS default [{default_idx}] '{default_name}' is a loopback/mix device — "
                f"using [{idx}] '{dev['name']}' instead to avoid capturing system audio.",
            )
            return _resolved_input_device

        # No real mic found — keep the default rather than hard-break capture.
        diagnostics.add(
            "error", "MIC",
            f"OS default [{default_idx}] '{default_name}' looks like loopback and no other mic was found — "
            "using it anyway; capture may include system audio.",
        )
        _resolved_input_device = default_idx
        _resolution_degraded = True
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
            with pa_stream_guard():
                stream = sd.OutputStream(
                    samplerate=sr, channels=channels, dtype="float32", device=resolve_output_device()
                )
                stream.start()
                stream.write(arr)
                stream.stop()
                stream.close()
        except Exception as e:
            import helpers.diagnostics
            helpers.diagnostics.add("warning", "Audio", f"Playback failed: {e}")

    if blocking:
        _do_play()
    else:
        threading.Thread(target=_do_play, daemon=True).start()


def play_wav(filename: str, blocking: bool = False) -> None:
    """Play a WAV file on the system default output device.

    Relative paths are resolved against the repo root (not the process CWD),
    so playback works regardless of what directory the app was launched from.
    blocking=False (default): spawns a daemon thread and returns immediately.
    blocking=True: blocks until playback finishes.
    """
    if not os.path.isabs(filename):
        filename = os.path.join(_REPO_ROOT, filename)
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

    Backed by FrameReader (callback-based) rather than blocking sd.rec()/
    sd.wait() — the latter carries the same read-hang risk on some WASAPI
    endpoints that FrameReader was built to avoid (see its docstring).
    """
    device = resolve_input_device()
    native = default_input_rate()
    target_frames = int(native * seconds)
    block = max(1, int(native * 0.05))  # 50ms blocks

    reader = FrameReader(native, block, device)
    collected: typing.List[np.ndarray] = []
    total = 0
    try:
        while total < target_frames:
            try:
                chunk = reader.read()
            except queue.Empty:
                raise RuntimeError("input device stalled during record_native()")
            collected.append(chunk)
            total += len(chunk)
    finally:
        reader.close()

    if not collected:
        return np.zeros(0, dtype=np.float32), native
    recording = np.concatenate(collected)[:target_frames]
    return recording, native


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

    reader = FrameReader(native, native_block, device)
    try:
        while not stop_event.is_set():
            try:
                mono = reader.read()
            except Exception:
                break  # device stalled — end the utterance rather than hang forever
            f16 = to_16k_mono_f32(mono, native)
            if len(f16) < out_frame:
                f16 = np.pad(f16, (0, out_frame - len(f16)))
            else:
                f16 = f16[:out_frame]
            pcm16 = np.clip(f16 * 32768.0, -32768, 32767).astype(np.int16)
            yield vad.is_speech(pcm16.tobytes(), _SR_TARGET), f16
    finally:
        reader.close()


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
