from __future__ import annotations

from typing import Optional

from .models import AlertEvent, FrontAnalysis, SideAnalysis, UNAUTHORIZED_LABEL_GROUPS


class LogicEvaluationLayer:
    def __init__(
        self,
        absent_threshold_sec: float = 5.0,
        occlusion_threshold_sec: float = 3.0,
        dark_brightness_threshold: float = 25.0,
        head_down_pitch_threshold_deg: float = 20.0,
        head_yaw_threshold_deg: float = 18.0,
        gaze_behavior_threshold_sec: float = 2.0,
        gaze_window_sec: float = 10.0,
        rapid_gaze_shift_threshold: int = 6,
        event_cooldown_sec: float = 5.0,
    ) -> None:
        self.absent_threshold_sec = absent_threshold_sec
        self.occlusion_threshold_sec = occlusion_threshold_sec
        self.dark_brightness_threshold = dark_brightness_threshold
        self.head_down_pitch_threshold_deg = head_down_pitch_threshold_deg
        self.head_yaw_threshold_deg = head_yaw_threshold_deg
        self.gaze_behavior_threshold_sec = gaze_behavior_threshold_sec
        self.gaze_window_sec = gaze_window_sec
        self.rapid_gaze_shift_threshold = rapid_gaze_shift_threshold
        self.event_cooldown_sec = event_cooldown_sec

        self._front_absent_since: Optional[float] = None
        self._side_absent_since: Optional[float] = None
        self._front_dark_since: Optional[float] = None
        self._side_dark_since: Optional[float] = None
        self._head_down_since: Optional[float] = None
        self._head_side_since: Optional[float] = None

        self._last_gaze_direction: Optional[str] = None
        self._gaze_shift_timestamps: list[float] = []

        self._last_event_at: dict[str, float] = {}

    def evaluate(self, front: FrontAnalysis, side: SideAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []

        events.extend(self._evaluate_unauthorized_items(side, now))
        events.extend(self._evaluate_multiple_people(front, side, now))
        events.extend(self._evaluate_camera_occlusion(front, side, now))
        events.extend(self._evaluate_absence(front, side, now))
        events.extend(self._evaluate_abnormal_gaze(front, now))

        return events

    def _evaluate_unauthorized_items(self, side: SideAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        if not side.unauthorized_items:
            return events

        labels = [item.lower() for item in side.unauthorized_items]
        for rule_name, group_labels in UNAUTHORIZED_LABEL_GROUPS.items():
            matched = sorted(set(label for label in labels if label in group_labels))
            if not matched:
                continue
            event_key = f"UNAUTHORIZED_ITEM:{rule_name}"
            if self._is_event_allowed(event_key, now):
                events.append(
                    AlertEvent(
                        event_type="UNAUTHORIZED_ITEM",
                        timestamp=now,
                        details={
                            "rule": rule_name,
                            "items": matched,
                            "camera_source": "SIDE_CAM",
                        },
                    )
                )

        return events

    def _evaluate_multiple_people(self, front: FrontAnalysis, side: SideAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        if side.person_count > 1 and self._is_event_allowed("MULTIPLE_PEOPLE:SIDE_CAM", now):
            events.append(
                AlertEvent(
                    event_type="MULTIPLE_PEOPLE",
                    timestamp=now,
                    details={
                        "camera_source": "SIDE_CAM",
                        "person_count": side.person_count,
                    },
                )
            )

        if front.face_count > 1 and self._is_event_allowed("MULTIPLE_PEOPLE:FRONT_CAM", now):
            events.append(
                AlertEvent(
                    event_type="MULTIPLE_PEOPLE",
                    timestamp=now,
                    details={
                        "camera_source": "FRONT_CAM",
                        "face_count": front.face_count,
                    },
                )
            )

        return events

    def _evaluate_camera_occlusion(self, front: FrontAnalysis, side: SideAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []

        front_dark = front.frame_brightness < self.dark_brightness_threshold
        side_dark = side.frame_brightness < self.dark_brightness_threshold

        self._front_dark_since = self._track_since(front_dark, self._front_dark_since, now)
        self._side_dark_since = self._track_since(side_dark, self._side_dark_since, now)

        if self._front_dark_since is not None:
            duration = now - self._front_dark_since
            if duration >= self.occlusion_threshold_sec and self._is_event_allowed("CAMERA_OCCLUDED:FRONT_CAM", now):
                events.append(
                    AlertEvent(
                        event_type="CAMERA_OCCLUDED",
                        timestamp=now,
                        details={
                            "camera_source": "FRONT_CAM",
                            "duration_sec": round(duration, 2),
                            "brightness": round(front.frame_brightness, 2),
                        },
                    )
                )

        if self._side_dark_since is not None:
            duration = now - self._side_dark_since
            if duration >= self.occlusion_threshold_sec and self._is_event_allowed("CAMERA_OCCLUDED:SIDE_CAM", now):
                events.append(
                    AlertEvent(
                        event_type="CAMERA_OCCLUDED",
                        timestamp=now,
                        details={
                            "camera_source": "SIDE_CAM",
                            "duration_sec": round(duration, 2),
                            "brightness": round(side.frame_brightness, 2),
                        },
                    )
                )

        return events

    def _evaluate_absence(self, front: FrontAnalysis, side: SideAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []

        self._front_absent_since = self._track_since(front.face_count == 0, self._front_absent_since, now)
        self._side_absent_since = self._track_since(side.person_count == 0, self._side_absent_since, now)

        if self._front_absent_since is not None:
            duration = now - self._front_absent_since
            if duration >= self.absent_threshold_sec and self._is_event_allowed("STUDENT_ABSENT:FRONT_CAM", now):
                events.append(
                    AlertEvent(
                        event_type="STUDENT_ABSENT",
                        timestamp=now,
                        details={
                            "camera_source": "FRONT_CAM",
                            "duration_sec": round(duration, 2),
                        },
                    )
                )

        if self._side_absent_since is not None:
            duration = now - self._side_absent_since
            if duration >= self.absent_threshold_sec and self._is_event_allowed("STUDENT_ABSENT:SIDE_CAM", now):
                events.append(
                    AlertEvent(
                        event_type="STUDENT_ABSENT",
                        timestamp=now,
                        details={
                            "camera_source": "SIDE_CAM",
                            "duration_sec": round(duration, 2),
                        },
                    )
                )

        return events

    def _evaluate_abnormal_gaze(self, front: FrontAnalysis, now: float) -> list[AlertEvent]:
        events: list[AlertEvent] = []

        pitch_down = front.head_pitch_deg is not None and front.head_pitch_deg > self.head_down_pitch_threshold_deg
        side_turn = front.head_yaw_deg is not None and abs(front.head_yaw_deg) > self.head_yaw_threshold_deg

        self._head_down_since = self._track_since(pitch_down, self._head_down_since, now)
        self._head_side_since = self._track_since(side_turn, self._head_side_since, now)

        if self._head_down_since is not None:
            duration = now - self._head_down_since
            if duration >= self.gaze_behavior_threshold_sec and self._is_event_allowed("ABNORMAL_GAZE:DOWN", now):
                events.append(
                    AlertEvent(
                        event_type="ABNORMAL_GAZE",
                        timestamp=now,
                        details={
                            "rule": "LOOKING_DOWN_PROLONGED",
                            "camera_source": "FRONT_CAM",
                            "duration_sec": round(duration, 2),
                            "pitch_deg": round(float(front.head_pitch_deg), 2),
                        },
                    )
                )

        if self._head_side_since is not None:
            duration = now - self._head_side_since
            if duration >= self.gaze_behavior_threshold_sec and self._is_event_allowed("ABNORMAL_GAZE:SIDE", now):
                events.append(
                    AlertEvent(
                        event_type="ABNORMAL_GAZE",
                        timestamp=now,
                        details={
                            "rule": "LOOKING_SIDE_PROLONGED",
                            "camera_source": "FRONT_CAM",
                            "duration_sec": round(duration, 2),
                            "yaw_deg": round(float(front.head_yaw_deg), 2),
                        },
                    )
                )

        events.extend(self._evaluate_rapid_gaze_shift(front, now))
        return events

    def _evaluate_rapid_gaze_shift(self, front: FrontAnalysis, now: float) -> list[AlertEvent]:
        valid = {"left", "right", "center"}
        direction = front.gaze_direction if front.gaze_direction in valid else None
        if direction is not None and self._last_gaze_direction is not None and direction != self._last_gaze_direction:
            self._gaze_shift_timestamps.append(now)
        if direction is not None:
            self._last_gaze_direction = direction

        cutoff = now - self.gaze_window_sec
        self._gaze_shift_timestamps = [t for t in self._gaze_shift_timestamps if t >= cutoff]

        if (
            len(self._gaze_shift_timestamps) >= self.rapid_gaze_shift_threshold
            and self._is_event_allowed("ABNORMAL_GAZE:RAPID_SHIFT", now)
        ):
            return [
                AlertEvent(
                    event_type="ABNORMAL_GAZE",
                    timestamp=now,
                    details={
                        "rule": "RAPID_GAZE_SHIFT",
                        "camera_source": "FRONT_CAM",
                        "shift_count": len(self._gaze_shift_timestamps),
                        "window_sec": self.gaze_window_sec,
                    },
                )
            ]

        return []

    @staticmethod
    def _track_since(condition: bool, since: Optional[float], now: float) -> Optional[float]:
        if condition:
            return now if since is None else since
        return None

    def _is_event_allowed(self, event_type: str, now: float) -> bool:
        last = self._last_event_at.get(event_type)
        if last is not None and (now - last) < self.event_cooldown_sec:
            return False
        self._last_event_at[event_type] = now
        return True
