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
    setup_hint="Run install.bat again and tick League of Legends.",
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


@register_job(
    module_name="league",
    requires=_LEAGUE_REQ,
    summary="Launch, close or auto-accept LoL",
    confirms={"close", "quit", "exit"},
)
@capture_response
def league(action: typing.Literal["launch", "close", "auto_accept"] = "launch") -> str:
    """
    [LEAGUE OF LEGENDS JOB] Starts the League of Legends client, closes it, or watches
    the screen for a queue pop-up and clicks Accept for you. Watching runs in the
    background and stops on its own once a game is accepted or after 30 minutes.

    Args:
        action (str): "launch" (the default), "close" or "auto_accept".

    Returns:
        str: Confirmation of what is happening.
    """
    wanted = (action or "launch").strip().lower()
    if wanted in ("launch", "open", "start", "queue_up"):
        return _launch()
    if wanted in ("close", "quit", "exit"):
        return _close()
    if wanted in ("auto_accept", "accept", "watch"):
        return _auto_accept()
    return f"Unknown action '{action}'. Use launch, close or auto_accept."


def _auto_accept() -> str:
    if BackgroundJobs.is_running(_ACCEPT_JOB):
        return "Already watching for queue pop-up."

    # Shares ScreenReader's matching with desktop.click but not the job:
    # click is gated on modules.desktop.allow_actions, and enabling the
    # league module is already the user asking for this one click. Routing
    # through it would break auto-accept for anyone who never wanted general
    # desktop control.
    def _watch():
        mouse_controller = MouseController()
        deadline = time.time() + _MAX_ACCEPT_MINUTES * 60
        while time.time() < deadline:
            try:
                screenshot = ScreenReader.take_screenshot(gray=True, target="main")
                accept_object = ScreenReader.find_text_in_screenshot(screenshot, "Accept!")
            except Exception as e:
                # This runs on a background thread, so an unhandled error here
                # just ends the watch with the user still expecting it to fire.
                # The usual cause is no OCR backend: a provider without vision
                # falls through to easyocr, which may not be installed.
                logger.log_error(str(e), "league.auto_accept")
                notify(f"Stopped watching for the queue pop-up: {e}", kind="error", source="league")
                BackgroundJobs.stop(_ACCEPT_JOB)
                return
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
        notify(
            f"No queue pop-up found after {_MAX_ACCEPT_MINUTES} minutes — no longer watching.",
            kind="info",
            source="league",
        )
        BackgroundJobs.stop(_ACCEPT_JOB)

    BackgroundJobs.start(_ACCEPT_JOB, _watch)
    return "Watching for queue pop-up (auto-stops after 30 min or when accepted)."


def _launch() -> str:
    launcher = _find_league()
    if launcher is None:
        return (
            "Couldn't find League of Legends on this computer. Make a desktop "
            "shortcut for it and try again."
        )
    os.startfile(launcher)
    return "League of Legends launched."


def _close() -> str:
    os.system("taskkill /f /im LeagueClientUx.exe")
    return "Sent close signal to League of Legends."
