import os
import time
import typing

from helpers.notify import notify
from helpers.controllers import MouseController
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement
from helpers.screenReader import ScreenReader

_LEAGUE_REQ = Requirement(
    pip_modules=["pynput", "mss"],
    setup_hint="pip install -r requirements/automation.txt",
)

_ACCEPT_JOB = "league_accept"
_MAX_ACCEPT_MINUTES = 30
# Where Riot's installer actually puts things, in the order worth trying. Drive
# letters are filled in from the drives this machine has, since a second SSD is
# the normal place for a game this size.
_SHORTCUT_DIRS = (
    os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
)
_INSTALL_SUBPATHS = (
    r"Riot Games\League of Legends\LeagueClient.exe",
    r"Games\Riot Games\League of Legends\LeagueClient.exe",
    r"Program Files\Riot Games\League of Legends\LeagueClient.exe",
    r"Riot Games\Riot Client\RiotClientServices.exe",
)


def _find_league() -> typing.Optional[str]:
    """The League launcher on this machine, or None.

    Hardcoding one path meant the job only ever worked on the machine it was
    written on — this checks the shortcuts Riot creates and then every drive.
    """
    for directory in _SHORTCUT_DIRS:
        if not directory:
            continue
        candidate = os.path.join(directory, "League of Legends.lnk")
        if os.path.isfile(candidate):
            return candidate

    for drive in _drives():
        for subpath in _INSTALL_SUBPATHS:
            candidate = os.path.join(drive, subpath)
            if os.path.isfile(candidate):
                return candidate
    return None


def _drives() -> typing.List[str]:
    if os.name != "nt":
        return ["/"]
    return [f"{letter}:\\" for letter in "CDEFGH" if os.path.isdir(f"{letter}:\\")]


@capture_response
@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Auto-accept LoL queue")
def accept_game() -> str:
    """
    [GAME AUTOMATION JOB] Monitors the screen for a League of Legends queue pop-up and clicks Accept.
    Runs in the background; stops automatically once accepted or after 30 minutes.

    Returns:
        str: Confirmation that monitoring started.
    """
    if BackgroundJobs.is_running(_ACCEPT_JOB):
        return "Already watching for queue pop-up."

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
                notify(msg, kind="info", source="league")
                logger.log_system_event("league_accept", msg)
                BackgroundJobs.stop(_ACCEPT_JOB)
                return
            time.sleep(5)
        logger.log_system_event("league_accept", f"No queue pop-up found after {_MAX_ACCEPT_MINUTES} minutes.")
        BackgroundJobs.stop(_ACCEPT_JOB)

    BackgroundJobs.start(_ACCEPT_JOB, _watch)
    return "Watching for queue pop-up (auto-stops after 30 min or when accepted)."


@capture_response
@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Launch League of Legends")
def queue_up() -> str:
    """
    [APPLICATION LAUNCHER JOB] Launches the League of Legends game client.

    Returns:
        str: Success or error message.
    """
    launcher = _find_league()
    if launcher is None:
        return (
            "Couldn't find League of Legends on this computer. Make a desktop "
            "shortcut for it and try again."
        )
    os.startfile(launcher)
    return "League of Legends launched."


@capture_response
@register_job(module_name="league", requires=_LEAGUE_REQ, summary="Close League of Legends")
def close_game() -> str:
    """
    [APPLICATION TERMINATION JOB] Forcefully closes the League of Legends client.

    Returns:
        str: Confirmation message.
    """
    os.system("taskkill /f /im LeagueClientUx.exe")
    return "Sent close signal to League of Legends."
