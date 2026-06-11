"""
openWakeWord-based wake-word listener.

Detection flow: sounddevice captures audio from the system default input at its
native sample rate, resampled to 16 kHz mono int16 for openWakeWord. On trigger:
  1. Release the mic (sounddevice stream stopped/closed)
  2. Play listening.wav
  3. STT via faster-whisper (Recognizer.recognize_speech_from_mic)
  4. Pass transcript to employer.handle_utterance (acquires agent_lock internally)
  5. Reopen the mic stream and reset the model buffer

Single-input-stream contract: the listener closes its stream before STT records.
Both paths use the system default input device.

Config keys (voice.wake_word.*):
  enabled          bool  - master switch
  phrase           str   - built-in model name (ignored when model_path is set)
                          valid: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"
  model_path       str   - path to a custom .onnx model (optional)
  threshold        float - detection score cutoff, 0..1 (default 0.5)
  cooldown_seconds float - ignore re-triggers within this window after detection

Required pip packages: openwakeword onnxruntime sounddevice soxr numpy
No account or API key required.
"""

import threading
import time
import typing

_FRAME_SIZE = 1280  # 80 ms at 16 kHz


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
        self._thread: typing.Optional[threading.Thread] = None
        self._enabled = False

        try:
            self._enabled = self._init_engine()
        except Exception as e:
            print(f"[wakeword] disabled — init failed: {e}")

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
            print(
                "[wakeword] disabled — openwakeword not installed (pip install -r requirements/wakeword.txt)"
            )
            return False

        try:
            import sounddevice  # noqa: F401
        except ImportError:
            print(
                "[wakeword] disabled — sounddevice not installed (pip install -r requirements/wakeword.txt)"
            )
            return False

        try:
            import numpy  # noqa: F401
        except ImportError:
            print(
                "[wakeword] disabled — numpy not installed (pip install -r requirements/wakeword.txt)"
            )
            return False

        # Download pre-trained weights on first run (no-op if already present)
        try:
            import openwakeword

            openwakeword.utils.download_models()
        except Exception as e:
            print(
                f"[wakeword] model download failed (offline?): {e} — continuing with cached models"
            )

        model_path = cfg.get("model_path") or None
        phrase = cfg.get("phrase", "hey jarvis")
        self._threshold = float(cfg.get("threshold", 0.5))
        self._cooldown = float(cfg.get("cooldown_seconds", 2.0))
        self._last_trigger = 0.0

        # Silero VAD pre-gate cuts false triggers from non-speech noise.
        vad_threshold = float(cfg.get("vad_threshold", 0.5))
        # Speex noise suppression helps in noisy/far-field rooms, but the
        # speexdsp-ns package is effectively Linux-only — guarded below.
        noise_suppression = bool(cfg.get("noise_suppression", False))
        models = [model_path] if model_path else [phrase]

        try:
            from openwakeword.model import Model

            kwargs: dict = {
                "wakeword_models": models,
                "inference_framework": "onnx",
                "vad_threshold": vad_threshold,
            }
            if noise_suppression:
                kwargs["enable_speex_noise_suppression"] = True
            try:
                self._oww = Model(**kwargs)
            except Exception as inner:
                # Retry without speex NS (unavailable on this platform) and/or
                # without newer kwargs (older openwakeword).
                if noise_suppression:
                    print(
                        f"[wakeword] noise suppression unavailable ({inner}) — "
                        "continuing without it"
                    )
                kwargs.pop("enable_speex_noise_suppression", None)
                try:
                    self._oww = Model(**kwargs)
                except TypeError:
                    self._oww = Model(
                        wakeword_models=models, inference_framework="onnx"
                    )
        except Exception as e:
            print(f"[wakeword] disabled — openWakeWord init failed: {e}")
            print(
                f"[wakeword] hint: phrase '{phrase}' may not be a valid built-in name. "
                'Valid built-in phrases: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"'
            )
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

        print(f"[wakeword] ready — listening for '{phrase}' (key: {self._model_key})")
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

    def pause(self) -> None:
        """Release mic so another caller can open it. Blocks until stream is closed."""
        if not self._enabled:
            return
        self._paused.set()
        time.sleep(0.15)  # give _run loop one iteration to close the stream

    def resume(self) -> None:
        """Let the listener reopen the mic stream."""
        self._paused.clear()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _open_stream(self, native_rate: int, native_block: int) -> typing.Any:
        import sounddevice as sd

        stream = sd.InputStream(
            samplerate=native_rate,
            channels=1,
            dtype="float32",
            blocksize=native_block,
        )
        stream.start()
        return stream

    def _run(self) -> None:
        try:
            import numpy as np

            from helpers import mic
        except ImportError:
            return

        native_rate = mic.default_input_rate()
        # native block size that yields _FRAME_SIZE samples after resampling to 16k
        native_block = int(round(native_rate * _FRAME_SIZE / 16000))

        stream = None
        try:
            stream = self._open_stream(native_rate, native_block)
            while not self._stop_event.is_set():
                # Pause: close stream and wait until resumed
                if self._paused.is_set():
                    if stream is not None:
                        try:
                            stream.stop()
                            stream.close()
                        except Exception:
                            pass
                        stream = None
                    time.sleep(0.05)
                    continue

                if stream is None:
                    try:
                        stream = self._open_stream(native_rate, native_block)
                    except Exception as e:
                        print(f"[wakeword] failed to reopen mic after pause: {e}")
                        time.sleep(0.5)
                        continue

                try:
                    data, _overflowed = stream.read(native_block)
                except Exception as e:
                    print(f"[wakeword] stream read failed: {e} — reopening")
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                    time.sleep(0.3)
                    continue

                mono = data[:, 0]
                frame16 = mic.to_16k_mono_f32(mono, native_rate)
                pcm16 = np.clip(frame16 * 32768.0, -32768, 32767).astype(np.int16)
                scores = self._oww.predict(pcm16)

                # Pick score for our target model key
                score = scores.get(self._model_key)
                if score is None:
                    score = max(scores.values()) if scores else 0.0

                if score >= self._threshold:
                    now = time.monotonic()
                    if now - self._last_trigger < self._cooldown:
                        continue
                    self._last_trigger = now

                    # Release mic so STT can record
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    stream = None

                    try:
                        self._handle_detection()
                    finally:
                        if not self._stop_event.is_set():
                            try:
                                self._oww.reset()
                            except Exception:
                                pass
                            try:
                                stream = self._open_stream(native_rate, native_block)
                            except Exception as e:
                                print(f"[wakeword] failed to reopen mic: {e}")
                                break

        except Exception as e:
            print(f"[wakeword] listener error: {e}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _handle_detection(self) -> None:
        from helpers.audio import Audio
        from helpers.ducking import duck_others

        with duck_others():
            Audio.play_cached("Yes?")  # non-blocking WAV if rendered, else live TTS

            from helpers.recognizer import Recognizer

            text = Recognizer.recognize_speech_from_mic()
            if not text:
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
                print(f"[wakeword] utterance error: {e}")
