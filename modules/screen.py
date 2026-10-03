import datetime
import os

from PIL import Image

from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, register_job
from helpers.requirements import Requirement
from helpers.screenReader import ScreenReader
from helpers.untrusted import wrap

SCREENSHOTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots"
)


_SCREEN_REQ = Requirement(
    pip_modules=["mss"],
    setup_hint="Run install.bat again and tick Screen capture + OCR.",
)


@register_job(module_name="screen", requires=_SCREEN_REQ, summary="Look at the screen")
@capture_response
def look_at_screen(question: str = "", save: bool = False) -> str:
    """
    [SCREEN JOB] Looks at what is on screen right now and answers a question about it —
    what an error says, what is in a picture, what a form is asking for. Sends a picture
    of the screen to the AI provider to answer. Can also keep a copy of the screenshot
    as a file.

    Args:
        question (str): What to answer about the screen. Leave empty just to describe it.
        save (bool): Also write the screenshot to the screenshots folder.

    Returns:
        str: The answer, and the file path when one was saved.
    """
    screenshot = ScreenReader.take_screenshot(target="active")

    saved_note = ""
    if save:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        filename = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S") + ".png"
        file_path = os.path.join(SCREENSHOTS_DIR, filename)
        Image.fromarray(screenshot).save(file_path)
        saved_note = f"\nSaved to {file_path}"

    ai_service = ServiceRegistry.get_service_instance("ai")
    if not ai_service:
        # Still say what happened: a saved file with no answer is a real result.
        return saved_note.strip() or "Error: AI service not available."

    answer = ai_service.explain_screenshot(
        question or "Describe what is on this screen.", screenshot
    )
    return f"{wrap(answer, 'screen')}{saved_note}"
