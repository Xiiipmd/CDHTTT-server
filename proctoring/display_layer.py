from __future__ import annotations

import ctypes
from typing import Any, Optional

import cv2
import numpy as np


class TopRightPreview:
    def __init__(
        self,
        window_name: str = "Proctor Preview",
        tile_width: int = 240,
        tile_height: int = 160,
        margin: int = 12,
    ) -> None:
        self.window_name = window_name
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.margin = margin
        self._window_ready = False

    def show(self, front_frame: Optional[Any], side_frame: Optional[Any]) -> int:
        panel = self._compose_panel(front_frame, side_frame)

        if not self._window_ready:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, panel.shape[1], panel.shape[0])
            self._move_top_right(panel.shape[1], panel.shape[0])
            self._window_ready = True

        cv2.imshow(self.window_name, panel)
        return cv2.waitKey(1) & 0xFF

    def _compose_panel(self, front_frame: Optional[Any], side_frame: Optional[Any]) -> Any:
        front = self._render_tile(front_frame, "Front Cam")
        side = self._render_tile(side_frame, "Side Cam")
        return np.hstack([front, side])

    def _render_tile(self, frame: Optional[Any], title: str) -> Any:
        tile = np.zeros((self.tile_height, self.tile_width, 3), dtype=np.uint8)
        if frame is not None:
            resized = cv2.resize(frame, (self.tile_width, self.tile_height), interpolation=cv2.INTER_AREA)
            tile = resized
        cv2.putText(tile, title, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        return tile

    def _move_top_right(self, panel_width: int, panel_height: int) -> None:
        screen_w, _ = self._screen_size()
        x = max(0, screen_w - panel_width - self.margin)
        y = self.margin
        cv2.moveWindow(self.window_name, x, y)

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        try:
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:
            return 1920, 1080
