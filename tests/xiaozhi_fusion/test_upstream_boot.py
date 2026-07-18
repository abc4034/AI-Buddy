from __future__ import annotations

import socket
import subprocess
import tempfile
import time
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import psutil
import pytest

from integrations.xiaozhi_server.render_config import default_output_path, write_config


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "xiaozhi_server"
CONFIG_PATH = RUNTIME_DIR / "data" / ".config.yaml"
APP_PATH = RUNTIME_DIR / "app.py"
WEBSOCKET_PORT = 18000
HTTP_PORT = 18003


def wait_tcp(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            if client.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def wait_http(url: str, timeout: float):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return urlopen(url, timeout=1)
        except (OSError, URLError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"HTTP endpoint did not become ready: {last_error}")


def listener_pids(port: int) -> set[int]:
    return {
        connection.pid
        for connection in psutil.net_connections(kind="tcp")
        if connection.pid
        and connection.laddr
        and connection.laddr.port == port
        and connection.status == psutil.CONN_LISTEN
    }


def wait_ports_released(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not listener_pids(WEBSOCKET_PORT) and not listener_pids(HTTP_PORT):
            return True
        time.sleep(0.2)
    return False


def terminate_process_tree(process: subprocess.Popen[bytes], listener_pid: int | None) -> None:
    owned: dict[int, psutil.Process] = {}
    for pid in (process.pid, listener_pid):
        if pid is None:
            continue
        try:
            candidate = psutil.Process(pid)
            owned[candidate.pid] = candidate
            for child in candidate.children(recursive=True):
                owned[child.pid] = child
        except psutil.Error:
            continue

    for candidate in owned.values():
        try:
            candidate.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(list(owned.values()), timeout=10)
    for candidate in alive:
        try:
            candidate.kill()
        except psutil.Error:
            continue
    process.wait(timeout=10)


def test_vendored_app_owns_both_alternate_listeners_and_releases_them():
    original_config = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
    process: subprocess.Popen[bytes] | None = None
    listener_pid: int | None = None
    log_file = tempfile.NamedTemporaryFile(prefix="xiaozhi-upstream-boot-", suffix=".log", delete=False)
    log_path = Path(log_file.name)

    try:
        rendered_path = write_config("192.168.2.9", default_output_path(REPO_ROOT), repo_root=REPO_ROOT)
        rendered_path.write_text(
            rendered_path.read_text(encoding="utf-8")
            .replace("port: 8000", f"port: {WEBSOCKET_PORT}")
            .replace("http_port: 8003", f"http_port: {HTTP_PORT}"),
            encoding="utf-8",
        )

        process = subprocess.Popen(
            ["conda", "run", "--no-capture-output", "-n", "xiaozhi-env", "python", str(APP_PATH)],
            cwd=RUNTIME_DIR,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

        if not wait_tcp("127.0.0.1", WEBSOCKET_PORT, timeout=30):
            log_file.flush()
            pytest.fail("XiaoZhi app.py did not open the WebSocket listener:\n" + log_path.read_text(encoding="utf-8", errors="replace"))
        with wait_http(f"http://127.0.0.1:{HTTP_PORT}/xiaozhi/ota/", timeout=30) as response:
            assert response.status == 200

        websocket_pids = listener_pids(WEBSOCKET_PORT)
        http_pids = listener_pids(HTTP_PORT)
        assert len(websocket_pids) == 1
        assert websocket_pids == http_pids
        listener_pid = websocket_pids.pop()
        assert str(APP_PATH).lower() in " ".join(psutil.Process(listener_pid).cmdline()).lower()
        print(f"XiaoZhi app.py listener PID {listener_pid} owns ports {WEBSOCKET_PORT} and {HTTP_PORT}")
    finally:
        if process is not None:
            terminate_process_tree(process, listener_pid)
        assert wait_ports_released(timeout=15)
        log_file.close()
        log_path.unlink(missing_ok=True)
        if original_config is None:
            CONFIG_PATH.unlink(missing_ok=True)
        else:
            CONFIG_PATH.write_bytes(original_config)
