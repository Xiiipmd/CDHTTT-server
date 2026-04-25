from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional, Union

import cv2


class CameraStream:
    def __init__(
        self,
        source: Union[int, str, list[str]],
        name: str,
        reconnect_interval_sec: float = 2.0,
    ) -> None:
        self.source = source
        self.name = name
        self.reconnect_interval_sec = reconnect_interval_sec

        self._lock = threading.Lock()
        self._frame: Optional[Any] = None
        self._timestamp: float = 0.0
        self._cap: Optional[cv2.VideoCapture] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._source_index = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._release_capture()

    def get_latest(self) -> tuple[Optional[Any], float]:
        with self._lock:
            if self._frame is None:
                return None, self._timestamp
            return self._frame.copy(), self._timestamp

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._is_capture_opened():
                self._open_capture()
                if not self._is_capture_opened():
                    time.sleep(self.reconnect_interval_sec)
                    continue

            ok, frame = self._cap.read() if self._cap is not None else (False, None)
            if not ok or frame is None:
                logging.warning("[%s] Frame read failed, reconnecting", self.name)
                self._release_capture()
                time.sleep(0.1)
                continue

            with self._lock:
                self._frame = frame
                self._timestamp = time.time()

    def _iter_sources(self) -> list[Union[int, str]]:
        if isinstance(self.source, list):
            return self.source
        return [self.source]

    def _next_source(self) -> Union[int, str]:
        sources = self._iter_sources()
        selected = sources[self._source_index % len(sources)]
        self._source_index += 1
        return selected

    def _open_capture(self) -> None:
        selected_source = self._next_source()
        logging.info("[%s] Opening source: %s", self.name, selected_source)
        self._cap = cv2.VideoCapture(selected_source)
        if not self._is_capture_opened():
            logging.warning("[%s] Cannot open source: %s", self.name, selected_source)

    def _is_capture_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def _release_capture(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def parse_front_source(value: str) -> Union[int, str]:
    return int(value) if value.isdigit() else value


def build_side_sources(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    return [base, f"{base}/video", f"{base}/videofeed", f"{base}/mjpegfeed"]
