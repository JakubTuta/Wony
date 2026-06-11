import importlib.util
import typing

from helpers.registry import ModuleStatus, ServiceRegistry


def _status_lines() -> typing.Tuple[typing.List[str], typing.List[str]]:
    """Return (ready_names, problem_lines) for all registered modules."""
    statuses = ServiceRegistry.get_module_status()
    hints = ServiceRegistry.get_module_hints()

    ready: typing.List[str] = []
    problems: typing.List[str] = []

    for name, (state, reason) in sorted(statuses.items()):
        if state == ModuleStatus.ENABLED:
            ready.append(name)
        else:
            hint = hints.get(name, "")
            line = f"  ✗ {name} ({state})"
            if reason:
                line += f" — {reason}"
            if hint:
                line += f"\n    Fix: {hint}"
            problems.append(line)

    return ready, problems


def print_startup_summary(voice_mode: bool = False) -> None:
    """Print a brief health summary to stdout at startup."""
    from helpers.model import describe_readiness

    ready, problems = _status_lines()

    ai_ok, ai_msg = describe_readiness()
    if ai_ok:
        print(f"  ✓ AI: {ai_msg}")
    else:
        print(f"  ✗ AI: {ai_msg}")
        try:
            from helpers.diagnostics import add as diag
            diag("error", "AI", ai_msg, hint="Check .env for ANTHROPIC_API_KEY / GEMINI_API_KEY, or set ai.provider: ollama in config.yaml.")
        except Exception:
            pass

    if ready:
        print(f"  ✓ Modules ready: {', '.join(ready)}")

    if problems:
        print("  Modules with issues:")
        for line in problems:
            print(line)
        try:
            from helpers.diagnostics import add as diag
            for line in problems:
                msg = line.lstrip().lstrip("✗ ").split("\n")[0].strip()
                if msg:
                    diag("warning", "Module", msg)
        except Exception:
            pass

    if voice_mode:
        missing_voice = _check_voice_deps()
        if missing_voice:
            print(f"  ✗ Voice: missing pip packages: {', '.join(missing_voice)}")
            print("    Fix: pip install -r requirements/voice.txt")
            try:
                from helpers.diagnostics import add as diag
                diag(
                    "error",
                    "Voice",
                    f"Missing pip packages: {', '.join(missing_voice)}",
                    hint="Run: pip install -r requirements/voice.txt",
                )
            except Exception:
                pass
        else:
            print("  ✓ Voice: dependencies present.")

    print("  Type 'help' for commands, 'check setup' for full diagnostics.")


def _check_voice_deps() -> typing.List[str]:
    required = ["kokoro_onnx", "espeakng_loader", "sounddevice", "soundfile", "soxr", "faster_whisper", "pynput"]
    return [m for m in required if importlib.util.find_spec(m) is None]
