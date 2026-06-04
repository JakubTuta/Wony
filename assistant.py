import argparse
import os
import time
import typing

from helpers.cache import Cache
from helpers.config import Config
from helpers.logger import logger


def get_config() -> typing.Dict[str, typing.Any]:
    """
    Parses command-line arguments and environment variables to configure the application.
    Defaults come from config.yaml; CLI flags and env vars take precedence.
    """
    Config._ensure_loaded()

    parser = argparse.ArgumentParser(description="AI Assistant")
    parser.add_argument(
        "--audio",
        "-a",
        action="store_true",
        help="Use audio input/output",
    )
    parser.add_argument(
        "--local",
        "-l",
        action="store_true",
        help="Use local AI model with Ollama instead of remote API",
    )
    parser.add_argument(
        "--doctor",
        "-d",
        action="store_true",
        help="Run setup diagnostics and exit",
    )
    args = parser.parse_args()

    config = {
        "audio": args.audio or Config.get("voice.enabled", False),
        "local": args.local or (Config.get("ai.provider") == "ollama"),
        "doctor": args.doctor,
    }

    # Environment variables override config and CLI args
    config["audio"] = os.environ.get("AI_ASSISTANT_AUDIO", config["audio"])
    config["local"] = os.environ.get("AI_ASSISTANT_LOCAL", config["local"])

    for key in ["audio", "local"]:
        if isinstance(config[key], str):
            config[key] = config[key].lower() in ("true", "1", "t")

    return config


def speech_to_text(employer) -> None:
    """Handles speech-to-text input loop."""
    import keyboard
    from helpers.audio import Audio

    Audio.play_audio_from_file("voice/bot/ready.wav")
    print("\nListening for key combination (Ctrl + L)...")
    keyboard.add_hotkey(
        hotkey="ctrl+l",
        callback=employer.speak,
    )
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nExiting program...")
            break


def text_to_text(employer) -> None:
    """Handles text-based input loop."""
    print("Listening for text input...")
    while True:
        try:
            user_input = input("\nEnter a command: ")
            logger.log_user_input(user_input, "text")
            employer.job_on_command(user_input)
        except KeyboardInterrupt:
            logger.log_system_event(
                "application_shutdown", "User interrupted with Ctrl+C"
            )
            print("\nExiting program...")
            break


def main() -> None:
    """Main function to run the AI assistant."""
    print("\nStarting program...")

    # Config must load BEFORE modules are imported (module decorators read it at registration time)
    Config.load()

    config = get_config()

    # --doctor: run diagnostics and exit without starting the assistant
    if config.get("doctor"):
        Cache.load_values()
        Cache.set_audio(config["audio"])
        Cache.set_local(config["local"])
        from modules.doctor import run_doctor
        print(run_doctor(voice_mode=bool(config["audio"])))
        return

    logger.log_system_event("application_startup", "AI Assistant starting up")
    logger.log_system_event("configuration_loaded", f"Config: {config}")

    Cache.load_values()
    Cache.set_audio(config["audio"])
    Cache.set_local(config["local"])

    # Load .env before any module imports so env vars are available for preflight
    import dotenv
    dotenv.load_dotenv()

    # Preflight: verify AI provider is configured before loading all modules
    from helpers.model import describe_readiness
    ai_ok, ai_msg = describe_readiness()
    if not ai_ok:
        print(f"\nCannot start: AI provider not ready.\n{ai_msg}\n")
        return

    # Import Employer here (after Config.load) so discover_services() runs with config ready
    from modules.employer import Employer

    employer = Employer()
    logger.log_system_event("employer_initialized", "Employer instance created")

    # Print startup health summary after modules are loaded
    print()
    from helpers.health import print_startup_summary
    print_startup_summary(voice_mode=bool(config["audio"]))
    print()

    if config["audio"]:
        logger.log_system_event("mode_selected", "Speech-to-text mode enabled")
        speech_to_text(employer)
    else:
        logger.log_system_event("mode_selected", "Text-to-text mode enabled")
        text_to_text(employer)


if __name__ == "__main__":
    main()
