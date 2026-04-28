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

## Backend dashboard

This branch also includes the member 3 server and proctor dashboard:

- `backend/main.py`: FastAPI server on port `7777`.
- `frontend/index.html`: proctor dashboard on port `4444`.
- SQLite storage for students, exams, monitoring clients, and cheating events.
- Student JWT login, heartbeat, and alert APIs.
- Proctor/admin JWT login with role-based permissions.
- WebSocket realtime dashboard updates at `/ws/dashboard`.

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

Demo proctor accounts:

```text
admin / admin123      role: ADMIN
giamthi / giamthi123  role: PROCTOR
```

Demo student account for the client:

```text
B22DCCN123 / hashed_password_string
```

Core client APIs:

- `POST /api/v1/auth/login`
- `POST /api/v1/monitoring/heartbeat`
- `POST /api/v1/monitoring/alerts`

Core proctor/admin APIs:

- `POST /api/v1/proctors/login`
- `GET /api/v1/monitoring/clients`
- `GET /api/v1/monitoring/alerts`
- `POST /api/v1/exams/{exam_id}/stop`
- `POST /api/v1/exams/{exam_id}/continue`
- `GET/POST/PUT/DELETE /api/v1/admin/students`
- `GET/POST/PUT/DELETE /api/v1/admin/exams`
