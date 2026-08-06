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

One shared stream per direction — this is the single audio system the whole app
uses, and no code outside this module may open a PortAudio stream of its own:

  input   FrameReader → _CaptureHub   (wake word, STT/VAD, barge-in)
  output  playback_session() → _PlaybackHub   (cached clips, earcon, TTS)

OPENING OR CLOSING a stream is audible on real hardware — a wireless headset
re-negotiates its link, a virtual mixer re-arms its chain. On capture that used
to happen up to four times per voice turn (wake word closes → STT opens/closes
→ barge-in opens/closes → wake word reopens), plus a full cycle per false wake;
on playback, once for the wake ack and again for the reply. Every one of those
was a pop in whatever else the user was listening to. The hubs make a whole
turn cost one open per direction, and linger after the last user lets go so
back-to-back hand-offs reuse the stream instead of reopening it.

Both hubs open at the device's native mix format (WASAPI shared mode accepts
nothing else) and adapt audio to it — see output_format/adapt_for_output. The
playback hub is callback-driven and emits silence when nothing is queued, so
an underrun degrades to a gap rather than a glitch, and every session's edges
are ramped (fade_edges) so playback never steps the DAC off zero.

`voice_session` still serializes *logical* sessions (who owns the user's
speech), and WakeWordListener still pause()s so the wake model doesn't listen
to a command meant for STT — but neither is about device ownership any more.

PortAudio stream lifetime must be tracked via pa_stream_guard() around every
open stream, so try_reinitialize_portaudio() can safely re-enumerate devices
(sd._terminate()/_initialize() destroys ALL open PortAudio streams
process-wide — it must only run when nothing is open). This lets the never-die
capture loop rediscover a changed OS default (Windows switches the default
input when devices connect/disconnect, but PortAudio freezes its list at init).
Lock-ordering rules: never take _resolved_input_lock while holding _pa_lock,
and never take _CaptureHub._lock while holding _pa_lock (the hub takes
pa_stream_guard, which takes _pa_lock).
"""
import contextlib
import collections
import os
import queue
import threading
import time
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

# Discard a capture with less than this much *voiced* audio (not capture
# length — every capture also carries preroll + trailing silence). Guards
# against a stray VAD blip reaching Whisper, which answers near-silence with
# fluent filler rather than an empty string. A developer knob, not a user
# setting: a normal user has no way to judge this number, they just want the
# assistant to stop inventing sentences out of a door slam.
_MIN_SPEECH_MS = 250

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
# global push-to-talk hotkey). Non-blocking acquire — skip cleanly if busy.
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


# ── Host API selection ───────────────────────────────────────────────────────


_PREFERRED_HOSTAPI = "wasapi"


def _preferred_hostapi_index() -> typing.Optional[int]:
    """Index of the preferred host API, or None if it isn't available (non-
    Windows, or a stripped PortAudio build) — callers then fall back to
    PortAudio's own default."""
    try:
        for i, ha in enumerate(sd.query_hostapis()):
            if _PREFERRED_HOSTAPI in ha.get("name", "").lower():
                return i
    except Exception:
        pass
    return None


def _hostapi_default_device(kind: str) -> typing.Optional[int]:
    """Default input/output device index *within* the preferred host API.

    PortAudio's process-wide default (sd.default.device) resolves to the MME
    device on Windows. MME is a legacy emulation layer: it resamples everything
    to its own fixed rate before Windows resamples again to the endpoint's mix
    format, and it re-opens the endpoint per stream — which costs quality and
    produces audible clicks on virtual endpoints (SteelSeries Sonar, VoiceMeeter).
    Every host API also publishes its own default, and WASAPI's tracks the real
    OS default endpoint — so this yields the same physical device over a
    materially better transport.
    """
    api = _preferred_hostapi_index()
    if api is None:
        return None
    try:
        idx = sd.query_hostapis(api).get(f"default_{kind}_device", -1)
    except Exception:
        return None
    if idx is None or int(idx) < 0:
        return None
    try:
        info = sd.query_devices(int(idx))
    except Exception:
        return None
    channels = info["max_input_channels"] if kind == "input" else info["max_output_channels"]
    return int(idx) if channels > 0 else None


def output_format(device: typing.Optional[int] = None) -> typing.Tuple[int, int]:
    """Native (samplerate, channels) for the resolved output device.

    WASAPI shared mode accepts *only* the endpoint's exact mix format — opening
    at anything else fails outright (verified live: a 96 kHz/8ch endpoint
    rejects both 48000/2 and 24000/1). So playback adapts our audio to the
    device instead of asking the device to adapt to us, which also means no
    Windows-side sample-rate conversion ever runs on the path.
    """
    if device is None:
        device = resolve_output_device()
    try:
        info = sd.query_devices(device, "output") if device is not None else sd.query_devices(kind="output")
        return int(info["default_samplerate"]), max(1, int(info["max_output_channels"]))
    except Exception:
        return 24000, 1


def adapt_for_output(samples: np.ndarray, sr: int, target_sr: int, target_ch: int) -> np.ndarray:
    """Resample `samples` to `target_sr` and lay it out across `target_ch` channels.

    Resampling happens here, with soxr's very-high-quality polyphase filter,
    rather than being left to MME/Windows — that is the point of opening the
    device at its native rate. Mono content goes to the front L/R pair; any
    surround/LFE channels stay silent.
    """
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float32, copy=False)

    if sr != target_sr and len(samples):
        try:
            import soxr
            samples = soxr.resample(samples, sr, target_sr, quality="VHQ").astype(np.float32)
        except Exception:
            n = int(round(len(samples) * target_sr / sr))
            samples = np.interp(
                np.linspace(0, len(samples), n, endpoint=False),
                np.arange(len(samples)),
                samples,
            ).astype(np.float32)

    if target_ch <= 1:
        return samples.reshape(-1, 1)
    out = np.zeros((len(samples), target_ch), dtype=np.float32)
    out[:, 0] = samples
    out[:, 1] = samples
    return out


_FADE_MS = 5.0


def fade_edges(block: np.ndarray, sr: int, fade_in: bool = False, fade_out: bool = False) -> np.ndarray:
    """Ramp the first/last few ms to silence.

    A stream that starts or stops on a non-zero sample steps the DAC output
    discontinuously, and that step is the audible click. Ramping the edges to
    zero costs 5ms and removes it.
    """
    n = int(sr * _FADE_MS / 1000.0)
    if n <= 0 or len(block) < 2 * n or not (fade_in or fade_out):
        return block
    block = block.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32).reshape(-1, 1)
    if fade_in:
        block[:n] *= ramp
    if fade_out:
        block[-n:] *= ramp[::-1]
    return block


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
    """Clear cached resolve result (call after a device open/read failure).

    Also marks the shared capture stream stale so it is rebuilt against the
    re-resolved device instead of being reused — otherwise the hub's linger
    would hand a dead stream to the next subscriber.
    """
    global _resolved_input_device
    with _resolved_input_lock:
        _resolved_input_device = None
    _capture_hub.mark_stale()


def resolution_is_degraded() -> bool:
    """True when we had to override the OS default input (it was a loopback
    device) and fall back to a substitute mic — kept for the periodic
    upgrade-recheck in the wake loop."""
    return _resolution_degraded


def _invalidate_output_device() -> None:
    global _resolved_output_device
    with _resolved_output_lock:
        _resolved_output_device = None
    _playback_hub.mark_stale()


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


_OPEN_ATTEMPTS = 3
_OPEN_RETRY_DELAY = 0.15


def _open_stream_with_retry(factory: typing.Callable[[], typing.Any]) -> typing.Tuple[typing.Any, typing.Any]:
    """Open and start a stream, retrying a few times. Returns (stream, guard).

    The first open of a virtual/wireless endpoint reproducibly fails with
    paUnanticipatedHostError while the device spins up, then succeeds
    immediately after — observed on both directions of a SteelSeries
    Sonar/Arctis stack. Retrying here keeps that off callers' error/backoff
    paths, where it used to cost an extra open/close cycle (audible) on
    capture and a hard failure on playback.
    """
    last: typing.Optional[Exception] = None
    for attempt in range(_OPEN_ATTEMPTS):
        guard = pa_stream_guard()
        guard.__enter__()
        try:
            stream = factory()
            stream.start()
            return stream, guard
        except Exception as e:
            guard.__exit__(None, None, None)
            last = e
            if attempt < _OPEN_ATTEMPTS - 1:
                time.sleep(_OPEN_RETRY_DELAY)
    raise last if last is not None else RuntimeError("stream open failed")


def try_reinitialize_portaudio() -> bool:
    """Re-enumerate PortAudio's device list (frozen at process init).

    Only runs when no stream is currently open — returns False otherwise so
    the caller can retry later instead of tearing down active audio.
    """
    global _pa_render_id
    # The hubs hold the only long-lived streams, so pa_stream_guard's count can
    # never reach zero until they let go. Done before taking _pa_lock — see the
    # module's lock-ordering rules.
    _capture_hub.close_if_idle()
    _playback_hub.close_if_idle()
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


_HUB_BLOCK_MS = 10.0
# Hold the stream open this long after the last subscriber leaves, so the
# close-then-immediately-reopen hand-offs in a voice turn reuse it.
_HUB_LINGER_SECONDS = 5.0
# ~320ms of slack per subscriber. Dropping is preferable to ever blocking the
# PortAudio callback thread.
_HUB_QUEUE_BLOCKS = 32


class _Subscription:
    """One consumer's view of the shared capture stream.

    The hub delivers fixed _HUB_BLOCK_MS chunks; this re-blocks them into
    whatever frame count the consumer asked for.
    """

    def __init__(self, hub: "_CaptureHub", rate: int) -> None:
        self.rate = rate
        self.queue: "queue.Queue" = queue.Queue(maxsize=_HUB_QUEUE_BLOCKS)
        self._hub = hub
        self._pending: typing.List[np.ndarray] = []
        self._pending_frames = 0
        self._closed = False

    def read(self, frames: int, timeout: float) -> np.ndarray:
        """Return exactly `frames` samples. Raises queue.Empty if the device
        stalls for longer than `timeout` before the block is complete."""
        deadline = time.monotonic() + timeout
        while self._pending_frames < frames:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            block = self.queue.get(timeout=remaining)
            self._pending.append(block)
            self._pending_frames += len(block)

        buf = self._pending[0] if len(self._pending) == 1 else np.concatenate(self._pending)
        out, rest = buf[:frames], buf[frames:]
        self._pending = [rest] if len(rest) else []
        self._pending_frames = len(rest)
        return out

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._hub._unsubscribe(self)


class _CaptureHub:
    """The single process-wide capture stream, fanned out to N subscribers.

    See the module docstring for why device open/close must be avoided rather
    than merely tolerated. Blocks handed to subscribers are shared read-only —
    no consumer may mutate a block in place.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream: typing.Any = None
        self._guard: typing.Any = None
        self._rate = 0
        # Replaced (never mutated) under _lock so the PortAudio callback can
        # read it without taking a lock.
        self._subs: typing.Tuple[_Subscription, ...] = ()
        self._linger_timer: typing.Optional[threading.Timer] = None
        # Set when a caller reports the device as dead/changed; the stream is
        # then rebuilt as soon as the last subscriber lets go.
        self._stale = False

    # ── Consumer API ────────────────────────────────────────────────────────

    def subscribe(self) -> _Subscription:
        with self._lock:
            self._cancel_linger()
            if self._stream is not None and self._stale and not self._subs:
                self._close_locked()
            if self._stream is None:
                self._open_locked()
                self._stale = False
            sub = _Subscription(self, self._rate)
            self._subs = self._subs + (sub,)
            return sub

    def _unsubscribe(self, sub: _Subscription) -> None:
        with self._lock:
            self._subs = tuple(s for s in self._subs if s is not sub)
            if self._subs:
                return
            if self._stale:
                self._close_locked()  # no point lingering a dead stream
            else:
                self._start_linger()

    def mark_stale(self) -> None:
        """Report the device as dead or changed. The stream is rebuilt on the
        next subscribe once every current subscriber has let go."""
        with self._lock:
            if self._stream is None:
                return
            self._stale = True
            if not self._subs:
                self._close_locked()

    def close_if_idle(self) -> bool:
        """Close the stream if nothing is subscribed (including during a
        linger). True if no stream is open afterwards.

        Must NOT be called while holding _pa_lock — see the module's
        lock-ordering rules.
        """
        with self._lock:
            self._cancel_linger()
            if self._subs:
                return False
            self._close_locked()
            return True

    @property
    def rate(self) -> int:
        return self._rate

    # ── Internals (all called under _lock) ──────────────────────────────────

    def _open_locked(self) -> None:
        device = resolve_input_device()
        info = sd.query_devices(device, "input")
        rate = int(info["default_samplerate"]) or _SR_TARGET
        blocksize = max(1, int(round(rate * _HUB_BLOCK_MS / 1000.0)))

        self._stream, self._guard = _open_stream_with_retry(
            lambda: sd.InputStream(
                samplerate=rate, channels=1, dtype="float32",
                blocksize=blocksize, device=device, callback=self._on_data,
            )
        )
        self._rate = rate

    def _close_locked(self) -> None:
        stream, guard = self._stream, self._guard
        self._stream, self._guard = None, None
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if guard is not None:
            try:
                guard.__exit__(None, None, None)
            except Exception:
                pass

    def _on_data(self, indata, frames, time_info, status) -> None:
        block = indata[:, 0].copy()
        for sub in self._subs:  # atomic tuple read — no lock on the audio thread
            try:
                sub.queue.put_nowait(block)
            except Exception:
                pass  # full — drop rather than block the PortAudio callback

    def _start_linger(self) -> None:
        self._cancel_linger()
        timer = threading.Timer(_HUB_LINGER_SECONDS, self._linger_expired)
        timer.daemon = True
        self._linger_timer = timer
        timer.start()

    def _cancel_linger(self) -> None:
        if self._linger_timer is not None:
            self._linger_timer.cancel()
            self._linger_timer = None

    def _linger_expired(self) -> None:
        with self._lock:
            self._linger_timer = None
            if not self._subs:
                self._close_locked()


_capture_hub = _CaptureHub()


class FrameReader:
    """Bounded-timeout frame reader over the shared capture stream.

    Manual `sd.InputStream(...).read(blocksize)` has been observed to hang
    indefinitely on some WASAPI endpoints (live case: SteelSeries Arctis Nova
    5) even though the same device delivers audio fine through a callback —
    sounddevice's own `rec()`/`play()` helpers and probe_input_device() are
    both callback-based internally and do not exhibit the hang. This gives
    callers the same "read one block" shape but backed by a callback + queue,
    so a stalled device raises queue.Empty instead of blocking the calling
    thread (and anything coordinating with it — e.g. the wake-word pause()
    handshake) forever.

    `samplerate` is the rate the caller *expected*; the shared stream may
    already be open at the device's native rate, so the real rate is exposed as
    `.rate` and callers must resample from that. `blocksize` is scaled
    accordingly, keeping the request's duration intact.
    """

    def __init__(self, samplerate: int, blocksize: int, timeout: float = 3.0) -> None:
        self.timeout = timeout
        self._sub = _capture_hub.subscribe()
        self.rate = self._sub.rate
        self.blocksize = (
            max(1, int(round(blocksize * self.rate / samplerate))) if samplerate else blocksize
        )

    def read(self) -> np.ndarray:
        """Return the next block. Raises queue.Empty if the device stalls."""
        return self._sub.read(self.blocksize, self.timeout)

    def close(self) -> None:
        self._sub.close()


# ── Shared playback stream ───────────────────────────────────────────────────

# Long enough to span an entire voice turn — wake ack, up to 12s of listening,
# then the reply — so one turn costs one device open instead of three.
_PLAYBACK_LINGER_SECONDS = 20.0
# Audio queued ahead of the device. Bounds how long an interrupt takes to go
# quiet, and how much slack there is for a slow synthesis step.
_PLAYBACK_HIGH_WATER_MS = 250.0
_PLAYBACK_CHUNK_MS = 50.0
# How long the queue may fail to drain at all before the device is declared
# dead. Generous — normal back-pressure drains continuously.
_PLAYBACK_STALL_SECONDS = 5.0


class _PlaybackWriter:
    """Serialized handle for writing to the shared output stream.

    Holds the hub's writer lock for its whole lifetime, so a streamed reply
    stays gapless and nothing (an earcon, a notification) can interleave into
    the middle of it.
    """

    def __init__(self, hub: "_PlaybackHub") -> None:
        self._hub = hub
        self._first_write = True

    @property
    def samplerate(self) -> int:
        return self._hub.samplerate

    @property
    def channels(self) -> int:
        return self._hub.channels

    def play(
        self,
        samples: np.ndarray,
        sr: int,
        interrupt_event: typing.Optional[threading.Event] = None,
    ) -> bool:
        """Adapt `samples` to the device format and queue them.

        Blocks while the queue is full (back-pressure), checking
        `interrupt_event` throughout. Returns False if interrupted — the queue
        is then cut short on a ramp so playback ends at zero rather than
        stepping the DAC mid-waveform, which is the audible click.
        """
        arr = adapt_for_output(samples, sr, self.samplerate, self.channels)
        if self._first_write:
            # Coming off silence: ramp in so the DAC doesn't step off zero.
            arr = fade_edges(arr, self.samplerate, fade_in=True)
            self._first_write = False

        chunk = max(1, int(self.samplerate * _PLAYBACK_CHUNK_MS / 1000.0))
        for i in range(0, len(arr), chunk):
            if not self._hub._submit(arr[i : i + chunk], interrupt_event):
                self._hub._cut()
                return False
        return True

    def drain(self, interrupt_event: typing.Optional[threading.Event] = None) -> None:
        """Block until everything queued has actually been played."""
        self._hub._drain(interrupt_event)


class _PlaybackHub:
    """The single process-wide output stream, mirroring _CaptureHub.

    Callback-driven with a pending-audio queue: when nothing is queued the
    callback emits silence, so the stream can stay open between clips instead
    of being opened and closed per clip (see the module docstring — those
    transitions are audible). That also means an underrun degrades to a gap
    rather than a glitch.

    Opened at the endpoint's native mix format, because WASAPI shared mode
    accepts nothing else; callers hand over audio at any rate and it is
    resampled here via adapt_for_output.
    """

    def __init__(self) -> None:
        # Lock order is _writer_lock → _lock → _buf_lock. acquire() takes them
        # in that order, so anything holding _lock (mark_stale, close_if_idle,
        # the linger timer) may only ever try _writer_lock non-blocking.
        self._lock = threading.RLock()
        self._writer_lock = threading.RLock()
        self._buf_lock = threading.Lock()
        self._stream: typing.Any = None
        self._guard: typing.Any = None
        self._rate = 0
        self._channels = 0
        self._pending: typing.Deque[np.ndarray] = collections.deque()
        self._pending_frames = 0
        self._last_frame: typing.Optional[np.ndarray] = None
        self._linger_timer: typing.Optional[threading.Timer] = None
        self._stale = False
        # Diagnostics: times the callback ran dry mid-buffer (i.e. a gap).
        self.starved = 0

    @property
    def samplerate(self) -> int:
        return self._rate

    @property
    def channels(self) -> int:
        return self._channels

    # ── Consumer API ────────────────────────────────────────────────────────

    def acquire(self) -> _PlaybackWriter:
        """Take the writer lock and make sure the stream is open."""
        self._writer_lock.acquire()
        try:
            with self._lock:
                self._cancel_linger()
                if self._stream is not None and self._stale:
                    self._close_locked()
                if self._stream is None:
                    self._open_locked()
                    self._stale = False
            return _PlaybackWriter(self)
        except Exception:
            self._writer_lock.release()
            raise

    def release(self) -> None:
        with self._lock:
            if self._stale:
                self._close_locked()
            else:
                self._start_linger()
        self._writer_lock.release()

    def mark_stale(self) -> None:
        """Report the endpoint as changed. Rebuilt on the next acquire."""
        with self._lock:
            if self._stream is None:
                return
            self._stale = True
            if self._writer_lock.acquire(blocking=False):
                try:
                    self._close_locked()
                finally:
                    self._writer_lock.release()

    def close_if_idle(self) -> bool:
        """Close the stream if nobody is writing (including during a linger).

        Must NOT be called while holding _pa_lock — see the module's
        lock-ordering rules.
        """
        with self._lock:
            self._cancel_linger()
            if not self._writer_lock.acquire(blocking=False):
                return False
            try:
                self._close_locked()
            finally:
                self._writer_lock.release()
            return True

    # ── Internals ───────────────────────────────────────────────────────────

    def _open_locked(self) -> None:
        import helpers.diagnostics

        device = resolve_output_device()
        self._rate, self._channels = output_format(device)
        with self._buf_lock:
            self._pending.clear()
            self._pending_frames = 0
            self._last_frame = None

        self._stream, self._guard = _open_stream_with_retry(
            lambda: sd.OutputStream(
                samplerate=self._rate, channels=self._channels, dtype="float32",
                device=device, callback=self._on_data,
            )
        )
        helpers.diagnostics.add(
            "info", "Audio",
            f"Output stream open @ {self._rate} Hz / {self._channels}ch.",
        )

    def _close_locked(self) -> None:
        stream, guard = self._stream, self._guard
        self._stream, self._guard = None, None
        if stream is not None:
            try:
                stream.stop()  # drain what's queued rather than cutting the DAC
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if guard is not None:
            try:
                guard.__exit__(None, None, None)
            except Exception:
                pass

    def _on_data(self, outdata, frames, time_info, status) -> None:
        filled = 0
        with self._buf_lock:
            while filled < frames and self._pending:
                block = self._pending[0]
                take = min(frames - filled, len(block))
                outdata[filled : filled + take] = block[:take]
                if take == len(block):
                    self._pending.popleft()
                else:
                    self._pending[0] = block[take:]
                self._pending_frames -= take
                filled += take
        if filled < frames:
            outdata[filled:] = 0
            if filled:
                self.starved += 1

    def _submit(
        self, block: np.ndarray, interrupt_event: typing.Optional[threading.Event]
    ) -> bool:
        high_water = int(self._rate * _PLAYBACK_HIGH_WATER_MS / 1000.0)
        stall_deadline = time.monotonic() + _PLAYBACK_STALL_SECONDS
        lowest_seen: typing.Optional[int] = None
        while True:
            if interrupt_event is not None and interrupt_event.is_set():
                return False
            with self._buf_lock:
                if self._pending_frames <= high_water:
                    self._pending.append(block)
                    self._pending_frames += len(block)
                    if len(block):
                        self._last_frame = block[-1].copy()
                    return True
                pending_now = self._pending_frames

            # Back-pressure is normal; the callback draining nothing at all is
            # not. Without this a dead output device would block the speaking
            # thread forever instead of surfacing as a device failure.
            if lowest_seen is None or pending_now < lowest_seen:
                lowest_seen = pending_now
                stall_deadline = time.monotonic() + _PLAYBACK_STALL_SECONDS
            elif time.monotonic() > stall_deadline:
                self._stale = True
                raise RuntimeError("output stream stopped consuming audio")
            time.sleep(0.005)

    def _cut(self) -> None:
        """Drop queued audio, keeping a short ramp so it ends at zero."""
        n = max(1, int(self._rate * _FADE_MS / 1000.0))
        with self._buf_lock:
            head = self._pending[0] if self._pending else None
            self._pending.clear()
            self._pending_frames = 0
            self._last_frame = None
            if head is None or not len(head):
                return
            take = min(n, len(head))
            ramp = np.linspace(1.0, 0.0, take, dtype=np.float32).reshape(-1, 1)
            self._pending.append(head[:take] * ramp)
            self._pending_frames = take

    def _queue_tail_ramp(self) -> None:
        """End on a ramp to zero if the last sample written wasn't silent."""
        with self._buf_lock:
            frame = self._last_frame
            if frame is None or not np.any(frame):
                return
            n = max(1, int(self._rate * _FADE_MS / 1000.0))
            ramp = np.linspace(1.0, 0.0, n, dtype=np.float32).reshape(-1, 1)
            self._pending.append(frame.reshape(1, -1) * ramp)
            self._pending_frames += n
            self._last_frame = None

    def _drain(self, interrupt_event: typing.Optional[threading.Event] = None) -> None:
        with self._buf_lock:
            queued_seconds = self._pending_frames / float(self._rate or _SR_TARGET)
        # Bounded by what is actually queued, so a stalled device ends the wait
        # instead of holding the caller forever.
        deadline = time.monotonic() + queued_seconds + _PLAYBACK_STALL_SECONDS
        while True:
            if interrupt_event is not None and interrupt_event.is_set():
                return
            with self._buf_lock:
                if self._pending_frames <= 0:
                    break
            if time.monotonic() > deadline:
                self._stale = True
                break
            time.sleep(0.01)
        # The device still holds whatever the callback already collected.
        try:
            latency = float(self._stream.latency) if self._stream is not None else 0.0
        except Exception:
            latency = 0.0
        time.sleep(min(0.5, max(0.02, latency)))

    def _start_linger(self) -> None:
        self._cancel_linger()
        timer = threading.Timer(_PLAYBACK_LINGER_SECONDS, self._linger_expired)
        timer.daemon = True
        self._linger_timer = timer
        timer.start()

    def _cancel_linger(self) -> None:
        if self._linger_timer is not None:
            self._linger_timer.cancel()
            self._linger_timer = None

    def _linger_expired(self) -> None:
        with self._lock:
            self._linger_timer = None
            if self._writer_lock.acquire(blocking=False):
                try:
                    self._close_locked()
                finally:
                    self._writer_lock.release()


_playback_hub = _PlaybackHub()


@contextlib.contextmanager
def playback_session() -> typing.Generator[_PlaybackWriter, None, None]:
    """Exclusive handle on the shared output stream for one speech session.

    Every playback path in the app goes through this — cached clips, the
    earcon, and streamed TTS — so they all get the same device resolution,
    native-format adaptation, click-free edges, and (crucially) all reuse one
    open stream instead of opening their own.

    Blocks until anything queued has played before releasing.
    """
    writer = _playback_hub.acquire()
    try:
        yield writer
    finally:
        try:
            _playback_hub._queue_tail_ramp()
            _playback_hub._drain()
        except Exception:
            pass
        _playback_hub.release()


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
            # OS default, but reached through the preferred host API (WASAPI)
            # rather than PortAudio's MME default — same endpoint, native format,
            # no legacy resampling layer. None means "let sounddevice decide".
            _resolved_output_device = _hostapi_default_device("output")
            if _resolved_output_device is not None:
                info = sd.query_devices(_resolved_output_device)
                api = sd.query_hostapis(info["hostapi"])["name"]
                diagnostics.add(
                    "info", "Audio",
                    f"Output [{_resolved_output_device}] {info['name']} via {api} "
                    f"@ {int(info['default_samplerate'])} Hz / {info['max_output_channels']}ch",
                )
            return _resolved_output_device

        try:
            if isinstance(override, int):
                info = sd.query_devices(override, "output")
                _resolved_output_device = override
                diagnostics.add("info", "Audio", f"Using configured output device [{override}] {info['name']}")
                return _resolved_output_device
            needle = str(override).lower()
            # Preferred host API first, so a name match doesn't land on the MME
            # copy of a device that also exists under WASAPI.
            api = _preferred_hostapi_index()
            devices = list(enumerate(sd.query_devices()))
            ordered = [it for it in devices if it[1]["hostapi"] == api] + [it for it in devices if it[1]["hostapi"] != api]
            for i, dev in ordered:
                if dev["max_output_channels"] > 0 and needle in dev["name"].lower():
                    _resolved_output_device = i
                    diagnostics.add("info", "Audio", f"Using configured output device [{i}] {dev['name']}")
                    return _resolved_output_device
            diagnostics.add("warning", "Audio", f"voice.output_device '{override}' not found — falling back to OS default")
        except Exception as e:
            diagnostics.add("warning", "Audio", f"voice.output_device override failed ({e}) — falling back to OS default")

        _resolved_output_device = _hostapi_default_device("output")
        return _resolved_output_device


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
                # Preferred host API first, so a name match doesn't land on the
                # MME copy of a device that also exists under WASAPI.
                api = _preferred_hostapi_index()
                ordered = [it for it in enumerate(all_devs) if it[1]["hostapi"] == api]
                ordered += [it for it in enumerate(all_devs) if it[1]["hostapi"] != api]
                for i, dev in ordered:
                    if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                        _resolved_input_device = i
                        _resolution_degraded = False
                        diagnostics.add("info", "MIC", f"Using configured input device [{i}] {dev['name']}")
                        return _resolved_input_device
                diagnostics.add("warning", "MIC", f"voice.input_device '{override}' not found — falling back to OS default")
            except Exception as e:
                diagnostics.add("warning", "MIC", f"voice.input_device override failed ({e}) — falling back to OS default")

        # ── Trust the OS default unless it carries system-playback audio ──────
        # Preferred host API's default first: it names the same OS-default
        # endpoint as sd.default.device[0], but as its WASAPI entry — native
        # 48 kHz instead of MME's resampled 44.1 kHz (a clean 3:1 ratio down to
        # the 16 kHz STT models, rather than 44100/16000).
        default_idx = _hostapi_default_device("input")
        if default_idx is None:
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
    def _do_play() -> None:
        try:
            with playback_session() as out:
                out.play(data, sr)
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
    native = default_input_rate()
    block = max(1, int(native * 0.05))  # 50ms blocks

    reader = FrameReader(native, block)
    native = reader.rate  # the shared stream is authoritative, not our guess
    target_frames = int(native * seconds)
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
    native = default_input_rate()
    frame_ms = 30
    out_frame = int(_SR_TARGET * frame_ms / 1000)  # 480 samples @16k
    native_block = int(round(native * out_frame / _SR_TARGET))

    reader = FrameReader(native, native_block)
    native = reader.rate  # the shared stream is authoritative, not our guess
    t0 = time.monotonic()
    delivered_ms = 0.0
    try:
        while not stop_event.is_set():
            try:
                mono = reader.read()
            except Exception:
                import helpers.diagnostics as diagnostics
                diagnostics.add("warning", "MIC", "Input device stalled during capture — reopening.")
                _invalidate_input_device()
                break  # device stalled — end the utterance rather than hang forever

            delivered_ms += frame_ms
            elapsed = time.monotonic() - t0
            # A healthy device delivers ~1 frame per frame_ms. If delivery has
            # fallen behind wall clock by more than half (checked only after a
            # couple of seconds to avoid false positives on stream startup),
            # the device is dribbling frames — same effective hang as
            # queue.Empty, just slow enough not to trip the read timeout.
            if elapsed >= 2.0 and delivered_ms < elapsed * 1000 * 0.5:
                import helpers.diagnostics as diagnostics
                diagnostics.add("warning", "MIC", "Input device delivering audio too slowly — reopening.")
                _invalidate_input_device()
                break

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
    cancel_event: typing.Optional[threading.Event] = None,
    min_speech_ms: int = _MIN_SPEECH_MS,
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
        cancel_event: if set while recording, capture aborts and returns empty
            immediately (deliberate cancel — never transcribe a half-capture).
        min_speech_ms: discard the capture unless the VAD flagged at least this
            much *voiced* audio. Note this is not the capture's length: every
            capture also carries `preroll_ms` plus the `silence_ms` that ended
            it, so a single VAD blip on a door slam still yields ~1s of array.
            Handing that to Whisper is what produces confident nonsense
            ("Thank you.", "I'm going to be…") in place of an empty string.

    Deadlines are wall-clock (time.monotonic), not frame counts — a stalled or
    slow-delivering mic (see vad_frame_stream) no longer stretches a nominal
    4-12s window into minutes; worst-case overshoot is bounded by one
    FrameReader read timeout.

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
    silence_needed_s = silence_ms / 1000.0

    ring: typing.Deque[np.ndarray] = collections.deque(maxlen=preroll_frames)
    voiced: typing.List[np.ndarray] = []
    started = False
    speech_frames = 0
    last_voice_t = 0.0

    t0 = time.monotonic()
    stop = threading.Event()
    gen = vad_frame_stream(stop, vad_aggressiveness)
    try:
        for is_speech, f16 in gen:
            now = time.monotonic()

            if cancel_event is not None and cancel_event.is_set():
                voiced = []
                break
            if now - t0 >= max_seconds:
                break
            if not started and now - t0 >= start_timeout:
                break

            if not started:
                ring.append(f16)
                if is_speech:
                    started = True
                    speech_frames = 1
                    voiced.extend(ring)
                    ring.clear()
                    last_voice_t = now
            else:
                voiced.append(f16)
                if is_speech:
                    speech_frames += 1
                    last_voice_t = now
                elif now - last_voice_t >= silence_needed_s:
                    break
    finally:
        gen.close()
        stop.set()

    if not voiced:
        return np.zeros(0, dtype=np.float32)

    speech_ms = speech_frames * frame_ms
    if speech_ms < min_speech_ms:
        import helpers.diagnostics as diagnostics
        diagnostics.add(
            "info", "MIC",
            f"Discarded capture — only {speech_ms}ms of speech (need {min_speech_ms}ms).",
        )
        return np.zeros(0, dtype=np.float32)

    return np.concatenate(voiced).astype(np.float32)
