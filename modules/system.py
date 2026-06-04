import os

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.registry import register_job


@register_job(module_name="system")
def close_computer() -> None:
    """
    [SYSTEM CONTROL JOB] Immediately shuts down the entire computer system.
    This is a critical system operation that forcefully terminates all processes
    and powers off the machine. Use with extreme caution as it will close all applications.

    Use this job when the user wants to:
    - Completely power down the computer
    - Shut down the system via voice command
    - Emergency system shutdown
    - End the computing session entirely

    Keywords: close computer, shut down, power off, turn off, exit, close system, shutdown, power down,
             restart computer, shut down pc, power down system, close everything

    Args:
        None

    Returns:
        None: System will shut down immediately after execution.
    """
    confirmation = input("Shut down the computer? Type 'yes' to confirm: ").strip().lower()
    if confirmation != "yes":
        print("Shutdown cancelled.")
        return

    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Closing computer. o7")
    print("Closing computer. o7")

    os.system("shutdown /s /f /t 0")
