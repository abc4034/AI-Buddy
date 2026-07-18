from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPO_ROOT / "scripts" / "start_buddy_fusion.ps1"
STOP_SCRIPT = REPO_ROOT / "scripts" / "stop_local_demo.ps1"
PORTS = (18100, 18103)


def powershell(command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def wait_for_ports(expected: bool, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        open_ports = []
        for port in PORTS:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(0.25)
                open_ports.append(client.connect_ex(("127.0.0.1", port)) == 0)
        if all(open_ports) is expected:
            return True
        time.sleep(0.2)
    return False


@pytest.mark.skipif(not hasattr(socket, "AF_INET"), reason="requires Windows TCP listeners")
def test_production_helpers_discover_and_stop_a_conda_listener_child(tmp_path: Path):
    fixture = tmp_path / "listener_fixture.py"
    fixture.write_text(
        "\n".join(
            [
                "import socket",
                "import sys",
                "import time",
                "listeners = []",
                "for value in sys.argv[1:] :",
                "    listener = socket.socket()",
                "    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)",
                "    listener.bind(('127.0.0.1', int(value)))",
                "    listener.listen()",
                "    listeners.append(listener)",
                "while True:",
                "    time.sleep(1)",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = subprocess.Popen(
        ["conda", "run", "--no-capture-output", "-n", "xiaozhi-env", "python", str(fixture), *(str(port) for port in PORTS)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    listener_pid: int | None = None
    try:
        assert wait_for_ports(True), "fixture listener did not start"
        discovery = powershell(
            "& { "
            f". '{START_SCRIPT}'; "
            f"Resolve-ServiceListenerPid -Ports @({PORTS[0]}, {PORTS[1]}) -ExpectedIdentity '{fixture}' -CondaEnv 'xiaozhi-env' "
            "}"
        )
        listener_pid = int(discovery.stdout.strip())
        assert listener_pid != wrapper.pid

        powershell(
            "& { "
            f". '{STOP_SCRIPT}'; "
            f"Stop-FusionOwnedProcess -ProcessId {listener_pid} -ExpectedIdentity '{fixture}' -CondaEnv 'xiaozhi-env' "
            "}"
        )
        assert wait_for_ports(False), "fixture ports were not released"
    finally:
        if wrapper.poll() is None:
            wrapper.terminate()
            try:
                wrapper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                wrapper.kill()
        assert wait_for_ports(False)
