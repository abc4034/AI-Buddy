from __future__ import annotations

import socket
from dataclasses import dataclass


WEBSOCKET_PATH = "/xiaozhi/v1/"


@dataclass(frozen=True)
class GatewaySettings:
    host: str = "0.0.0.0"
    http_port: int = 8003
    websocket_port: int = 8000
    advertise_host: str | None = None
    buddy_core_base_url: str = "http://127.0.0.1:8010"
    session_history_limit: int = 50

    def advertised_host(self) -> str:
        if self.advertise_host:
            return self.advertise_host
        if self.host and self.host not in {"0.0.0.0", "::"}:
            return self.host
        return _detect_lan_ip() or "127.0.0.1"

    def websocket_url(self) -> str:
        return f"ws://{self.advertised_host()}:{self.websocket_port}{WEBSOCKET_PATH}"


def _detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None
