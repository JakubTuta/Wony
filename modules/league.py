import os
import time

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.controllers import MouseController
from helpers.jobs import BackgroundJobs
from helpers.registry import register_job
from helpers.requirements import Requirement
from helpers.screenReader import ScreenReader

_LEAGUE_REQ = Requirement(
    pip_modules=["pynput", "mss"],
    setup_hint="pip install -r requirements/automation.txt",
)

_LEAGUE_LNK = "C:/Users/Public/Desktop/League of Legends.lnk"
_ACCEPT_JOB = "league_accept"
_MAX_ACCEPT_MINUTES = 30


@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Auto-accept LoL queue")
def accept_game() -> str:
    """
    [GAME AUTOMATION JOB] Monitors the screen for a League of Legends queue pop-up and clicks Accept.
    Runs in the background; stops automatically once accepted or after 30 minutes.

    Use this job when the user wants to:
    - Automatically accept League of Legends matches
    - Avoid missing queue pop-ups while multitasking
    - Enable hands-free match acceptance

    Keywords: league, lol, queue, accept match, accept game, queue pop, ready check, auto accept,
             league of legends, automatic accept, match found, game ready, auto queue

    Args:
        None

    Returns:
        str: Confirmation that monitoring started.
    """
    if BackgroundJobs.is_running(_ACCEPT_JOB):
        return "Already watching for queue pop-up."

    audio = Cache.get_audio()

    def _watch():
        mouse_controller = MouseController()
        deadline = time.time() + _MAX_ACCEPT_MINUTES * 60
        while time.time() < deadline:
            screenshot = ScreenReader.take_screenshot(gray=True, target="main")
            accept_object = ScreenReader.find_text_in_screenshot(screenshot, "Accept!")
            if accept_object is not None:
                mouse_controller.go_to_center_of_bbox(accept_object)
                mouse_controller.click_left_button()
                msg = "Game accepted."
                if audio:
                    Audio.text_to_speech(msg)
                print(msg)
                BackgroundJobs.stop(_ACCEPT_JOB)
                return
            time.sleep(5)
        print(f"accept_game: no queue pop-up found after {_MAX_ACCEPT_MINUTES} minutes, stopping.")
        BackgroundJobs.stop(_ACCEPT_JOB)

    BackgroundJobs.start(_ACCEPT_JOB, _watch)
    msg = "Watching for queue pop-up (auto-stops after 30 min or when accepted)."
    if audio:
        Audio.text_to_speech(msg)
    print(msg)
    return msg


@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Launch League of Legends")
def queue_up() -> str:
    """
    [APPLICATION LAUNCHER JOB] Launches the League of Legends game client.

    Use this job when the user wants to:
    - Start playing League of Legends
    - Launch the game client
    - Open the League application

    Keywords: queue up, run game, start league, open league, launch lol, play league,
             start lol, run league, start game, launch league of legends, open lol

    Args:
        None

    Returns:
        str: Success or error message.
    """
    audio = Cache.get_audio()

    if not os.path.exists(_LEAGUE_LNK):
        msg = (
            f"League of Legends shortcut not found at {_LEAGUE_LNK}. "
            "Create a desktop shortcut or update the path in modules/league.py."
        )
        print(msg)
        return msg

    if audio:
        Audio.text_to_speech("Launching League of Legends...")
    print("Launching League of Legends...")
    os.startfile(_LEAGUE_LNK)
    return "League of Legends launched."


@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Close League of Legends")
def close_game() -> str:
    """
    [APPLICATION TERMINATION JOB] Forcefully closes the League of Legends client.

    Use this job when the user wants to:
    - Exit League of Legends completely
    - End their gaming session
    - Close the game client

    Keywords: exit league, quit league, terminate lol, close lol, shut down league, stop league,
             exit game, close game, end league, quit lol, stop playing, close league of legends

    Args:
        None

    Returns:
        str: Confirmation message.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Closing League of Legends...")
    print("Closing League of Legends...")
    os.system("taskkill /f /im LeagueClientUx.exe")
    return "Sent close signal to League of Legends."
