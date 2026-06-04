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

    if ready:
        print(f"  ✓ Modules ready: {', '.join(ready)}")

    if problems:
        print("  Modules with issues:")
        for line in problems:
            print(line)

    ai_ok, ai_msg = describe_readiness()
    if ai_ok:
        print(f"  ✓ AI: {ai_msg}")
    else:
        print(f"  ✗ AI: {ai_msg}")

    if voice_mode:
        missing_voice = _check_voice_deps()
        if missing_voice:
            print(f"  ✗ Voice: missing pip packages: {', '.join(missing_voice)}")
            print("    Fix: pip install -r requirements/voice.txt")
        else:
            print("  ✓ Voice: dependencies present.")

    print("  Type 'help' for commands, 'check setup' for full diagnostics.")


def _check_voice_deps() -> typing.List[str]:
    import importlib.util

    required = ["pyttsx3", "speech_recognition", "pyaudio", "faster_whisper", "keyboard"]
    return [m for m in required if importlib.util.find_spec(m) is None]
