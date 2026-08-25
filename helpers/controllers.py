import typing


class MouseController:
    def __init__(self) -> None:
        from pynput.mouse import Button, Controller

        self._controller = Controller()
        self._Button = Button

    def go_to_center_of_bbox(
        self, bbox: typing.Dict[str, typing.Tuple[int, int]]
    ) -> None:
        """bbox:
        {
            "top_left": (x1, y1),
            "top_right": (x2, y1),
            "bottom_left": (x1, y2),
            "bottom_right": (x2, y2),
        }
        """
        center = (
            (bbox["top_left"][0] + bbox["bottom_right"][0]) // 2,
            (bbox["top_left"][1] + bbox["bottom_right"][1]) // 2,
        )
        self._controller.position = center

    def click_left_button(self) -> None:
        self._controller.press(self._Button.left)
        self._controller.release(self._Button.left)
