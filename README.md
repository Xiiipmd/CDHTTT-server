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
