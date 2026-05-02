# Proctoring Client (Python)

Client architecture is split into separate files in the `proctoring/` package:
1. Data collection layer: `data_layer.py`
2. AI inference layer: `ai_layer.py`
3. Logic and evaluation layer: `logic_layer.py`
4. Communication layer: `communication_layer.py`

Additional modules:
- Login flow: `auth_layer.py`
- Preview UI: `display_layer.py`
- App orchestration: `app.py`

## Behavior configured for testing

- Login flow is implemented but disabled by default.
- Alerts are printed as JSON in terminal, not sent to server.
- Heartbeat is printed as JSON in terminal every 10-20 seconds (default 15s), including front/side camera status.
- UI shows two small camera screens in one window at top-right of the monitor.
- YOLO defaults to `yolov8n.pt` (Nano). You can override via `--yolo-model`.

Implemented rule groups from the latest scope update:
- Group 1: Unauthorized items on side camera (phone/tablet, laptop, smartwatch/clock, book/document).
- Group 2: Multiple people detection from both cameras.
- Group 3: Camera occlusion (dark frame over threshold) and seat absence from both cameras.
- Group 4: Abnormal gaze behavior (prolonged looking down, prolonged side looking, rapid gaze shifts).

## Quick start

```bash
pip install -r requirements.txt
python proctoring_client.py --side-source http://192.168.1.9:8080/
```

Press `q` or `Esc` to exit.

## Enable login flow (optional)

```bash
python proctoring_client.py \
  --side-source http://192.168.1.9:8080/ \
  --enable-login \
  --auth-url http://localhost:5000 \
  --username test_user \
  --password test_pass
```

## CLI options

```bash
python proctoring_client.py --help
```

## Backend API

This branch also includes the member 3 backend API:

- `backend/main.py`: FastAPI server on port `7777`.
- `frontend/index.html`: lightweight monitoring dashboard on port `4444`.
- SQLite storage for login attempts, heartbeat, and cheating events.
- No admin login, no proctor login, no exam management, no WebSocket.
- The client-facing contract is the 3 POST APIs from the report.
- The dashboard uses one read-only endpoint, `GET /dashboard/data`, to show saved DB data.

### Run backend

```bash
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 7777 --reload
```

### Run dashboard

```bash
python -m http.server 4444 --directory frontend
```

Open `http://localhost:4444`.

### API contract

- `POST /api/v1/auth/login`
- `POST /api/v1/monitoring/heartbeat`
- `POST /api/v1/monitoring/alerts`

Dashboard-only read endpoint:

- `GET /dashboard/data`

#### Login

```json
{
  "student_id": "B22DCCN123",
  "password": "hashed_password_string"
}
```

#### Heartbeat

```json
{
  "student_id": "B22DCCN123",
  "camera_front_status": "active",
  "camera_side_status": "active",
  "timestamp": "2026-04-21T08:30:15"
}
```

#### Alert

```json
{
  "student_id": "B22DCCN123",
  "exam_id": "CS101_FINAL",
  "camera_source": "SIDE_CAM",
  "violation_type": "UNAUTHORIZED_ITEM",
  "detected_objects": ["cell phone"],
  "confidence_score": 0.92,
  "timestamp": "2026-04-21T08:45:10",
  "evidence_image_base64": "R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
}
```

`exam_id` is accepted only because it is part of the report contract. The backend does not manage exams or make decisions based on exam records.
