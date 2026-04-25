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
        login_config=login_config,
    )
    client.run()


if __name__ == "__main__":
    main()
