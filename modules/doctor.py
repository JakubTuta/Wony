import os

from helpers.decorators import capture_response
from helpers.paths import repo_path
from helpers.registry import register_job
from helpers.requirements import Requirement, evaluate

_NON_MODULE_CHECKS = [
    (
        "Semantic memory",
        Requirement(
            pip_modules=["fastembed"],
            setup_hint="pip install -r requirements/semantic.txt",
        ),
        False,
    ),
    (
        "Voice (TTS/STT)",
        Requirement(
            pip_modules=[
                "kokoro_onnx",
                "espeakng_loader",
                "sounddevice",
                "soundfile",
                "soxr",
                "faster_whisper",
                "pynput",
            ],
            setup_hint="pip install -r requirements/voice.txt",
        ),
        True,
    ),
    (
        "Wake word",
        Requirement(
            pip_modules=["openwakeword", "onnxruntime", "sounddevice", "soxr", "numpy"],
            setup_hint="pip install -r requirements/wakeword.txt  "
            "Enable with voice.wake_word.enabled: true in config.yaml  "
            'Built-in phrases: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"',
        ),
        True,
    ),
]


def _module_checks(voice_mode: bool) -> list:
    """(label, Requirement) for every module that declared one, plus the
    non-module features. Modules are read from the registry so this never
    drifts from what the modules themselves require."""
    from helpers.registry import ServiceRegistry

    checks = [
        (name, req)
        for name, req in sorted(ServiceRegistry.get_module_requirements().items())
    ]
    checks += [
        (label, req)
        for label, req, needs_voice in _NON_MODULE_CHECKS
        if voice_mode or not needs_voice
    ]
    return checks


def run_doctor(voice_mode: bool = False) -> str:
    """Run all setup checks and return a formatted report."""
    from helpers.model import describe_readiness

    lines = ["Setup diagnostics:"]

    if os.path.exists(repo_path(".env")):
        lines.append("  ✓ .env file found.")
    else:
        lines.append("  ✗ .env file missing — create it in the project root.")
        lines.append("    Add at least one of: ANTHROPIC_API_KEY, GEMINI_API_KEY")

    if os.path.exists(repo_path("config.yaml")):
        lines.append("  ✓ config.yaml found.")
    else:
        lines.append(
            "  ! config.yaml missing — using config.example.yaml defaults.\n"
            "    Copy it: Copy-Item config.example.yaml config.yaml"
        )

    ai_ok, ai_msg = describe_readiness()
    prefix = "✓" if ai_ok else "✗"
    lines.append(f"  {prefix} AI: {ai_msg}")

    for label, req in _module_checks(voice_mode):
        ok, reason = evaluate(req)
        if ok:
            lines.append(f"  ✓ {label}")
        else:
            lines.append(f"  ✗ {label}: {reason}")
            if req.setup_hint:
                lines.append(f"    Fix: {req.setup_hint}")

    lines.extend(_compute_selftest())

    if voice_mode:
        lines.extend(_audio_selftest())
        lines.extend(_wakeword_selftest())

    return "\n".join(lines)


def _compute_selftest() -> list:
    try:
        from helpers.compute import describe_compute

        return describe_compute()
    except Exception as e:
        return [f"\n  Compute devices: unavailable ({e})"]


def _audio_selftest() -> list:
    lines = ["\n  Audio self-test:"]
    try:
        import numpy as np
        import sounddevice as sd

        from helpers import mic
    except Exception as e:
        lines.append(f"  ✗ Audio self-test unavailable: {e}")
        return lines

    try:
        in_idx, out_idx = mic.default_devices()
        in_info = sd.query_devices(in_idx, "input")
        out_info = sd.query_devices(out_idx, "output")
        lines.append(
            f"    Default input : [{in_idx}] {in_info['name']}  ({int(in_info['default_samplerate'])} Hz)"
        )
        resolved_idx = mic.resolve_input_device()
        if resolved_idx != in_idx:
            resolved_info = sd.query_devices(resolved_idx, "input")
            lines.append(
                f"    Capture input : [{resolved_idx}] {resolved_info['name']}  ({int(resolved_info['default_samplerate'])} Hz)  (virtual default bypassed)"
            )
        lines.append(f"    Default output: [{out_idx}] {out_info['name']}")
    except Exception as e:
        lines.append(f"  ✗ Could not query devices: {e}")
        return lines

    lines.append("\n    Input device matrix (→ marks the resolved capture device):")
    try:
        all_devs = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
        for idx, dev in enumerate(all_devs):
            if dev["max_input_channels"] <= 0:
                continue
            ha_name = (
                hostapis[dev["hostapi"]]["name"]
                if dev["hostapi"] < len(hostapis)
                else "?"
            )
            marker = "→ " if idx == resolved_idx else "  "
            if mic.device_is_excluded(dev["name"], all_devs):
                lines.append(
                    f"    {marker}[{idx:2d}] EXCLUDED  ({ha_name}) {dev['name']}"
                )
                continue
            ok, detail = mic.probe_input_device(idx, seconds=0.25, deadline=1.0)
            status = "OK      " if ok else "DEAD    "
            lines.append(
                f"    {marker}[{idx:2d}] {status}({ha_name}) {dev['name']}  — {detail}"
            )
    except Exception as e:
        lines.append(f"    ✗ Device matrix failed: {e}")

    try:
        from helpers.media_pause import pause_media

        with pause_media():
            mic.play_wav("voice/bot/ready.wav", blocking=True)
        lines.append("\n    ✓ Output test — did you hear the ready sound?")
    except Exception as e:
        lines.append(f"    ✗ Output test failed: {e}")

    try:
        from helpers import audio as _audio

        out_idx = mic.resolve_output_device()
        out_name = (
            "(OS default)"
            if out_idx is None
            else sd.query_devices(out_idx, "output")["name"]
        )
        endpoint_id = mic._get_default_render_endpoint_id()
        lane_free = _audio._playback_lane.acquire(blocking=False)
        if lane_free:
            _audio._playback_lane.release()
        lines.append(
            f"    ✓ Output device — resolved: [{out_idx if out_idx is not None else 'default'}] {out_name}"
        )
        lines.append(
            f"    ✓ Default render endpoint ID: {endpoint_id or '(unavailable)'}"
        )
        lines.append(f"    ✓ Playback lane free: {lane_free}")
    except Exception as e:
        lines.append(f"    ✗ Output device report failed: {e}")

    try:
        from helpers import recognizer as _recognizer
        from helpers.config import Config as _Config

        preload = bool(_Config.get("models.preload", False))
        idle_minutes = _Config.get("models.idle_unload_minutes", 15)
        stt_loaded = _recognizer._model is not None
        tts_loaded = _audio._tts_singleton is not None
        lines.append(
            f"    ✓ Models — preload: {preload}, idle_unload_minutes: {idle_minutes}, "
            f"STT loaded: {stt_loaded}, TTS loaded: {tts_loaded}"
        )
    except Exception as e:
        lines.append(f"    ✗ Models report failed: {e}")

    try:
        import asyncio

        from helpers.media_pause import _IS_WINDOWS

        if not _IS_WINDOWS:
            lines.append(
                "    ! Media-pause — Windows only, skipped (not running on Windows)."
            )
        else:
            try:
                from winrt.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
                )

                backend_available = True
            except ImportError:
                backend_available = False

            if not backend_available:
                lines.append(
                    "    ✗ Media-pause backend (winrt) not installed — media won't be paused automatically."
                )
                lines.append("      pip install -r requirements/voice.txt")
            else:

                async def _list_sessions():
                    mgr = await _SessionManager.request_async()
                    return mgr.get_sessions()

                sessions = asyncio.run(_list_sessions())
                if not sessions:
                    lines.append(
                        "    ✓ Media-pause backend ready — no active media sessions right now."
                    )
                else:
                    lines.append(
                        f"    ✓ Media-pause backend ready — {len(sessions)} active session(s):"
                    )
                    for s in sessions:
                        try:
                            info = s.get_playback_info()
                            pausable = (
                                info.controls is not None
                                and info.controls.is_pause_enabled
                            )
                            lines.append(
                                f"        {s.source_app_user_model_id} — status: {info.playback_status}, "
                                f"pausable: {pausable}"
                            )
                        except Exception as e:
                            lines.append(f"        (session report failed: {e})")
    except Exception as e:
        lines.append(f"    ✗ Media-pause self-test failed: {e}")

    try:
        lines.append("    Recording 2s from mic...")
        sig = mic.record_16k(2)
        rms = float(np.sqrt(np.mean(sig**2)))
        bar = "#" * min(40, int(rms * 400))
        lines.append(f"    ✓ Input RMS {rms:.4f} |{bar}|")
        if rms < 0.001:
            lines.append(
                "    ! Near-silent — mic may be muted or wrong default input device."
            )
    except Exception as e:
        lines.append(f"    ✗ Input test failed: {e}")

    return lines


def _wakeword_selftest() -> list:
    """Synthesize the configured wake phrase and score it against the live
    model, independent of mic capture — isolates model/threshold problems
    from device/lifecycle problems."""
    lines = ["\n  Wake-word self-test:"]
    try:
        from helpers.config import Config

        cfg = Config.get("voice.wake_word", {}) or {}
        if not cfg.get("enabled", False):
            lines.append("    (disabled — voice.wake_word.enabled: false)")
            return lines
    except Exception as e:
        lines.append(f"    ✗ Could not read config: {e}")
        return lines

    try:
        import numpy as np
        import soxr
        from openwakeword.model import Model
    except Exception as e:
        lines.append(f"    (skipped — dependency missing: {e})")
        return lines

    try:
        from helpers.audio import _get_tts_singleton

        engine = _get_tts_singleton()
    except Exception as e:
        lines.append(f"    (skipped — TTS engine unavailable: {e})")
        return lines

    model_path = cfg.get("model_path") or None
    phrase = cfg.get("phrase", "hey jarvis")
    threshold = float(cfg.get("threshold", 0.5))
    if model_path and not os.path.isabs(model_path):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(repo_root, model_path)
    models = [model_path] if model_path else [phrase]

    try:
        oww = Model(wakeword_models=models, inference_framework="onnx")
    except Exception as e:
        lines.append(f"    ✗ Model load failed: {e}")
        return lines

    try:
        say = phrase.replace("_", " ")
        text = say if say.endswith(("!", ".", "?")) else f"{say}!"
        samples, sr = engine.synthesize(text)
        s16 = soxr.resample(samples, sr, 16000)
        lead = np.zeros(16000, dtype=np.float32)
        sig = np.concatenate([lead, s16, lead])
        pad = (-len(sig)) % 1280
        sig = np.pad(sig, (0, pad))

        target = phrase.lower().replace(" ", "_")
        key = None
        peak = 0.0
        for i in range(0, len(sig), 1280):
            frame = sig[i : i + 1280]
            pcm16 = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16)
            scores = oww.predict(pcm16)
            if key is None and scores:
                key = next(
                    (k for k in scores if target in k.lower().replace(" ", "_")),
                    next(iter(scores)),
                )
            if key is not None:
                peak = max(peak, float(scores.get(key, 0.0)))

        status = "✓" if peak >= threshold else "✗"
        lines.append(
            f"    {status} Synthesized '{text}' → peak score {peak:.3f} (threshold {threshold})"
        )
        if peak < threshold:
            lines.append(
                "      Model/threshold problem — try lowering voice.wake_word.threshold or retraining the model."
            )
    except Exception as e:
        lines.append(f"    ✗ Self-test failed: {e}")

    return lines


@register_job
@capture_response
def check_setup() -> str:
    """
    [SYSTEM DIAGNOSTICS JOB] Validates the full assistant setup and prints a ✓/✗ checklist.
    Checks .env, config.yaml, AI provider, and each integration's requirements.
    Prints exactly what to fix for anything that is missing or broken.

    Use this job when the user wants to:
    - Diagnose setup problems
    - See what integrations need configuration
    - Get step-by-step fix instructions
    - Validate the assistant is fully configured

    Keywords: check setup, diagnose, setup, doctor, validate, configuration check,
             what's broken, fix setup, setup status, configuration status

    Args:
        None

    Returns:
        str: Full diagnostics report with ✓/✗ per component and fix instructions.
    """
    from helpers.cache import Cache

    voice_mode = Cache.get_audio()
    return run_doctor(voice_mode=bool(voice_mode))
