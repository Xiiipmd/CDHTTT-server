from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "exam_monitoring.db"
JWT_SECRET = os.environ.get("EXAM_MONITORING_JWT_SECRET", "dev-secret-change-me")
JWT_TTL_SECONDS = 6 * 60 * 60
DEFAULT_EXAM_ID = "CS101_FINAL"
HEARTBEAT_WARNING_SECONDS = 5
HEARTBEAT_TIMEOUT_SECONDS = 10
TRANSPARENT_GIF_BASE64 = "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="


class CameraSource(str, Enum):
    FRONT_CAM = "FRONT_CAM"
    SIDE_CAM = "SIDE_CAM"


class CameraStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ServerAction(str, Enum):
    CONTINUE = "CONTINUE"
    STOP_EXAM = "STOP_EXAM"


class ViolationType(str, Enum):
    UNAUTHORIZED_ITEM = "UNAUTHORIZED_ITEM"
    UNAUTHORIZED_DEVICE = "UNAUTHORIZED_DEVICE"
    UNAUTHORIZED_MATERIAL = "UNAUTHORIZED_MATERIAL"
    SECOND_PERSON = "SECOND_PERSON"
    MULTIPLE_PEOPLE = "MULTIPLE_PEOPLE"
    CAMERA_BLOCKED = "CAMERA_BLOCKED"
    STUDENT_ABSENT = "STUDENT_ABSENT"
    ABNORMAL_GAZE = "ABNORMAL_GAZE"
    HEARTBEAT_LOST = "HEARTBEAT_LOST"


class TokenType(str, Enum):
    STUDENT = "student"
    PROCTOR = "proctor"


class ProctorRole(str, Enum):
    ADMIN = "ADMIN"
    PROCTOR = "PROCTOR"


class StudentLoginPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    password: Annotated[str, Field(min_length=1, max_length=255)]


class StudentLoginData(BaseModel):
    token: str
    exam_id: str


class StudentLoginResponse(BaseModel):
    status: str
    message: str
    data: StudentLoginData


class ProctorLoginPayload(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=50)]
    password: Annotated[str, Field(min_length=1, max_length=255)]


class ProctorLoginData(BaseModel):
    token: str
    username: str
    full_name: str
    role: ProctorRole


class ProctorLoginResponse(BaseModel):
    status: str
    message: str
    data: ProctorLoginData


class AuthToken(BaseModel):
    token_type: TokenType
    subject: str
    exam_id: str | None = None
    role: ProctorRole | None = None


class HeartbeatPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    camera_front_status: CameraStatus
    camera_side_status: CameraStatus
    timestamp: datetime


class HeartbeatResponse(BaseModel):
    status: str
    server_action: ServerAction


class AlertPayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    exam_id: Annotated[str, Field(min_length=1, max_length=50)]
    camera_source: CameraSource
    violation_type: ViolationType
    detected_objects: list[str] = Field(default_factory=list)
    confidence_score: Annotated[float, Field(ge=0, le=1)]
    timestamp: datetime
    evidence_image_base64: Annotated[str, Field(min_length=16)]

    @field_validator("evidence_image_base64")
    @classmethod
    def validate_base64(cls, value: str) -> str:
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
    source: str
    created_at: datetime


class ClientRecord(BaseModel):
    student_id: str
    exam_id: str
    camera_front_status: CameraStatus
    camera_side_status: CameraStatus
    last_heartbeat_at: datetime
    seconds_since_heartbeat: float
    connection_status: str
    server_action: ServerAction


class StudentRecord(BaseModel):
    student_id: str
    full_name: str
    created_at: datetime


class StudentCreatePayload(BaseModel):
    student_id: Annotated[str, Field(min_length=1, max_length=50)]
    password: Annotated[str, Field(min_length=1, max_length=255)]
    full_name: str = ""


class StudentUpdatePayload(BaseModel):
    password: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)


class ExamRecord(BaseModel):
    exam_id: str
    title: str
    action: ServerAction
    status: str
    start_time: datetime | None
    end_time: datetime | None
    created_at: datetime
    updated_at: datetime | None


class ExamCreatePayload(BaseModel):
    exam_id: Annotated[str, Field(min_length=1, max_length=50)]
    title: str = ""
    status: str = "scheduled"
    start_time: datetime | None = None
    end_time: datetime | None = None


class ExamUpdatePayload(BaseModel):
    title: str | None = None
    status: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    action: ServerAction | None = None


class DashboardSnapshot(BaseModel):
    type: str = "snapshot"
    clients: list[ClientRecord]
    alerts: list[AlertRecord]
    students: list[StudentRecord]
    exams: list[ExamRecord]


class DashboardConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    def has_connections(self) -> bool:
        return len(self.active_connections) > 0

    async def broadcast(self, payload: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(payload)
            except RuntimeError:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)


app = FastAPI(title="Online Exam Anti-Cheating Server", version="1.2.0")
dashboard_manager = DashboardConnectionManager()

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


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored_value: str) -> bool:
    if not stored_value.startswith("pbkdf2_sha256$"):
        return hmac.compare_digest(password, stored_value)
    try:
        _, iterations, salt, digest = stored_value.split("$", 3)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except ValueError:
        return False


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
                password_hash TEXT NOT NULL DEFAULT 'hashed_password_string',
                full_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exams (
                exam_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT 'CONTINUE',
                status TEXT NOT NULL DEFAULT 'scheduled',
                start_time TEXT,
                end_time TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS proctors (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'PROCTOR',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS monitoring_clients (
                student_id TEXT PRIMARY KEY,
                exam_id TEXT NOT NULL,
                camera_front_status TEXT NOT NULL,
                camera_side_status TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                server_action TEXT NOT NULL DEFAULT 'CONTINUE',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id),
                FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
            );

            CREATE TABLE IF NOT EXISTS cheating_events (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                exam_id TEXT NOT NULL,
                camera_source TEXT NOT NULL,
                violation_type TEXT NOT NULL,
                detected_objects TEXT NOT NULL DEFAULT '[]',
                confidence_score REAL NOT NULL,
                timestamp TEXT NOT NULL,
                evidence_image_base64 TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'CLIENT',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id),
                FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
            );
            """
        )
        add_column_if_missing(
            connection,
            "students",
            "password_hash",
            "TEXT NOT NULL DEFAULT 'hashed_password_string'",
        )
        add_column_if_missing(connection, "students", "full_name", "TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(connection, "exams", "title", "TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(connection, "exams", "action", "TEXT NOT NULL DEFAULT 'CONTINUE'")
        add_column_if_missing(connection, "exams", "status", "TEXT NOT NULL DEFAULT 'scheduled'")
        add_column_if_missing(connection, "exams", "start_time", "TEXT")
        add_column_if_missing(connection, "exams", "end_time", "TEXT")
        add_column_if_missing(connection, "exams", "updated_at", "TEXT")
        add_column_if_missing(
            connection,
            "cheating_events",
            "detected_objects",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        add_column_if_missing(connection, "cheating_events", "source", "TEXT NOT NULL DEFAULT 'CLIENT'")
        seed_demo_data(connection)


def seed_demo_data(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO exams (exam_id, title, action, status)
        VALUES (?, ?, ?, ?)
        """,
        (
            DEFAULT_EXAM_ID,
            "Final Exam - Computer Science 101",
            ServerAction.CONTINUE.value,
            "active",
        ),
    )
    sample_students = [
        ("B22DCCN123", "hashed_password_string", "Demo Student 1"),
        ("B20DCCN123", "hashed_password_string", "Demo Student 2"),
    ]
    connection.executemany(
        """
        INSERT OR IGNORE INTO students (student_id, password_hash, full_name)
        VALUES (?, ?, ?)
        """,
        sample_students,
    )
    sample_proctors = [
        ("admin", hash_password("admin123"), "Admin", ProctorRole.ADMIN.value),
        ("giamthi", hash_password("giamthi123"), "Giam thi", ProctorRole.PROCTOR.value),
    ]
    connection.executemany(
        """
        INSERT OR IGNORE INTO proctors (username, password_hash, full_name, role)
        VALUES (?, ?, ?, ?)
        """,
        sample_proctors,
    )


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_token(
    subject: str,
    token_type: TokenType,
    *,
    exam_id: str | None = None,
    role: ProctorRole | None = None,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "exp": int(time.time()) + JWT_TTL_SECONDS,
    }
    if exam_id is not None:
        payload["exam_id"] = exam_id
    if role is not None:
        payload["role"] = role.value

    header_part = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{b64url_encode(signature)}"


def decode_token(token: str) -> AuthToken:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected_signature = hmac.new(
            JWT_SECRET.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_signature = b64url_decode(signature_part)
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("Invalid token signature")

        payload = json.loads(b64url_decode(payload_part))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("Token expired")

        token_type = TokenType(payload.get("type", TokenType.STUDENT.value))
        role = ProctorRole(payload["role"]) if payload.get("role") else None
        return AuthToken(
            token_type=token_type,
            subject=payload["sub"],
            exam_id=payload.get("exam_id"),
            role=role,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def require_auth_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthToken:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization bearer token")
    return decode_token(authorization.removeprefix("Bearer ").strip())


def require_student_token(
    token: Annotated[AuthToken, Depends(require_auth_token)],
) -> AuthToken:
    if token.token_type != TokenType.STUDENT:
        raise HTTPException(status_code=403, detail="Student token required")
    return token


def require_proctor_token(
    token: Annotated[AuthToken, Depends(require_auth_token)],
) -> AuthToken:
    if token.token_type != TokenType.PROCTOR:
        raise HTTPException(status_code=403, detail="Proctor token required")
    return token


def require_admin_token(
    token: Annotated[AuthToken, Depends(require_proctor_token)],
) -> AuthToken:
    if token.role != ProctorRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return token


def assert_same_student(token: AuthToken, student_id: str) -> None:
    if token.subject != student_id:
        raise HTTPException(status_code=403, detail="Token does not belong to this student")


def assert_same_exam(token: AuthToken, exam_id: str) -> None:
    if token.exam_id != exam_id:
        raise HTTPException(status_code=403, detail="Token does not belong to this exam")


def get_exam_action(connection: sqlite3.Connection, exam_id: str) -> ServerAction:
    row = connection.execute(
        "SELECT action FROM exams WHERE exam_id = ?",
        (exam_id,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO exams (exam_id, title, action, status) VALUES (?, ?, ?, ?)",
            (exam_id, exam_id, ServerAction.CONTINUE.value, "active"),
        )
        return ServerAction.CONTINUE
    return ServerAction(row["action"])


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
    data: dict[str, Any] = dict(row)
    data["detected_objects"] = parse_detected_objects(data.get("detected_objects"))
    return AlertRecord(**data)


def client_from_row(row: sqlite3.Row, current_time: datetime) -> ClientRecord:
    last_heartbeat_at = datetime.fromisoformat(row["last_heartbeat_at"])
    status, seconds = connection_status(last_heartbeat_at, current_time)
    return ClientRecord(
        student_id=row["student_id"],
        exam_id=row["exam_id"],
        camera_front_status=CameraStatus(row["camera_front_status"]),
        camera_side_status=CameraStatus(row["camera_side_status"]),
        last_heartbeat_at=last_heartbeat_at,
        seconds_since_heartbeat=round(seconds, 1),
        connection_status=status,
        server_action=ServerAction(row["server_action"]),
    )


def student_from_row(row: sqlite3.Row) -> StudentRecord:
    return StudentRecord(
        student_id=row["student_id"],
        full_name=row["full_name"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def exam_from_row(row: sqlite3.Row) -> ExamRecord:
    updated_at = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
    start_time = datetime.fromisoformat(row["start_time"]) if row["start_time"] else None
    end_time = datetime.fromisoformat(row["end_time"]) if row["end_time"] else None
    return ExamRecord(
        exam_id=row["exam_id"],
        title=row["title"],
        action=ServerAction(row["action"]),
        status=row["status"],
        start_time=start_time,
        end_time=end_time,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=updated_at,
    )


def insert_alert(
    connection: sqlite3.Connection,
    *,
    student_id: str,
    exam_id: str,
    camera_source: str,
    violation_type: str,
    detected_objects: list[str],
    confidence_score: float,
    timestamp: str,
    evidence_image_base64: str,
    source: str,
) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO students (student_id) VALUES (?)",
        (student_id,),
    )
    connection.execute(
        "INSERT OR IGNORE INTO exams (exam_id, title, action, status) VALUES (?, ?, ?, ?)",
        (exam_id, exam_id, ServerAction.CONTINUE.value, "active"),
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
            evidence_image_base64,
            source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            exam_id,
            camera_source,
            violation_type,
            json.dumps(detected_objects, ensure_ascii=False),
            confidence_score,
            timestamp,
            evidence_image_base64,
            source,
        ),
    )
    return int(cursor.lastrowid)


def connection_status(last_heartbeat_at: datetime, now: datetime) -> tuple[str, float]:
    seconds = max(0.0, (now - last_heartbeat_at).total_seconds())
    if seconds <= HEARTBEAT_WARNING_SECONDS:
        return "ONLINE", seconds
    if seconds <= HEARTBEAT_TIMEOUT_SECONDS:
        return "WARNING", seconds
    return "OFFLINE", seconds


def record_missing_heartbeat_alerts(connection: sqlite3.Connection) -> bool:
    changed = False
    current_time = datetime.now()
    rows = connection.execute("SELECT * FROM monitoring_clients").fetchall()
    for row in rows:
        last_heartbeat_at = datetime.fromisoformat(row["last_heartbeat_at"])
        status, seconds = connection_status(last_heartbeat_at, current_time)
        if status != "OFFLINE" or seconds <= HEARTBEAT_TIMEOUT_SECONDS:
            continue

        existing = connection.execute(
            """
            SELECT alert_id
            FROM cheating_events
            WHERE student_id = ?
              AND exam_id = ?
              AND violation_type = ?
              AND timestamp >= ?
            LIMIT 1
            """,
            (
                row["student_id"],
                row["exam_id"],
                ViolationType.HEARTBEAT_LOST.value,
                row["last_heartbeat_at"],
            ),
        ).fetchone()
        if existing is not None:
            continue

        insert_alert(
            connection,
            student_id=row["student_id"],
            exam_id=row["exam_id"],
            camera_source="SYSTEM",
            violation_type=ViolationType.HEARTBEAT_LOST.value,
            detected_objects=["heartbeat"],
            confidence_score=1.0,
            timestamp=now_iso(),
            evidence_image_base64=TRANSPARENT_GIF_BASE64,
            source="SERVER",
        )
        changed = True
    return changed


def get_alert_records(connection: sqlite3.Connection, limit: int = 50) -> list[AlertRecord]:
    rows = connection.execute(
        """
        SELECT *
        FROM cheating_events
        ORDER BY alert_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [alert_from_row(row) for row in rows]


def get_client_records(connection: sqlite3.Connection) -> list[ClientRecord]:
    current_time = datetime.now()
    rows = connection.execute(
        """
        SELECT *
        FROM monitoring_clients
        ORDER BY last_heartbeat_at DESC
        """
    ).fetchall()
    return [client_from_row(row, current_time) for row in rows]


def get_student_records(connection: sqlite3.Connection) -> list[StudentRecord]:
    rows = connection.execute(
        """
        SELECT student_id, full_name, created_at
        FROM students
        ORDER BY student_id
        """
    ).fetchall()
    return [student_from_row(row) for row in rows]


def get_exam_records(connection: sqlite3.Connection) -> list[ExamRecord]:
    rows = connection.execute(
        """
        SELECT *
        FROM exams
        ORDER BY created_at DESC, exam_id
        """
    ).fetchall()
    return [exam_from_row(row) for row in rows]


def build_dashboard_snapshot() -> DashboardSnapshot:
    with get_connection() as connection:
        record_missing_heartbeat_alerts(connection)
        return DashboardSnapshot(
            clients=get_client_records(connection),
            alerts=get_alert_records(connection),
            students=get_student_records(connection),
            exams=get_exam_records(connection),
        )


async def broadcast_dashboard() -> None:
    if not dashboard_manager.has_connections():
        return
    snapshot = build_dashboard_snapshot()
    await dashboard_manager.broadcast(snapshot.model_dump(mode="json"))


async def heartbeat_watchdog() -> None:
    while True:
        await asyncio.sleep(1)
        if dashboard_manager.has_connections():
            await broadcast_dashboard()
        else:
            with get_connection() as connection:
                record_missing_heartbeat_alerts(connection)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    asyncio.create_task(heartbeat_watchdog())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login", response_model=StudentLoginResponse)
async def login(payload: StudentLoginPayload) -> StudentLoginResponse:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (payload.student_id,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid student_id or password")

    token = create_token(
        payload.student_id,
        TokenType.STUDENT,
        exam_id=DEFAULT_EXAM_ID,
    )
    return StudentLoginResponse(
        status="success",
        message="Dang nhap thanh cong",
        data=StudentLoginData(token=token, exam_id=DEFAULT_EXAM_ID),
    )


@app.post("/api/v1/proctors/login", response_model=ProctorLoginResponse)
async def proctor_login(payload: ProctorLoginPayload) -> ProctorLoginResponse:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM proctors WHERE username = ?",
            (payload.username,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    role = ProctorRole(row["role"])
    token = create_token(payload.username, TokenType.PROCTOR, role=role)
    return ProctorLoginResponse(
        status="success",
        message="Dang nhap giam thi thanh cong",
        data=ProctorLoginData(
            token=token,
            username=row["username"],
            full_name=row["full_name"],
            role=role,
        ),
    )


@app.get("/api/v1/proctors/me", response_model=ProctorLoginData)
async def proctor_me(
    token: Annotated[AuthToken, Depends(require_proctor_token)],
) -> ProctorLoginData:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM proctors WHERE username = ?",
            (token.subject,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Proctor not found")
    return ProctorLoginData(
        token="",
        username=row["username"],
        full_name=row["full_name"],
        role=ProctorRole(row["role"]),
    )


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket) -> None:
    raw_token = websocket.query_params.get("token", "")
    try:
        token = decode_token(raw_token)
        if token.token_type != TokenType.PROCTOR:
            raise HTTPException(status_code=403, detail="Proctor token required")
    except HTTPException:
        await websocket.close(code=1008)
        return

    await dashboard_manager.connect(websocket)
    try:
        await websocket.send_json(build_dashboard_snapshot().model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        dashboard_manager.disconnect(websocket)


@app.post("/api/v1/monitoring/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatPayload,
    token: Annotated[AuthToken, Depends(require_student_token)],
) -> HeartbeatResponse:
    assert_same_student(token, payload.student_id)
    timestamp = payload.timestamp.isoformat(timespec="seconds")

    with get_connection() as connection:
        server_action = get_exam_action(connection, token.exam_id or DEFAULT_EXAM_ID)
        connection.execute(
            """
            INSERT INTO monitoring_clients (
                student_id,
                exam_id,
                camera_front_status,
                camera_side_status,
                last_heartbeat_at,
                server_action,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                exam_id = excluded.exam_id,
                camera_front_status = excluded.camera_front_status,
                camera_side_status = excluded.camera_side_status,
                last_heartbeat_at = excluded.last_heartbeat_at,
                server_action = excluded.server_action,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.student_id,
                token.exam_id or DEFAULT_EXAM_ID,
                payload.camera_front_status.value,
                payload.camera_side_status.value,
                timestamp,
                server_action.value,
            ),
        )

    await broadcast_dashboard()
    return HeartbeatResponse(status="success", server_action=server_action)


@app.post("/api/v1/monitoring/alerts", response_model=AlertResponse, status_code=201)
async def receive_monitoring_alert(
    alert: AlertPayload,
    token: Annotated[AuthToken, Depends(require_student_token)],
) -> AlertResponse:
    assert_same_student(token, alert.student_id)
    assert_same_exam(token, alert.exam_id)
    with get_connection() as connection:
        alert_id = insert_alert(
            connection,
            student_id=alert.student_id,
            exam_id=alert.exam_id,
            camera_source=alert.camera_source.value,
            violation_type=alert.violation_type.value,
            detected_objects=alert.detected_objects,
            confidence_score=alert.confidence_score,
            timestamp=alert.timestamp.isoformat(timespec="seconds"),
            evidence_image_base64=alert.evidence_image_base64,
            source="CLIENT",
        )

    await broadcast_dashboard()
    return AlertResponse(
        status="success",
        message="Da ghi nhan vi pham vao co so du lieu",
        alert_id=alert_id,
    )


@app.post("/api/v1/alerts", response_model=AlertResponse, status_code=201)
async def receive_legacy_alert(alert: AlertPayload) -> AlertResponse:
    with get_connection() as connection:
        alert_id = insert_alert(
            connection,
            student_id=alert.student_id,
            exam_id=alert.exam_id,
            camera_source=alert.camera_source.value,
            violation_type=alert.violation_type.value,
            detected_objects=alert.detected_objects,
            confidence_score=alert.confidence_score,
            timestamp=alert.timestamp.isoformat(timespec="seconds"),
            evidence_image_base64=alert.evidence_image_base64,
            source="CLIENT_LEGACY",
        )

    await broadcast_dashboard()
    return AlertResponse(
        status="success",
        message="Da ghi nhan vi pham vao co so du lieu",
        alert_id=alert_id,
    )


@app.get("/api/v1/monitoring/alerts", response_model=list[AlertRecord])
async def list_monitoring_alerts(
    _: Annotated[AuthToken, Depends(require_proctor_token)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AlertRecord]:
    with get_connection() as connection:
        record_missing_heartbeat_alerts(connection)
        return get_alert_records(connection, limit=limit)


@app.get("/api/v1/alerts", response_model=list[AlertRecord])
async def list_legacy_alerts(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AlertRecord]:
    with get_connection() as connection:
        record_missing_heartbeat_alerts(connection)
        return get_alert_records(connection, limit=limit)


@app.get("/api/v1/monitoring/clients", response_model=list[ClientRecord])
async def list_clients(
    _: Annotated[AuthToken, Depends(require_proctor_token)],
) -> list[ClientRecord]:
    with get_connection() as connection:
        record_missing_heartbeat_alerts(connection)
        return get_client_records(connection)


@app.post("/api/v1/exams/{exam_id}/stop")
async def stop_exam(
    exam_id: str,
    _: Annotated[AuthToken, Depends(require_proctor_token)],
) -> dict[str, str]:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO exams (exam_id, title, action, status, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(exam_id) DO UPDATE SET
                action = excluded.action,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            (exam_id, exam_id, ServerAction.STOP_EXAM.value, "active"),
        )
        connection.execute(
            """
            UPDATE monitoring_clients
            SET server_action = ?, updated_at = CURRENT_TIMESTAMP
            WHERE exam_id = ?
            """,
            (ServerAction.STOP_EXAM.value, exam_id),
        )
    await broadcast_dashboard()
    return {"status": "success", "server_action": ServerAction.STOP_EXAM.value}


@app.post("/api/v1/exams/{exam_id}/continue")
async def continue_exam(
    exam_id: str,
    _: Annotated[AuthToken, Depends(require_proctor_token)],
) -> dict[str, str]:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO exams (exam_id, title, action, status, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(exam_id) DO UPDATE SET
                action = excluded.action,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            (exam_id, exam_id, ServerAction.CONTINUE.value, "active"),
        )
        connection.execute(
            """
            UPDATE monitoring_clients
            SET server_action = ?, updated_at = CURRENT_TIMESTAMP
            WHERE exam_id = ?
            """,
            (ServerAction.CONTINUE.value, exam_id),
        )
    await broadcast_dashboard()
    return {"status": "success", "server_action": ServerAction.CONTINUE.value}


@app.get("/api/v1/admin/students", response_model=list[StudentRecord])
async def list_students(
    _: Annotated[AuthToken, Depends(require_proctor_token)],
) -> list[StudentRecord]:
    with get_connection() as connection:
        return get_student_records(connection)


@app.post("/api/v1/admin/students", response_model=StudentRecord, status_code=201)
async def create_student(
    payload: StudentCreatePayload,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> StudentRecord:
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO students (student_id, password_hash, full_name)
                VALUES (?, ?, ?)
                """,
                (payload.student_id, hash_password(payload.password), payload.full_name),
            )
            row = connection.execute(
                "SELECT student_id, full_name, created_at FROM students WHERE student_id = ?",
                (payload.student_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Student already exists") from exc

    await broadcast_dashboard()
    return student_from_row(row)


@app.put("/api/v1/admin/students/{student_id}", response_model=StudentRecord)
async def update_student(
    student_id: str,
    payload: StudentUpdatePayload,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> StudentRecord:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Student not found")
        if payload.full_name is not None:
            connection.execute(
                "UPDATE students SET full_name = ? WHERE student_id = ?",
                (payload.full_name, student_id),
            )
        if payload.password:
            connection.execute(
                "UPDATE students SET password_hash = ? WHERE student_id = ?",
                (hash_password(payload.password), student_id),
            )
        updated = connection.execute(
            "SELECT student_id, full_name, created_at FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()

    await broadcast_dashboard()
    return student_from_row(updated)


@app.delete("/api/v1/admin/students/{student_id}")
async def delete_student(
    student_id: str,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> dict[str, str]:
    with get_connection() as connection:
        connection.execute("DELETE FROM monitoring_clients WHERE student_id = ?", (student_id,))
        connection.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
    await broadcast_dashboard()
    return {"status": "success"}


@app.get("/api/v1/admin/exams", response_model=list[ExamRecord])
async def list_exams(
    _: Annotated[AuthToken, Depends(require_proctor_token)],
) -> list[ExamRecord]:
    with get_connection() as connection:
        return get_exam_records(connection)


@app.post("/api/v1/admin/exams", response_model=ExamRecord, status_code=201)
async def create_exam(
    payload: ExamCreatePayload,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> ExamRecord:
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO exams (
                    exam_id,
                    title,
                    action,
                    status,
                    start_time,
                    end_time,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    payload.exam_id,
                    payload.title,
                    ServerAction.CONTINUE.value,
                    payload.status,
                    serialize_datetime(payload.start_time),
                    serialize_datetime(payload.end_time),
                ),
            )
            row = connection.execute(
                "SELECT * FROM exams WHERE exam_id = ?",
                (payload.exam_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Exam already exists") from exc

    await broadcast_dashboard()
    return exam_from_row(row)


@app.put("/api/v1/admin/exams/{exam_id}", response_model=ExamRecord)
async def update_exam(
    exam_id: str,
    payload: ExamUpdatePayload,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> ExamRecord:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM exams WHERE exam_id = ?", (exam_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Exam not found")
        updates: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        values: list[Any] = []
        if payload.title is not None:
            updates.append("title = ?")
            values.append(payload.title)
        if payload.status is not None:
            updates.append("status = ?")
            values.append(payload.status)
        if payload.start_time is not None:
            updates.append("start_time = ?")
            values.append(serialize_datetime(payload.start_time))
        if payload.end_time is not None:
            updates.append("end_time = ?")
            values.append(serialize_datetime(payload.end_time))
        if payload.action is not None:
            updates.append("action = ?")
            values.append(payload.action.value)
        values.append(exam_id)
        connection.execute(
            f"UPDATE exams SET {', '.join(updates)} WHERE exam_id = ?",
            values,
        )
        updated = connection.execute(
            "SELECT * FROM exams WHERE exam_id = ?",
            (exam_id,),
        ).fetchone()

    await broadcast_dashboard()
    return exam_from_row(updated)


@app.delete("/api/v1/admin/exams/{exam_id}")
async def delete_exam(
    exam_id: str,
    _: Annotated[AuthToken, Depends(require_admin_token)],
) -> dict[str, str]:
    with get_connection() as connection:
        connection.execute("DELETE FROM monitoring_clients WHERE exam_id = ?", (exam_id,))
        connection.execute("DELETE FROM exams WHERE exam_id = ?", (exam_id,))
    await broadcast_dashboard()
    return {"status": "success"}
