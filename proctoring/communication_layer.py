from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from typing import Any, Callable, Optional

import cv2

from .models import AlertEvent


class TerminalCommunicationLayer:
    def __init__(self, heartbeat_interval_sec: float = 15.0) -> None:
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status_provider: Optional[Callable[[], dict[str, Any]]] = None

    def set_status_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._status_provider = provider

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def send_alert(self, event: AlertEvent, evidence_frame: Optional[Any]) -> None:
        payload: dict[str, Any] = {
            "event_type": event.event_type,
            "timestamp": self._format_ts(event.timestamp),
            "details": event.details,
        }
        if evidence_frame is not None:
            payload["evidence_jpg_bytes"] = self._encode_frame_size(evidence_frame)

        print(json.dumps(payload, ensure_ascii=False))
        logging.warning("Triggered %s | %s", event.event_type, event.details)

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            payload = {
                "type": "HEARTBEAT",
                "timestamp": self._format_ts(time.time()),
                "status": "alive",
            }
            if self._status_provider is not None:
                try:
                    payload.update(self._status_provider())
                except Exception as ex:
                    logging.warning("Heartbeat status provider failed: %s", ex)
            print(json.dumps(payload, ensure_ascii=False))
            self._stop.wait(self.heartbeat_interval_sec)

    @staticmethod
    def _format_ts(ts: float) -> str:
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat()

    @staticmethod
    def _encode_frame_size(frame: Any) -> int:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        if not ok:
            return 0
        return int(encoded.size)
