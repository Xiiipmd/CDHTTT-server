from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class LoginConfig:
    enabled: bool = False
    auth_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class LoginFlow:
    def __init__(self, config: LoginConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.token: Optional[str] = None

    def login(self) -> bool:
        if not self.config.enabled:
            logging.info("Login flow is disabled for testing mode.")
            return True

        if not self.config.auth_url or not self.config.username or not self.config.password:
            logging.error("Login is enabled but credentials/auth URL are missing.")
            return False

        endpoint = self.config.auth_url.rstrip("/") + "/login"
        payload = {
            "username": self.config.username,
            "password": self.config.password,
        }

        try:
            response = self.session.post(endpoint, json=payload, timeout=5)
            response.raise_for_status()
            data = response.json() if response.content else {}
            self.token = data.get("token")
            if self.token:
                self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            logging.info("Login successful.")
            return True
        except Exception as ex:
            logging.error("Login failed: %s", ex)
            return False
