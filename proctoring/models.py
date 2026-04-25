from __future__ import annotations

import dataclasses
from typing import Any, Optional


UNAUTHORIZED_LABEL_GROUPS: dict[str, set[str]] = {
    "PHONE_TABLET": {"cell phone", "phone", "tablet"},
    "SECONDARY_LAPTOP": {"laptop", "computer"},
    "SMARTWATCH_CLOCK": {"clock", "smartwatch", "watch"},
    "BOOK_OR_DOCUMENT": {"book", "paper", "document", "notebook"},
}

UNAUTHORIZED_CLASSES = set().union(*UNAUTHORIZED_LABEL_GROUPS.values())


@dataclasses.dataclass
class FrontAnalysis:
    face_count: int
    gaze_direction: str
    eye_open_score: Optional[float] = None
    head_yaw_deg: Optional[float] = None
    head_pitch_deg: Optional[float] = None
    frame_brightness: float = 0.0


@dataclasses.dataclass
class SideDetection:
    label: str
    confidence: float
    bbox_xyxy: tuple[int, int, int, int]


@dataclasses.dataclass
class SideAnalysis:
    person_count: int
    detections: list[SideDetection]
    unauthorized_items: list[str]
    frame_brightness: float = 0.0


@dataclasses.dataclass
class AlertEvent:
    event_type: str
    timestamp: float
    details: dict[str, Any]
