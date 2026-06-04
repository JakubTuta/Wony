import typing

import numpy as np
from PIL import Image

from helpers import model as helper_model


class ScreenReader:
    _reader: typing.Any = None

    @staticmethod
    def _get_reader() -> typing.Any:
        if ScreenReader._reader is None:
            import easyocr

            ScreenReader._reader = easyocr.Reader(["en"])
        return ScreenReader._reader

    @staticmethod
    def _use_gemini() -> bool:
        model = helper_model.get_model()
        return (
            model is not None
            and isinstance(model, (list, tuple))
            and model[0] == "gemini"
        )

    @staticmethod
    def take_screenshot(
        gray: bool = False,
        target: typing.Literal["main", "active", "all"] = "main",
    ) -> np.ndarray:
        """
        Take a screenshot of the specified display.

        Args:
            gray: Convert the screenshot to grayscale if True
            target: Which display to capture - "main" (primary display),
                    "active" (currently active display), or "all" (all displays)

        Returns:
            Screenshot as numpy array
        """
        import mss

        if target not in ["main", "active", "all"]:
            raise ValueError("target must be one of: 'main', 'active', or 'all'")

        with mss.mss() as sct:
            if target == "all":
                monitor = sct.monitors[0]

            elif target == "active":
                try:
                    import pyautogui

                    x, y = pyautogui.position()
                    monitor = sct.monitors[1]
                    for mon in sct.monitors[1:]:
                        if (
                            mon["left"] <= x < mon["left"] + mon["width"]
                            and mon["top"] <= y < mon["top"] + mon["height"]
                        ):
                            monitor = mon
                            break
                except ImportError:
                    monitor = sct.monitors[1]

            else:
                monitor = sct.monitors[1]

            screenshot = sct.grab(monitor)
            screenshot = Image.frombytes(
                "RGB", (screenshot.width, screenshot.height), screenshot.rgb
            )

        if gray:
            screenshot = screenshot.convert("L")

        return np.array(screenshot)

    @staticmethod
    def find_text_in_screenshot(screenshot: np.ndarray, text: str):
        if ScreenReader._use_gemini():
            from modules.ai import AI

            ai_model = AI()

            try:
                response = ai_model.find_text_in_screenshot(screenshot, text)

                if not response:
                    return None

                height, width = screenshot.shape[:2]
                ymin, xmin, ymax, xmax = [
                    int(coord * width / 1000) if i % 2 else int(coord * height / 1000)
                    for i, coord in enumerate(response)
                ]

                return {
                    "top_left": (xmin, ymin),
                    "top_right": (xmax, ymin),
                    "bottom_left": (xmin, ymax),
                    "bottom_right": (xmax, ymax),
                }

            except Exception as e:
                print(f"Error finding text with AI: {e}")
                return None

        reader = ScreenReader._get_reader()
        result = reader.readtext(screenshot)

        text_object = next(
            (detection for detection in result if detection[1].lower() == text.lower()),
            None,
        )

        if text_object:
            bbox, _, _ = text_object
            tl, tr, br, bl = bbox

            return {
                "top_left": (int(tl[0]), int(tl[1])),
                "top_right": (int(tr[0]), int(tr[1])),
                "bottom_right": (int(br[0]), int(br[1])),
                "bottom_left": (int(bl[0]), int(bl[1])),
            }
