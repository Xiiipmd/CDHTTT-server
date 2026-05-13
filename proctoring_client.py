from __future__ import annotations

import argparse
import logging

from proctoring import ProctoringClient
from proctoring.auth_layer import LoginConfig
from proctoring.data_layer import parse_front_source


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exam proctoring client")
    parser.add_argument("--front-source", default="0", help="Front camera source (default: 0)")
    parser.add_argument(
        "--side-source",
        default="http://192.168.1.9:8080/",
        help="Side camera stream URL",
    )
    parser.add_argument("--sample-fps", type=float, default=2.5, help="AI inference sampling FPS")
    parser.add_argument(
        "--yolo-model",
        default="yolov8n.pt",
        help="YOLO model name/path (default: yolov8n.pt)",
    )
    parser.add_argument("--heartbeat-sec", type=float, default=15.0, help="Heartbeat interval in seconds")
    parser.add_argument("--headless", action="store_true", help="Run without preview windows")
    parser.add_argument("--server-url", default="http://localhost:7777", help="Backend base URL")
    parser.add_argument("--student-id", default="B22DCCN123", help="Student ID sent to backend")
    parser.add_argument(
        "--student-password",
        default="hashed_password_string",
        help="Student password sent to backend login API",
    )
    parser.add_argument("--exam-id", default="DEFAULT_EXAM", help="Exam ID included in alert payloads")

    parser.add_argument("--enable-login", action="store_true", help="Enable login flow (disabled by default)")
    parser.add_argument("--auth-url", default=None, help="Authentication service base URL")
    parser.add_argument("--username", default=None, help="Username for login")
    parser.add_argument("--password", default=None, help="Password for login")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    login_config = LoginConfig(
        enabled=args.enable_login,
        auth_url=args.auth_url,
        username=args.username,
        password=args.password,
    )

    client = ProctoringClient(
        front_source=parse_front_source(args.front_source),
        side_source_url=args.side_source,
        sample_fps=args.sample_fps,
        yolo_model=args.yolo_model,
        heartbeat_interval_sec=args.heartbeat_sec,
        show_windows=not args.headless,
        server_url=args.server_url,
        student_id=args.student_id,
        student_password=args.student_password,
        exam_id=args.exam_id,
        login_config=login_config,
    )
    client.run()


if __name__ == "__main__":
    main()
