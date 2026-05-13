from __future__ import annotations

import datetime as dt
import base64
import json
import logging
import threading
import time
from typing import Any, Callable, Optional

import cv2
import requests

from .models import AlertEvent


class TerminalCommunicationLayer:
    def __init__(
        self,
        heartbeat_interval_sec: float = 15.0,
        server_url: Optional[str] = "http://localhost:7777",
        student_id: str = "B22DCCN123",
        student_password: str = "hashed_password_string",
        exam_id: str = "DEFAULT_EXAM",
    ) -> None:
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.server_url = server_url.rstrip("/") if server_url else None
        self.student_id = student_id
        self.student_password = student_password
        self.exam_id = exam_id
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status_provider: Optional[Callable[[], dict[str, Any]]] = None
        self._session = requests.Session()

    def set_status_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._status_provider = provider

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._login()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def send_alert(self, event: AlertEvent, evidence_frame: Optional[Any]) -> None:
        payload: dict[str, Any] = {
            "student_id": self.student_id,
            "exam_id": self.exam_id,
            "camera_source": str(event.details.get("camera_source", "SIDE_CAM")),
            "violation_type": event.event_type,
            "detected_objects": self._detected_objects(event),
            "confidence_score": float(event.details.get("confidence_score", 1.0)),
            "timestamp": self._format_ts(event.timestamp),
            "evidence_image_base64": "",
        }
        if evidence_frame is not None:
            payload["evidence_image_base64"] = self._encode_frame_base64(evidence_frame)

        print(json.dumps(payload, ensure_ascii=False))
        self._post("/api/v1/monitoring/alerts", payload)
        logging.warning("Triggered %s | %s", event.event_type, event.details)

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            payload = {
                "student_id": self.student_id,
                "timestamp": self._format_ts(time.time()),
                "camera_front_status": "inactive",
                "camera_side_status": "inactive",
            }
            if self._status_provider is not None:
                try:
                    payload.update(self._status_provider())
                except Exception as ex:
                    logging.warning("Heartbeat status provider failed: %s", ex)
            print(json.dumps(payload, ensure_ascii=False))
            self._post("/api/v1/monitoring/heartbeat", payload)
            self._stop.wait(self.heartbeat_interval_sec)

    def _login(self) -> None:
        payload = {
            "student_id": self.student_id,
            "password": self.student_password,
        }
        self._post("/api/v1/auth/login", payload)

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        if not self.server_url:
            return
        try:
            response = self._session.post(
                self.server_url + path,
                json=payload,
                timeout=3,
            )
            response.raise_for_status()
        except Exception as ex:
            logging.warning("Cannot send data to backend %s: %s", path, ex)

    @staticmethod
    def _detected_objects(event: AlertEvent) -> list[str]:
        items = event.details.get("items")
        if isinstance(items, list):
            return [str(item) for item in items]
        rule = event.details.get("rule")
        if rule:
            return [str(rule)]
        return []

    @staticmethod
    def _format_ts(ts: float) -> str:
        return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")

    @staticmethod
    def _encode_frame_base64(frame: Any) -> str:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        if not ok:
            return ""
        return base64.b64encode(encoded.tobytes()).decode("utf-8")
