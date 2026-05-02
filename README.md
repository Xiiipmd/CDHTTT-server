# Hệ thống phát hiện gian lận thi trực tuyến

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy backend

Backend chạy ở cổng `7777`.

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 7777 --reload
```

## Chạy dashboard

Dashboard chạy ở cổng `4444`.

```bash
python -m http.server 4444 --directory frontend
```

Mở:

```text
http://localhost:4444
```

Dashboard dùng để xem:

- heartbeat mới nhất từ các máy thí sinh,
- danh sách cảnh báo vi phạm,
- ảnh bằng chứng của từng cảnh báo.

## Chạy client giám sát

```bash
python proctoring_client.py --side-source http://192.168.1.9:8080/
```

Thoát chương trình bằng phím `q` hoặc `Esc`.

Xem các tham số hỗ trợ:

```bash
python proctoring_client.py --help
```

## Cấu trúc chính

```text
backend/main.py              Backend FastAPI
frontend/index.html          Dashboard giám sát
proctoring_client.py         File chạy client
proctoring/data_layer.py     Lấy dữ liệu camera
proctoring/ai_layer.py       Xử lý AI
proctoring/logic_layer.py    Luật phát hiện vi phạm
proctoring/communication_layer.py  Gửi heartbeat/cảnh báo
```

## API contract

Backend chỉ cần nhận dữ liệu từ client và lưu vào SQLite.

### 1. Đăng nhập

```text
POST /api/v1/auth/login
```

Request:

```json
{
  "student_id": "B22DCCN123",
  "password": "hashed_password_string"
}
```

Response:

```json
{
  "status": "success",
  "message": "Dang nhap thanh cong",
  "data": {
    "token": "...",
    "exam_id": "DEFAULT_EXAM"
  }
}
```

### 2. Heartbeat

```text
POST /api/v1/monitoring/heartbeat
```

Request:

```json
{
  "student_id": "B22DCCN123",
  "camera_front_status": "active",
  "camera_side_status": "active",
  "timestamp": "2026-04-21T08:30:15"
}
```

Response:

```json
{
  "status": "success",
  "server_action": "CONTINUE"
}
```

### 3. Gửi cảnh báo vi phạm

```text
POST /api/v1/monitoring/alerts
```

Request:

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

Response:

```json
{
  "status": "success",
  "message": "Da ghi nhan vi pham vao co so du lieu",
  "alert_id": 1
}
```

## API cho dashboard

```text
GET /dashboard/data
```

API này chỉ dùng để đọc dữ liệu đã lưu và hiển thị lên dashboard.

## Lưu ý

- Không có đăng nhập admin/giám thị.
- Không quản lý kỳ thi.
- Không dùng WebSocket.
- File SQLite sinh ra ở `backend/exam_monitoring.db` và không commit lên Git.
