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
                files=["credentials/gmail_credentials.json"],
                pip_modules=["simplegmail"],
                setup_hint="Follow simplegmail setup (pypi.org/project/simplegmail), place "
                           "credentials/gmail_credentials.json, pip install -r requirements/gmail.txt",
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
                    pip_modules=["pyttsx3", "speech_recognition", "pyaudio", "faster_whisper", "keyboard"],
                    setup_hint="pip install -r requirements/voice.txt",
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

    return "\n".join(lines)


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
