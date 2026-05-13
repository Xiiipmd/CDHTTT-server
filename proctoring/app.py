from __future__ import annotations

import logging
import time
from typing import Optional, Union

import cv2

from .ai_layer import AIInferenceLayer
from .auth_layer import LoginConfig, LoginFlow
from .communication_layer import TerminalCommunicationLayer
from .data_layer import CameraStream, build_side_sources
from .display_layer import TopRightPreview
from .logic_layer import LogicEvaluationLayer
from .models import FrontAnalysis


class ProctoringClient:
    def __init__(
        self,
        front_source: Union[int, str],
        side_source_url: str,
        sample_fps: float,
        yolo_model: str,
        heartbeat_interval_sec: float,
        show_windows: bool,
        server_url: Optional[str],
        student_id: str,
        student_password: str,
        exam_id: str,
        login_config: Optional[LoginConfig] = None,
    ) -> None:
        side_sources = build_side_sources(side_source_url)

        self.front_cam = CameraStream(source=front_source, name="front")
        self.side_cam = CameraStream(source=side_sources, name="side")
        self.ai = AIInferenceLayer(sample_fps=sample_fps, yolo_model=yolo_model)
        self.logic = LogicEvaluationLayer(absent_threshold_sec=5.0)
        self.comm = TerminalCommunicationLayer(
            heartbeat_interval_sec=heartbeat_interval_sec,
            server_url=server_url,
            student_id=student_id,
            student_password=student_password,
            exam_id=exam_id,
        )
        self.preview = TopRightPreview()
        self.show_windows = show_windows
        self._front_frame_ts: float = 0.0
        self._side_frame_ts: float = 0.0

        self.login = LoginFlow(login_config or LoginConfig(enabled=False))
        self.comm.set_status_provider(self._heartbeat_status)

    def run(self) -> None:
        if not self.login.login():
            logging.error("Cannot start client because login failed.")
            return

        logging.info("Starting client...")
        self.front_cam.start()
        self.side_cam.start()
        self.comm.start()

        next_step = time.time()
        try:
            while True:
                now = time.time()
                if now < next_step:
                    time.sleep(min(0.01, next_step - now))
                    continue
                next_step = now + self.ai.sample_interval_sec

                front_frame, front_ts = self.front_cam.get_latest()
                side_frame, side_ts = self.side_cam.get_latest()
                self._front_frame_ts = front_ts
                self._side_frame_ts = side_ts

                if side_frame is None:
                    logging.info("Waiting for side camera frame...")
                    continue

                front_result = self.ai.analyze_front(front_frame) if front_frame is not None else FrontAnalysis(0, "unknown")
                side_result = self.ai.analyze_side(side_frame)

                events = self.logic.evaluate(front=front_result, side=side_result, now=now)
                for event in events:
                    source = str(event.details.get("camera_source", ""))
                    if source == "SIDE_CAM":
                        evidence = side_frame
                    elif source == "FRONT_CAM" and front_frame is not None:
                        evidence = front_frame
                    else:
                        evidence = side_frame
                    self.comm.send_alert(event, evidence)

                if self.show_windows:
                    side_view = self.ai.draw_side_overlay(side_frame, side_result)
                    front_view = self.ai.draw_front_overlay(front_frame, front_result) if front_frame is not None else None
                    key = self.preview.show(front_view, side_view)
                    if key in (27, ord("q")):
                        break
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        logging.info("Shutting down client...")
        self.front_cam.stop()
        self.side_cam.stop()
        self.comm.stop()
        cv2.destroyAllWindows()

    def _heartbeat_status(self) -> dict[str, str]:
        now = time.time()
        front_ok = (now - self._front_frame_ts) <= 3.0 if self._front_frame_ts > 0 else False
        side_ok = (now - self._side_frame_ts) <= 3.0 if self._side_frame_ts > 0 else False
        return {
            "camera_front_status": "active" if front_ok else "inactive",
            "camera_side_status": "active" if side_ok else "inactive",
        }
