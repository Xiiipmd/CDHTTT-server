from __future__ import annotations

import logging
from typing import Any

import cv2

from .models import FrontAnalysis, SideAnalysis, SideDetection, UNAUTHORIZED_CLASSES

try:
    import mediapipe as mp
except ImportError:
    mp = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


class AIInferenceLayer:
    def __init__(self, sample_fps: float = 2.5, yolo_model: str = "yolov8n.pt") -> None:
        self.sample_interval_sec = max(0.05, 1.0 / sample_fps)

        self._face_mesh = self._build_face_mesh()
        if self._face_mesh is None:
            logging.warning("Face Mesh unavailable. Falling back to Haar face detection.")

        self._haar_face = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        self._yolo = None
        if YOLO is not None:
            for candidate in self._candidate_models(yolo_model):
                try:
                    self._yolo = YOLO(candidate)
                    logging.info("Loaded YOLO model: %s", candidate)
                    break
                except Exception as ex:
                    logging.warning("Failed to load YOLO model '%s': %s", candidate, ex)
        else:
            logging.warning("ultralytics is not installed. Side object detection will be disabled.")

    @staticmethod
    def _candidate_models(primary: str) -> list[str]:
        # Prefer Nano because it is the lightest standard YOLOv8 model for real-time CPU usage.
        candidates = [primary, "yolov8n.pt", "yolov8n"]
        deduped: list[str] = []
        for name in candidates:
            if name not in deduped:
                deduped.append(name)
        return deduped

    @staticmethod
    def _build_face_mesh() -> Any:
        if mp is None:
            logging.warning("mediapipe is not installed.")
            return None

        try:
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
                return mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=3,
                    refine_landmarks=False,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )

            from mediapipe.python import solutions as mp_solutions

            return mp_solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=3,
                refine_landmarks=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        except Exception as ex:
            logging.warning("Cannot initialize MediaPipe Face Mesh: %s", ex)
            return None

    def analyze_front(self, frame: Any) -> FrontAnalysis:
        if frame is None:
            return FrontAnalysis(face_count=0, gaze_direction="unknown")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())

        if self._face_mesh is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self._face_mesh.process(rgb)
            if result.multi_face_landmarks:
                face_count = len(result.multi_face_landmarks)
                landmarks = result.multi_face_landmarks[0].landmark

                left_eye = landmarks[33]
                right_eye = landmarks[263]
                nose = landmarks[1]

                eye_center_x = (left_eye.x + right_eye.x) / 2.0
                offset = nose.x - eye_center_x
                if offset < -0.03:
                    gaze = "left"
                elif offset > 0.03:
                    gaze = "right"
                else:
                    gaze = "center"

                eye_center_y = (left_eye.y + right_eye.y) / 2.0
                chin = landmarks[152]
                face_width = max(abs(right_eye.x - left_eye.x), 1e-6)
                face_height = max(abs(chin.y - eye_center_y), 1e-6)
                head_yaw_deg = float(max(-45.0, min(45.0, (offset / face_width) * 35.0)))
                head_pitch_deg = float(
                    max(-45.0, min(45.0, ((nose.y - eye_center_y) / face_height) * 45.0))
                )

                eye_open_score = max(0.0, landmarks[145].y - landmarks[159].y)
                return FrontAnalysis(
                    face_count=face_count,
                    gaze_direction=gaze,
                    eye_open_score=eye_open_score,
                    head_yaw_deg=head_yaw_deg,
                    head_pitch_deg=head_pitch_deg,
                    frame_brightness=brightness,
                )

            return FrontAnalysis(face_count=0, gaze_direction="unknown", frame_brightness=brightness)

        faces = self._haar_face.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(50, 50))
        return FrontAnalysis(face_count=len(faces), gaze_direction="unknown", frame_brightness=brightness)

    def analyze_side(self, frame: Any) -> SideAnalysis:
        if frame is None:
            return SideAnalysis(person_count=0, detections=[], unauthorized_items=[], frame_brightness=0.0)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        if self._yolo is None:
            return SideAnalysis(person_count=0, detections=[], unauthorized_items=[], frame_brightness=brightness)

        detections: list[SideDetection] = []
        unauthorized_items: list[str] = []
        person_count = 0

        try:
            results = self._yolo.predict(frame, verbose=False, conf=0.35)
            if not results:
                return SideAnalysis(person_count=0, detections=[], unauthorized_items=[], frame_brightness=brightness)

            output = results[0]
            names = output.names
            for box in output.boxes:
                cls_id = int(box.cls.item())
                conf = float(box.conf.item())
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                label = str(names.get(cls_id, cls_id))
                label_lc = label.lower()

                detections.append(
                    SideDetection(label=label, confidence=conf, bbox_xyxy=(x1, y1, x2, y2))
                )

                if label_lc == "person":
                    person_count += 1
                if label_lc in UNAUTHORIZED_CLASSES:
                    unauthorized_items.append(label_lc)
        except Exception as ex:
            logging.warning("YOLO inference failed: %s", ex)

        return SideAnalysis(
            person_count=person_count,
            detections=detections,
            unauthorized_items=unauthorized_items,
            frame_brightness=brightness,
        )

    @staticmethod
    def draw_side_overlay(frame: Any, side: SideAnalysis) -> Any:
        canvas = frame.copy()
        for det in side.detections:
            x1, y1, x2, y2 = det.bbox_xyxy
            color = (0, 0, 255) if det.label.lower() in UNAUTHORIZED_CLASSES else (0, 255, 0)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            caption = f"{det.label} {det.confidence:.2f}"
            cv2.putText(canvas, caption, (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        return canvas

    @staticmethod
    def draw_front_overlay(frame: Any, front: FrontAnalysis) -> Any:
        canvas = frame.copy()
        summary = (
            f"face={front.face_count} gaze={front.gaze_direction} "
            f"yaw={front.head_yaw_deg if front.head_yaw_deg is not None else 'NA'} "
            f"pitch={front.head_pitch_deg if front.head_pitch_deg is not None else 'NA'}"
        )
        cv2.putText(canvas, summary, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 220, 240), 1)
        return canvas
