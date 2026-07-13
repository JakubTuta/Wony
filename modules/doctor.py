import os

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement, evaluate


def run_doctor(voice_mode: bool = False) -> str:
    """Run all setup checks and return a formatted report."""
    from helpers.model import describe_readiness

    lines = ["Setup diagnostics:"]

    if os.path.exists(".env"):
        lines.append("  ✓ .env file found.")
    else:
        lines.append("  ✗ .env file missing — create it in the project root.")
        lines.append("    Add at least one of: ANTHROPIC_API_KEY, GEMINI_API_KEY")

    if os.path.exists("config.yaml"):
        lines.append("  ✓ config.yaml found.")
    else:
        lines.append(
            "  ! config.yaml missing — using config.example.yaml defaults.\n"
            "    Copy it: Copy-Item config.example.yaml config.yaml"
        )

    ai_ok, ai_msg = describe_readiness()
    prefix = "✓" if ai_ok else "✗"
    lines.append(f"  {prefix} AI: {ai_msg}")

    module_checks = [
        (
            "Weather",
            Requirement(
                env_vars=["WEATHER_API_KEY"],
                pip_modules=["geocoder", "requests"],
                setup_hint="Add WEATHER_API_KEY to .env (free key: openweathermap.org/api). "
                "pip install -r requirements/weather.txt",
            ),
        ),
        (
            "Spotify",
            Requirement(
                env_vars=["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
                pip_modules=["requests"],
                setup_hint="Create app at developer.spotify.com, add SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET to .env, set redirect URI http://127.0.0.1:8888/callback",
            ),
        ),
        (
            "Gmail",
            Requirement(
                files=["credentials/google_credentials.json"],
                pip_modules=["simplegmail"],
                setup_hint="Follow simplegmail OAuth setup (pypi.org/project/simplegmail), "
                "place credentials/google_credentials.json in the credentials/ folder, "
                "then run: pip install -r requirements/gmail.txt",
            ),
        ),
        (
            "Calendar",
            Requirement(
                files=["credentials/google_credentials.json"],
                pip_modules=["googleapiclient", "google_auth_oauthlib", "google.auth"],
                setup_hint="Create an OAuth client (Desktop) in Google Cloud Console with "
                "Calendar API and Gmail API enabled, download it to "
                "credentials/google_credentials.json, "
                "then run: pip install -r requirements/calendar.txt",
            ),
        ),
        (
            "Web search",
            Requirement(
                pip_modules=["duckduckgo_search"],
                setup_hint="pip install -r requirements/web.txt  "
                "(optional: add TAVILY_API_KEY to .env for higher-quality results)",
            ),
        ),
        (
            "Scheduler",
            Requirement(
                pip_modules=["apscheduler", "dateparser"],
                setup_hint="pip install -r requirements/scheduler.txt",
            ),
        ),
        (
            "Desktop automation",
            Requirement(
                pip_modules=["pyautogui", "pygetwindow", "pyperclip"],
                setup_hint="pip install -r requirements/desktop.txt  "
                "Then set modules.desktop.allow_actions: true in config.yaml to enable actions.",
            ),
        ),
        (
            "Screen/OCR",
            Requirement(
                pip_modules=["mss", "easyocr"],
                setup_hint="pip install -r requirements/screen.txt",
            ),
        ),
        (
            "League / automation",
            Requirement(
                pip_modules=["pynput", "mss"],
                setup_hint="pip install -r requirements/automation.txt",
            ),
        ),
        (
            "Shelly",
            Requirement(
                pip_modules=["requests"],
                setup_hint="Set modules.shelly.base_url in config.yaml to your device IP.",
            ),
        ),
        (
            "Shazam",
            Requirement(
                pip_modules=["shazamio", "pyaudiowpatch", "soundfile"],
                setup_hint="pip install -r requirements/shazam.txt",
            ),
        ),
        (
            "MCP client",
            Requirement(
                pip_modules=["mcp"],
                setup_hint="pip install -r requirements/mcp.txt",
            ),
        ),
        (
            "Semantic memory",
            Requirement(
                pip_modules=["fastembed"],
                setup_hint="pip install -r requirements/semantic.txt",
            ),
        ),
    ]

    if voice_mode:
        module_checks.append(
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
            )
        )
        module_checks.append(
            (
                "Wake word",
                Requirement(
                    pip_modules=["openwakeword", "onnxruntime", "sounddevice", "soxr", "numpy"],
                    setup_hint="pip install -r requirements/wakeword.txt  "
                    "Enable with voice.wake_word.enabled: true in config.yaml  "
                    "Built-in phrases: \"hey jarvis\", \"alexa\", \"hey mycroft\", \"hey rhasspy\"",
                ),
            )
        )

    for label, req in module_checks:
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
        lines.append(f"    Default input : [{in_idx}] {in_info['name']}  ({int(in_info['default_samplerate'])} Hz)")
        resolved_idx = mic.resolve_input_device()
        if resolved_idx != in_idx:
            resolved_info = sd.query_devices(resolved_idx, "input")
            lines.append(f"    Capture input : [{resolved_idx}] {resolved_info['name']}  ({int(resolved_info['default_samplerate'])} Hz)  (virtual default bypassed)")
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
            ha_name = hostapis[dev["hostapi"]]["name"] if dev["hostapi"] < len(hostapis) else "?"
            marker = "→ " if idx == resolved_idx else "  "
            if mic.device_is_excluded(dev["name"], all_devs):
                lines.append(f"    {marker}[{idx:2d}] EXCLUDED  ({ha_name}) {dev['name']}")
                continue
            ok, detail = mic.probe_input_device(idx, seconds=0.25, deadline=1.0)
            status = "OK      " if ok else "DEAD    "
            lines.append(f"    {marker}[{idx:2d}] {status}({ha_name}) {dev['name']}  — {detail}")
    except Exception as e:
        lines.append(f"    ✗ Device matrix failed: {e}")

    try:
        from helpers.ducking import duck_others
        with duck_others():
            mic.play_wav("voice/bot/ready.wav", blocking=True)
        lines.append("\n    ✓ Output test — did you hear the ready sound?")
    except Exception as e:
        lines.append(f"    ✗ Output test failed: {e}")

    try:
        from helpers import audio as _audio

        out_idx = mic.resolve_output_device()
        out_name = "(OS default)" if out_idx is None else sd.query_devices(out_idx, "output")["name"]
        endpoint_id = mic._get_default_render_endpoint_id()
        lane_free = _audio._playback_lane.acquire(blocking=False)
        if lane_free:
            _audio._playback_lane.release()
        lines.append(f"    ✓ Output device — resolved: [{out_idx if out_idx is not None else 'default'}] {out_name}")
        lines.append(f"    ✓ Default render endpoint ID: {endpoint_id or '(unavailable)'}")
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
        import json as _json
        import time as _time

        from helpers.ducking import (
            _PENDING_RECOVERY_PATH,
            _SNAPSHOT_PATH,
            duck_others,
            recover_stale_snapshot,
        )

        with duck_others():
            # Give the worker thread a moment to process "duck" and (if any
            # foreign sessions exist) write the crash-recovery snapshot.
            _time.sleep(0.5)
            snapshot_seen = os.path.exists(_SNAPSHOT_PATH)
        _time.sleep(1.2)  # let the restore fade + snapshot delete complete
        snapshot_cleared = not os.path.exists(_SNAPSHOT_PATH)
        lines.append(
            f"    ✓ Ducking snapshot lifecycle — wrote: {snapshot_seen or '(no foreign sessions playing)'}, "
            f"cleared after restore: {snapshot_cleared}"
        )

        # Synthetic crash-recovery test 1: a stale (>24h old) record for a
        # nonexistent PID should be discarded outright, without raising.
        with open(_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            _json.dump(
                {
                    "version": 1,
                    "pid": 999999,
                    "duck_level": 0.15,
                    "created_epoch": 0,  # 1970 — always older than the 24h cutoff
                    "sessions": [{"pid": 999999, "name": "nonexistent.exe", "volume": 0.8}],
                },
                f,
            )
        recover_stale_snapshot()
        _time.sleep(0.3)
        stale_discarded = not os.path.exists(_SNAPSHOT_PATH) and not os.path.exists(_PENDING_RECOVERY_PATH)
        lines.append(f"    ✓ Ducking crash-recovery test (stale >24h) — discarded: {stale_discarded}")

        # Synthetic crash-recovery test 2: a RECENT record for a nonexistent
        # PID should move to the pending-recovery file (retried later) rather
        # than being lost — this is the safety-net path a user hits if their
        # app wasn't running yet when recovery ran.
        with open(_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            _json.dump(
                {
                    "version": 1,
                    "pid": 999998,
                    "duck_level": 0.15,
                    "created_epoch": _time.time(),
                    "sessions": [{"pid": 999998, "name": "nonexistent2.exe", "volume": 0.8}],
                },
                f,
            )
        recover_stale_snapshot()
        _time.sleep(0.3)
        moved_to_pending = not os.path.exists(_SNAPSHOT_PATH) and os.path.exists(_PENDING_RECOVERY_PATH)
        lines.append(f"    ✓ Ducking crash-recovery test (recent, app absent) — moved to pending-recovery: {moved_to_pending}")

        # Clean up the synthetic pending-recovery entry so it doesn't linger
        # and get retried by the real safety sweep.
        if os.path.exists(_PENDING_RECOVERY_PATH):
            os.remove(_PENDING_RECOVERY_PATH)
    except Exception as e:
        lines.append(f"    ✗ Ducking self-test failed: {e}")

    try:
        lines.append("    Recording 2s from mic...")
        sig = mic.record_16k(2)
        rms = float(np.sqrt(np.mean(sig ** 2)))
        bar = "#" * min(40, int(rms * 400))
        lines.append(f"    ✓ Input RMS {rms:.4f} |{bar}|")
        if rms < 0.001:
            lines.append("    ! Near-silent — mic may be muted or wrong default input device.")
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
                key = next((k for k in scores if target in k.lower().replace(" ", "_")), next(iter(scores)))
            if key is not None:
                peak = max(peak, float(scores.get(key, 0.0)))

        status = "✓" if peak >= threshold else "✗"
        lines.append(f"    {status} Synthesized '{text}' → peak score {peak:.3f} (threshold {threshold})")
        if peak < threshold:
            lines.append("      Model/threshold problem — try lowering voice.wake_word.threshold or retraining the model.")
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
