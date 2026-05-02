from __future__ import annotations

import base64
import binascii
import json
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "exam_monitoring.db"
DEFAULT_EXAM_ID = "DEFAULT_EXAM"


class LoginPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    password: Annotated[str, Field(min_length=1, max_length=255)]


class LoginData(BaseModel):
    token: str
    exam_id: str


class LoginResponse(BaseModel):
    status: str
    message: str
    data: LoginData


class HeartbeatPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    camera_front_status: str = "active"
    camera_side_status: str = "active"
    timestamp: datetime


class HeartbeatResponse(BaseModel):
    status: str
    server_action: str


class AlertPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    exam_id: str = DEFAULT_EXAM_ID
    camera_source: Annotated[str, Field(min_length=1, max_length=50)]
    violation_type: Annotated[str, Field(min_length=1, max_length=80)]
    detected_objects: list[str] = Field(default_factory=list)
    confidence_score: Annotated[float, Field(ge=0, le=1)] = 1.0
    timestamp: datetime
    evidence_image_base64: str = ""

    @field_validator("evidence_image_base64")
    @classmethod
    def validate_base64(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("data:image/"):
            raise ValueError("Send only raw base64, without data:image prefix")
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("evidence_image_base64 must be valid base64") from exc
        return value


class AlertResponse(BaseModel):
    status: str
    message: str
    alert_id: int


class AlertRecord(BaseModel):
    alert_id: int
    student_id: str
    exam_id: str
    camera_source: str
    violation_type: str
    detected_objects: list[str]
    confidence_score: float
    timestamp: datetime
    evidence_image_base64: str
    created_at: datetime


class HeartbeatRecord(BaseModel):
    student_id: str
    camera_front_status: str
    camera_side_status: str
    timestamp: datetime
    updated_at: datetime


class DashboardData(BaseModel):
    heartbeats: list[HeartbeatRecord]
    alerts: list[AlertRecord]


app = FastAPI(
    title="Online Exam Monitoring API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4444",
        "http://127.0.0.1:4444",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                password TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS heartbeats (
                student_id TEXT PRIMARY KEY,
                camera_front_status TEXT NOT NULL,
                camera_side_status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cheating_events (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                exam_id TEXT NOT NULL DEFAULT '',
                camera_source TEXT NOT NULL,
                violation_type TEXT NOT NULL,
                detected_objects TEXT NOT NULL DEFAULT '[]',
                confidence_score REAL NOT NULL DEFAULT 1,
                timestamp TEXT NOT NULL,
                evidence_image_base64 TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        add_column_if_missing(connection, "students", "password", "TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(connection, "cheating_events", "exam_id", "TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(
            connection,
            "cheating_events",
            "detected_objects",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        add_column_if_missing(
            connection,
            "cheating_events",
            "confidence_score",
            "REAL NOT NULL DEFAULT 1",
        )
        add_column_if_missing(
            connection,
            "cheating_events",
            "evidence_image_base64",
            "TEXT NOT NULL DEFAULT ''",
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def parse_detected_objects(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def alert_from_row(row: sqlite3.Row) -> AlertRecord:
    data = dict(row)
    data["detected_objects"] = parse_detected_objects(data.get("detected_objects"))
    return AlertRecord(**data)


@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(payload: LoginPayload) -> LoginResponse:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO students (student_id, password)
            VALUES (?, ?)
            ON CONFLICT(student_id) DO UPDATE SET password = excluded.password
            """,
            (payload.student_id, payload.password),
        )

    return LoginResponse(
        status="success",
        message="Dang nhap thanh cong",
        data=LoginData(
            token=secrets.token_urlsafe(24),
            exam_id=DEFAULT_EXAM_ID,
        ),
    )


@app.post("/api/v1/monitoring/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(payload: HeartbeatPayload) -> HeartbeatResponse:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO heartbeats (
                student_id,
                camera_front_status,
                camera_side_status,
                timestamp,
                updated_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                camera_front_status = excluded.camera_front_status,
                camera_side_status = excluded.camera_side_status,
                timestamp = excluded.timestamp,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.student_id,
                payload.camera_front_status,
                payload.camera_side_status,
                payload.timestamp.isoformat(timespec="seconds"),
            ),
        )

    return HeartbeatResponse(status="success", server_action="CONTINUE")


@app.post("/api/v1/monitoring/alerts", response_model=AlertResponse, status_code=201)
async def receive_alert(alert: AlertPayload) -> AlertResponse:
    with get_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO students (student_id) VALUES (?)",
            (alert.student_id,),
        )
        cursor = connection.execute(
            """
            INSERT INTO cheating_events (
                student_id,
                exam_id,
                camera_source,
                violation_type,
                detected_objects,
                confidence_score,
                timestamp,
                evidence_image_base64
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.student_id,
                alert.exam_id,
                alert.camera_source,
                alert.violation_type,
                json.dumps(alert.detected_objects, ensure_ascii=False),
                alert.confidence_score,
                alert.timestamp.isoformat(timespec="seconds"),
                alert.evidence_image_base64,
            ),
        )
        alert_id = int(cursor.lastrowid)

    return AlertResponse(
        status="success",
        message="Da ghi nhan vi pham vao co so du lieu",
        alert_id=alert_id,
    )


@app.get("/dashboard/data", response_model=DashboardData)
async def dashboard_data(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> DashboardData:
    with get_connection() as connection:
        heartbeat_rows = connection.execute(
            """
            SELECT *
            FROM heartbeats
            ORDER BY updated_at DESC
            """
        ).fetchall()
        alert_rows = connection.execute(
            """
            SELECT *
            FROM cheating_events
            ORDER BY alert_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return DashboardData(
        heartbeats=[HeartbeatRecord(**dict(row)) for row in heartbeat_rows],
        alerts=[alert_from_row(row) for row in alert_rows],
    )
