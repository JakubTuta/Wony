import importlib.util
import os

from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement, evaluate


def run_doctor(voice_mode: bool = False) -> str:
    """Run all setup checks and return a formatted report."""
    from helpers.model import describe_readiness

    lines = ["Setup diagnostics:"]

    # .env file
    if os.path.exists(".env"):
        lines.append("  ✓ .env file found.")
    else:
        lines.append("  ✗ .env file missing — create it in the project root.")
        lines.append("    Add at least one of: ANTHROPIC_API_KEY, GEMINI_API_KEY")

    # config.yaml vs example
    if os.path.exists("config.yaml"):
        lines.append("  ✓ config.yaml found.")
    else:
        lines.append(
            "  ! config.yaml missing — using config.example.yaml defaults.\n"
            "    Copy it: Copy-Item config.example.yaml config.yaml"
        )

    # AI readiness
    ai_ok, ai_msg = describe_readiness()
    prefix = "✓" if ai_ok else "✗"
    lines.append(f"  {prefix} AI: {ai_msg}")

    # Per-module checks
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

    if voice_mode:
        lines.extend(_audio_selftest())

    return "\n".join(lines)


def _audio_selftest() -> list:
    lines = ["\n  Audio self-test:"]
    try:
        import numpy as np
        import sounddevice as sd
        from helpers import mic
    except Exception as e:
        lines.append(f"  ✗ Audio self-test unavailable: {e}")
        return lines

    # Show resolved default devices
    try:
        in_idx = sd.default.device[0]
        out_idx = sd.default.device[1]
        in_info = sd.query_devices(in_idx, "input")
        out_info = sd.query_devices(out_idx, "output")
        lines.append(f"    Default input : [{in_idx}] {in_info['name']}  ({int(in_info['default_samplerate'])} Hz)")
        lines.append(f"    Default output: [{out_idx}] {out_info['name']}")
    except Exception as e:
        lines.append(f"  ✗ Could not query devices: {e}")
        return lines

    # Output test
    try:
        mic.play_wav("voice/bot/ready.wav", blocking=True)
        lines.append("    ✓ Output test — did you hear the ready sound?")
    except Exception as e:
        lines.append(f"    ✗ Output test failed: {e}")

    # Input test (2s recording + RMS level)
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
