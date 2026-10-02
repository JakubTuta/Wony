import difflib
import typing

import numpy as np
from PIL import Image

from helpers import model as helper_model

# How close an OCR caption has to be to count as the same words. OCR misreads a
# character or two ("Accepl", "Setlings"), so equality never matched real UI
# text; below this, though, it is a different word and clicking it is a misfire.
_FUZZY_CUTOFF = 0.75


def _is_real_box(box: typing.Any) -> bool:
    """True only for a box that names an actual region of the screen.

    The model is told to answer [0, 0, 0, 0] when the text is not on screen.
    A non-empty list is truthy, so a plain falsiness check passed the sentinel
    straight through and callers clicked the top-left corner of the display and
    reported success. A degenerate box (zero width or height) is the same
    mistake in a less obvious form.
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    return xmax > xmin and ymax > ymin


class ScreenReader:
    _reader: typing.Any = None

    @staticmethod
    def _get_reader() -> typing.Any:
        if ScreenReader._reader is None:
            import easyocr

            from helpers.compute import torch_cuda_available

            use_gpu = torch_cuda_available()
            import helpers.diagnostics
            helpers.diagnostics.add("info", "ScreenReader", f"OCR using {'GPU' if use_gpu else 'CPU'}.")
            ScreenReader._reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
        return ScreenReader._reader

    # Providers whose send_message() accepts an image. Anthropic was excluded
    # for no reason: AI.find_text_in_screenshot goes through the provider-
    # agnostic send_message(image=...), so it works on both.
    _VISION_PROVIDERS = ("gemini", "anthropic")

    @staticmethod
    def _vision_capable() -> bool:
        model = helper_model.get_model()
        return (
            model is not None
            and isinstance(model, (list, tuple))
            and model[0] in ScreenReader._VISION_PROVIDERS
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
        """The best on-screen match for `text`, or None.

        Callers that must not act on the wrong thing want find_text_matches()
        instead — this one picks a winner even when several regions matched.
        """
        matches = ScreenReader.find_text_matches(screenshot, text)
        return matches[0]["box"] if matches else None

    @staticmethod
    def find_text_matches(
        screenshot: np.ndarray, text: str
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Every region reading as `text`, best first: [{"caption", "box"}, …].

        More than one entry means the words really are on screen more than once
        — the caller decides whether that is safe to act on.

        Local OCR first: the screen can show anything a camera could, and
        reading it never has to leave this PC when easyocr is installed. The
        AI provider's vision is the fallback, not the default, for whenever
        it isn't.
        """
        try:
            reader = ScreenReader._get_reader()
        except ImportError:
            reader = None

        if reader is not None:
            try:
                detections = reader.readtext(screenshot)
            except Exception as e:
                import helpers.diagnostics
                helpers.diagnostics.add("error", "ScreenReader", f"OCR failed: {e}")
                detections = None
            if detections is not None:
                return [
                    {"caption": str(detection[1]), "box": _bbox_from_ocr(detection[0])}
                    for detection in _rank_detections(detections, text)
                ]

        if ScreenReader._vision_capable():
            box = ScreenReader._ask_model(screenshot, text)
            return [{"caption": text, "box": box}] if box else []
        return []

    @staticmethod
    def _ask_model(screenshot: np.ndarray, text: str):
        from modules.ai import AI

        try:
            response = AI().find_text_in_screenshot(screenshot, text)
        except Exception as e:
            import helpers.diagnostics
            helpers.diagnostics.add("error", "ScreenReader", f"Error finding text with AI: {e}")
            return None

        if not _is_real_box(response):
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


def _bbox_from_ocr(bbox: typing.Sequence) -> typing.Dict[str, typing.Tuple[int, int]]:
    tl, tr, br, bl = bbox
    return {
        "top_left": (int(tl[0]), int(tl[1])),
        "top_right": (int(tr[0]), int(tr[1])),
        "bottom_right": (int(br[0]), int(br[1])),
        "bottom_left": (int(bl[0]), int(bl[1])),
    }


def _rank_detections(detections: typing.Sequence, text: str) -> typing.List[typing.Any]:
    """OCR detections that read as `text`, best tier only, best first.

    Tiers, in order: the same words, one contained in the other, close enough
    after a misread. Only the best tier that matched is returned — a screen with
    a real "Accept" button must not also offer "Accepted at 12:04" as a
    candidate and make the whole thing ambiguous.
    """
    needle = (text or "").strip().lower()
    if not needle:
        return []

    tiers: typing.Dict[int, typing.List[typing.Tuple[float, typing.Any]]] = {}
    for detection in detections:
        caption = str(detection[1]).strip().lower()
        if not caption:
            continue
        ratio = difflib.SequenceMatcher(None, needle, caption).ratio()
        if caption == needle:
            tier = 0
        elif needle in caption or caption in needle:
            tier = 1
        elif ratio >= _FUZZY_CUTOFF:
            tier = 2
        else:
            continue
        tiers.setdefault(tier, []).append((ratio, detection))

    if not tiers:
        return []
    best = tiers[min(tiers)]
    best.sort(key=lambda pair: pair[0], reverse=True)
    return [detection for _ratio, detection in best]
