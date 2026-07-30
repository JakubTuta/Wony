"""
openWakeWord-based wake-word listener.

Detection flow: sounddevice captures audio from the resolved input device
(see helpers.mic.resolve_input_device — trusts the OS default, no liveness
probe at resolve time) at its native sample rate, resampled to 16 kHz mono
int16 for openWakeWord. On trigger:
  1. Acquire mic.voice_session (so tray "Listen now" / Ctrl+L can't collide)
  2. Release the mic (sounddevice stream stopped/closed)
  3. Play the "Yes?" ack clip (Audio.play_cached)
  4. STT via faster-whisper (Recognizer.recognize_speech_from_mic)
  5. Pass transcript to employer.handle_utterance (acquires agent_lock internally)
  6. Reopen the mic stream and reset the model buffer, release voice_session

The main loop never dies on a capture error: read/open failures are
contained per-iteration, trigger cache invalidation + escalating backoff,
and — after repeated failures — a guarded PortAudio re-enumeration (see
helpers.mic.try_reinitialize_portaudio) so a device that came back (e.g. a
wireless headset powered back on) can be rediscovered without a restart.

Single-input-stream contract: the listener closes its stream before STT records.

Config keys (voice.wake_word.*):
  enabled          bool  - master switch
  phrase           str   - built-in model name (ignored when model_path is set)
                          valid: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"
  model_path       str   - path to a custom .onnx model (optional, relative to repo root)
  threshold        float - detection score cutoff, 0..1 (default 0.5)
  cooldown_seconds float - ignore re-triggers within this window after detection

False-trigger tuning lives in the constants below (_PATIENCE_FRAMES,
_VAD_THRESHOLD) rather than config.yaml — they are developer knobs, not
settings a user should have to understand to get a working app.

Required pip packages: openwakeword onnxruntime sounddevice soxr numpy
No account or API key required.
"""

import os
import queue
import threading
import time
import typing

import helpers.diagnostics as diagnostics

_FRAME_SIZE = 1280  # 80 ms at 16 kHz
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAX_BACKOFF = 5.0
_DEGRADED_RECHECK_INTERVAL = 300.0  # 5 min
# Floor between full PortAudio re-inits. See _recover() — a re-init disturbs
# every audio app on the machine, so a persistently failing mic must not cause
# one on every retry cycle.
_MIN_REINIT_INTERVAL = 60.0
# Consecutive FrameReader read timeouts (0.5s each) tolerated before the stream
# is considered stalled and reopened. See the read() call site.
_MAX_READ_TIMEOUTS = 4
_BUILTIN_PHRASES = {"hey jarvis", "alexa", "hey mycroft", "hey rhasspy"}
# Consecutive frames (80 ms each) that must all clear `threshold` before firing.
# A spoken wake word keeps the model confident across several frames; a
# transient — a keyboard clack, a notification chirp, one syllable off a video —
# spikes a single frame and drops. This is the main false-trigger gate, and it
# is preferred over simply raising `threshold`, because the hey_wony model is
# weak on real voice and needs a low cutoff to fire at all.
_PATIENCE_FRAMES = 2
# Silero speech pre-gate (openWakeWord's own): audio it scores below this never
# reaches the wake-word model. Raise toward 0.7 if music or game audio triggers.
_VAD_THRESHOLD = 0.5


class WakeWordListener:
    def __init__(
        self,
        employer: typing.Any,
        exit_event: typing.Optional[threading.Event] = None,
    ) -> None:
        self._employer = employer
        self._exit_event = exit_event
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._resume_event = threading.Event()
        self._mic_released = threading.Event()
        self._mic_released.set()  # no stream open yet
        self._thread: typing.Optional[threading.Thread] = None
        self._enabled = False

        self._reader: typing.Any = None
        self._native_rate: int = 16000
        self._native_block: int = _FRAME_SIZE

        try:
            self._enabled = self._init_engine()
        except Exception as e:
            diagnostics.add("error", "WakeWord", f"Disabled — init failed: {e}", hint="Check openwakeword install and config voice.wake_word.phrase.")

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_engine(self) -> bool:
        from helpers.config import Config

        cfg = Config.get("voice.wake_word", {})
        if not cfg.get("enabled", False):
            return False

        try:
            import openwakeword  # noqa: F401
            from openwakeword.model import Model  # noqa: F401
        except ImportError:
            diagnostics.add("warning", "WakeWord", "Disabled — openwakeword not installed.", hint="pip install -r requirements/wakeword.txt")
            return False

        try:
            import sounddevice  # noqa: F401
        except ImportError:
            diagnostics.add("warning", "WakeWord", "Disabled — sounddevice not installed.", hint="pip install -r requirements/wakeword.txt")
            return False

        try:
            import numpy  # noqa: F401
        except ImportError:
            diagnostics.add("warning", "WakeWord", "Disabled — numpy not installed.", hint="pip install -r requirements/wakeword.txt")
            return False

        # Download pre-trained weights on first run (no-op if already present)
        try:
            import openwakeword

            openwakeword.utils.download_models()
        except Exception as e:
            diagnostics.add("warning", "WakeWord", f"Model download failed (offline?): {e} — continuing with cached models.")

        model_path = cfg.get("model_path") or None
        if model_path and not os.path.isabs(model_path):
            model_path = os.path.join(_REPO_ROOT, model_path)
        phrase = cfg.get("phrase", "hey jarvis")
        self._threshold = float(cfg.get("threshold", 0.5))
        self._cooldown = float(cfg.get("cooldown_seconds", 2.0))
        self._last_trigger = 0.0

        # A missing/invalid custom model or an unrecognized phrase must never
        # silently disable wake word — fall back to a working built-in instead.
        fell_back = False
        if model_path and not os.path.exists(model_path):
            diagnostics.add(
                "error", "WakeWord",
                f"Custom model '{model_path}' not found — falling back to a built-in phrase.",
                hint="Train it (training/train_hey_wony.ipynb or .sh) or unset voice.wake_word.model_path.",
            )
            model_path = None
            fell_back = True

        if model_path is None and phrase.lower() not in _BUILTIN_PHRASES:
            diagnostics.add(
                "warning", "WakeWord",
                f"'{phrase}' is not a built-in phrase — using 'hey jarvis' instead.",
                hint='Valid built-in phrases: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy". '
                "For a custom phrase, train a model (training/train_hey_wony.ipynb or .sh).",
            )
            phrase = "hey jarvis"
            fell_back = True

        if fell_back:
            # A threshold tuned for a specific (possibly weak) custom model
            # would false-fire constantly on a different model — don't carry it over.
            self._threshold = max(self._threshold, 0.5)

        # Silero VAD pre-gate cuts false triggers from non-speech noise.
        vad_threshold = _VAD_THRESHOLD
        # Speex noise suppression helps in noisy/far-field rooms, but the
        # speexdsp-ns package is effectively Linux-only — guarded below.
        noise_suppression = bool(cfg.get("noise_suppression", False))
        models = [model_path] if model_path else [phrase]

        from openwakeword.model import Model

        def _build(model_list: list) -> typing.Any:
            kwargs: dict = {
                "wakeword_models": model_list,
                "inference_framework": "onnx",
                "vad_threshold": vad_threshold,
            }
            if noise_suppression:
                kwargs["enable_speex_noise_suppression"] = True
            try:
                return Model(**kwargs)
            except Exception as inner:
                # Retry without speex NS (unavailable on this platform) and/or
                # without newer kwargs (older openwakeword).
                if noise_suppression:
                    diagnostics.add("warning", "WakeWord", f"Noise suppression unavailable ({inner}) — continuing without it.")
                kwargs.pop("enable_speex_noise_suppression", None)
                try:
                    return Model(**kwargs)
                except TypeError:
                    return Model(wakeword_models=model_list, inference_framework="onnx")

        try:
            self._oww = _build(models)
        except Exception as e:
            if models == ["hey jarvis"]:
                diagnostics.add(
                    "error", "WakeWord", f"Disabled — openWakeWord init failed: {e}",
                    hint='Valid built-in phrases: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"',
                )
                return False
            diagnostics.add(
                "warning", "WakeWord",
                f"Model init failed for '{models[0]}' ({e}) — retrying with built-in 'hey jarvis'.",
            )
            phrase = "hey jarvis"
            models = [phrase]
            self._threshold = max(self._threshold, 0.5)
            try:
                self._oww = _build(models)
            except Exception as e2:
                diagnostics.add("error", "WakeWord", f"Disabled — openWakeWord init failed even with built-in fallback: {e2}")
                return False

        # Resolve the model key from the constructed model (avoids hardcoding)
        keys = (
            list(self._oww.prediction_buffer.keys())
            if hasattr(self._oww, "prediction_buffer")
            else []
        )
        if not keys:
            self._model_key = phrase.lower().replace(" ", "_")
        else:
            phrase_norm = phrase.lower().replace(" ", "_")
            self._model_key = next(
                (k for k in keys if phrase_norm in k.lower().replace(" ", "_")),
                keys[0],
            )

        diagnostics.add(
            "info", "WakeWord",
            f"Ready — listening for '{phrase}' (key: {self._model_key}, "
            f"threshold {self._threshold}, patience {_PATIENCE_FRAMES} frames).",
        )
        return True

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="wakeword",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._resume_event.set()  # wake a paused loop so it notices stop promptly
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def pause(self) -> None:
        """Release mic so another caller can open it. Blocks until the stream is closed.

        Never gives up: proceeding while the wake-word loop still holds the
        stream would violate the single-input-stream contract, so this keeps
        waiting (logging periodically) instead of racing ahead.
        """
        if not self._enabled:
            return
        self._paused.set()
        while not self._mic_released.wait(2.0):
            diagnostics.add("warning", "WakeWord", "pause() still waiting for mic release...")

    def resume(self) -> None:
        """Let the listener reopen the mic stream."""
        self._paused.clear()
        self._resume_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Stream lifecycle ──────────────────────────────────────────────────────

    def _open_stream(self) -> None:
        """Subscribe to the shared capture stream (see helpers.mic._CaptureHub).

        Backed by mic.FrameReader (callback-based) rather than a manual
        blocking InputStream.read() — the latter has been observed to hang
        indefinitely on some WASAPI endpoints. This does not necessarily touch
        the device: the hub reuses an already-open stream, which is why
        subscribing and unsubscribing around a voice turn is silent.
        """
        from helpers import mic

        native_rate = mic.default_input_rate()
        native_block = int(round(native_rate * _FRAME_SIZE / 16000))

        # Short read timeout so a paused/stalled loop reliably notices within
        # pause()'s 2s wait window — normal frame cadence (~80ms) never hits it.
        self._reader = mic.FrameReader(native_rate, native_block, timeout=0.5)
        self._native_rate = self._reader.rate  # shared stream's actual rate
        self._native_block = self._reader.blocksize
        self._mic_released.clear()

    def _close_stream(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
        self._mic_released.set()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            import numpy as np

            from helpers import mic
        except ImportError:
            return

        failures = 0
        streak = 0  # consecutive frames at/above threshold (see _PATIENCE_FRAMES)
        last_degraded_check = time.monotonic()
        last_reinit = 0.0
        read_timeouts = 0

        def _recover() -> None:
            nonlocal failures, last_reinit
            failures += 1
            mic._invalidate_input_device()
            now = time.monotonic()
            # A full re-init re-enumerates every host API (MME, DirectSound,
            # WASAPI, WDM-KS) and WDM-KS enumeration pokes kernel pins on every
            # audio device on the machine — audible as clicks in whatever else
            # is playing. Reopening the stream is cheap and is retried on every
            # failure; the re-init is the heavy hammer, so a device that keeps
            # failing must not trigger one every backoff cycle.
            if failures >= 3 and now - last_reinit >= _MIN_REINIT_INTERVAL:
                # No-op (returns False) if another stream (e.g. TTS) is active —
                # safe to call every time; it just won't do anything until free.
                if mic.try_reinitialize_portaudio():
                    last_reinit = now
            backoff = min(_MAX_BACKOFF, 0.5 * (2 ** (min(failures, 5) - 1)))
            time.sleep(backoff)

        try:
            while not self._stop_event.is_set():
                try:
                    # Paused (STT / push-to-talk owns the mic) or suspended by
                    # the user: let go of the stream and idle until that clears.
                    if self._paused.is_set():
                        if self._reader is not None:
                            self._close_stream()
                            streak = 0
                            read_timeouts = 0
                        self._resume_event.clear()
                        # Timeout only so stop_event still gets checked periodically.
                        self._resume_event.wait(timeout=1.0)
                        continue

                    if self._reader is None:
                        try:
                            self._open_stream()
                            if failures > 0:
                                diagnostics.add("info", "WakeWord", f"Mic capture recovered on [{mic.resolve_input_device()}].")
                                failures = 0
                        except Exception as e:
                            diagnostics.add("warning", "WakeWord", f"Failed to open mic stream: {e} — retrying.")
                            _recover()
                            continue

                    # Periodic upgrade check: once degraded (running on a
                    # fallback device), re-probe every few minutes so a
                    # returned preferred device (e.g. headset powered back on)
                    # gets rediscovered without waiting for a read failure.
                    now = time.monotonic()
                    if mic.resolution_is_degraded() and now - last_degraded_check > _DEGRADED_RECHECK_INTERVAL:
                        last_degraded_check = now
                        self._close_stream()
                        if mic.try_reinitialize_portaudio():
                            diagnostics.add("info", "WakeWord", "PortAudio reinitialized — re-checking for a better input device.")
                        continue

                    # Output side (TTS/notifications) requested a PortAudio
                    # reinit — e.g. the default output device changed mid-
                    # session and stayed stale. This loop holds the only
                    # long-lived input stream, so it's the one place that can
                    # safely close and re-enumerate (pa_stream_guard requires
                    # zero open streams).
                    if mic.consume_reinit_request():
                        self._close_stream()
                        if mic.try_reinitialize_portaudio():
                            diagnostics.add("info", "WakeWord", "PortAudio reinitialized for output device change.")
                        continue

                    try:
                        mono = self._reader.read()
                        read_timeouts = 0
                    except queue.Empty:
                        # A single late block is a hiccup, not a dead device, and
                        # tearing the stream down costs more than it fixes: the
                        # reopen toggles the mic off and on, which on a wireless
                        # headset re-negotiates the link (audible in whatever
                        # else is playing). Only give up after a real stall.
                        read_timeouts += 1
                        if read_timeouts < _MAX_READ_TIMEOUTS:
                            continue
                        diagnostics.add(
                            "warning", "WakeWord",
                            f"No mic audio for {read_timeouts * self._reader.timeout:.1f}s — reopening.",
                        )
                        read_timeouts = 0
                        self._close_stream()
                        _recover()
                        continue
                    except Exception as e:
                        diagnostics.add("warning", "WakeWord", f"Mic read failed: {type(e).__name__}: {e} — reopening.")
                        read_timeouts = 0
                        self._close_stream()
                        _recover()
                        continue

                    frame16 = mic.to_16k_mono_f32(mono, self._native_rate)
                    pcm16 = np.clip(frame16 * 32768.0, -32768, 32767).astype(np.int16)
                    scores = self._oww.predict(pcm16)

                    # Pick score for our target model key
                    score = scores.get(self._model_key)
                    if score is None:
                        score = max(scores.values()) if scores else 0.0

                    # Require the score to hold across consecutive frames —
                    # see _PATIENCE_FRAMES. This is what stops "Wony woke up
                    # on its own".
                    streak = streak + 1 if score >= self._threshold else 0

                    if streak >= _PATIENCE_FRAMES:
                        streak = 0
                        trigger_now = time.monotonic()
                        if trigger_now - self._last_trigger < self._cooldown:
                            continue
                        self._last_trigger = trigger_now
                        # Logged so threshold/patience can be tuned from real
                        # data: compare the scores of genuine wakes against the
                        # ones that turn out to be false triggers.
                        diagnostics.add("info", "WakeWord", f"Detected (score {score:.2f}).")

                        if not mic.voice_session.acquire(blocking=False):
                            continue  # mic busy elsewhere (tray Listen now / Ctrl+L)

                        self._close_stream()
                        try:
                            self._handle_detection()
                        finally:
                            mic.voice_session.release()
                            if not self._stop_event.is_set() and not self._paused.is_set():
                                try:
                                    self._oww.reset()
                                except Exception:
                                    pass
                                try:
                                    self._open_stream()
                                except Exception as e:
                                    diagnostics.add("warning", "WakeWord", f"Failed to reopen mic after detection: {e} — recovering.")
                                    _recover()

                except Exception as e:
                    # Containment of last resort: nothing in this loop may kill
                    # the thread — a dead wake-word thread means the assistant
                    # goes permanently deaf.
                    diagnostics.add("error", "WakeWord", f"Listener loop error: {e} — recovering.")
                    self._close_stream()
                    _recover()
        finally:
            self._close_stream()

    def _handle_detection(self) -> None:
        from helpers.audio import Audio, play_earcon, warm_tts_async
        from helpers.cache import Cache
        from helpers.config import Config
        from helpers.ducking import duck_others
        from helpers.events import clear_cancel, emit_state
        from helpers.recognizer import Recognizer, warm_async

        clear_cancel()  # new session — a cancel from a prior turn must not leak in
        emit_state("listening")
        # Overlap any cold-start model load (when models.preload is off) with
        # the ack clip + the user speaking, instead of stalling silently.
        warm_async()
        warm_tts_async()
        with duck_others():
            if Cache.get_audio():
                Audio.play_cached("Yes?")
            elif bool(Config.get("voice.feedback.ack_when_muted", True)):
                # Muted: no spoken ack, but a short tone still confirms the
                # wake word landed instead of leaving the user guessing.
                play_earcon()

            text = Recognizer.recognize_speech_from_mic()
            if not text:
                from helpers.events import session_cancel
                if Recognizer.last_capture_empty and not Recognizer.last_call_failed:
                    # Woke up, then heard nothing at all — treat it as a false
                    # trigger and say nothing rather than announcing it.
                    diagnostics.add(
                        "info", "WakeWord",
                        "Triggered but no speech followed — ignoring as a false trigger.",
                        hint="Raise voice.wake_word.threshold or patience if this happens often.",
                    )
                elif not session_cancel.is_set():
                    msg = "Sorry, I couldn't process that." if Recognizer.last_call_failed else "I didn't catch that."
                    Audio.play_cached(msg)
                emit_state("idle")
                return

            try:
                self._employer.handle_utterance(text)
            except SystemExit:
                from modules.employer import Employer

                if Employer._exit_hook is not None:
                    Employer._exit_hook()
                elif self._exit_event is not None:
                    self._stop_event.set()
                    self._exit_event.set()
            except Exception as e:
                diagnostics.add("error", "WakeWord", f"Utterance error: {e}")
                Audio.text_to_speech(f"Sorry, something went wrong: {e}")
            finally:
                emit_state("idle")
