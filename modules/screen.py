import datetime
import os

from PIL import Image

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.registry import ServiceRegistry, register_job
from helpers.requirements import Requirement
from helpers.screenReader import ScreenReader

SCREENSHOTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots"
)


_SCREEN_REQ = Requirement(
    pip_modules=["mss"],
    setup_hint="pip install -r requirements/screen.txt",
)


@register_job(module_name="screen", requires=_SCREEN_REQ)
def save_screenshot() -> None:
    """
    [SCREEN CAPTURE JOB] Captures and saves a screenshot of the current active screen to disk.
    This standalone task creates a timestamped image file of whatever is currently displayed
    on the screen and stores it in the screenshots directory for later reference.

    Use this job when the user wants to:
    - Capture what's currently on screen
    - Save visual documentation
    - Create image records of displayed content
    - Take screenshots for sharing or archiving

    Keywords: screenshot, save, screen capture, take picture, capture screen, save image,
             screen shot, take screenshot, capture display

    Args:
        None

    Returns:
        None: Screenshot file saved to screenshots directory with timestamp filename.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Saving a screenshot...")
    print("Saving a screenshot...")

    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    screenshot = ScreenReader.take_screenshot(target="active")

    filename = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S") + ".png"
    file_path = os.path.join(SCREENSHOTS_DIR, filename)

    image = Image.fromarray(screenshot)
    image.save(file_path)


@register_job(module_name="screen", requires=_SCREEN_REQ)
@capture_response
def explain_screenshot(user_input: str) -> str:
    """
    [AI VISION JOB] Captures the current screen and provides AI-powered analysis and explanation.
    This intelligent task takes a screenshot and uses computer vision AI to describe, analyze,
    and explain the visual content based on the user's specific question or request.

    Use this job when the user wants to:
    - Understand what's displayed on screen
    - Get AI analysis of visual content
    - Explain complex interfaces or applications
    - Describe images, text, or UI elements visible on screen
    - Get contextual help about what they're seeing

    Keywords: explain this, what's this, explain, analyze, screenshot, screen capture,
             describe screen, what am I looking at, analyze this, tell me about this,
             screen analysis, visual explanation

    Args:
        user_input (str): The user's specific question or request about the screenshot content.

    Returns:
        str: Detailed AI-generated explanation of the screen content based on user's query.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.text_to_speech("Taking a screenshot and explaining it...")
    print("Taking a screenshot and explaining it...")

    screenshot = ScreenReader.take_screenshot(target="active")

    # Get AI service instance
    ai_service = ServiceRegistry.get_service_instance("ai")
    if not ai_service:
        return "Error: AI service not available"

    response = ai_service.explain_screenshot(user_input, screenshot)
    return response
