from pathlib import Path


SCRIPTS = [
    "render_xiaozhi_config.ps1",
    "setup_xiaozhi_server.ps1",
    "start_buddy_brain.ps1",
    "start_xiaozhi_server.ps1",
    "print_local_demo_urls.ps1",
]


def test_xiaozhi_scripts_exist_and_are_ascii_safe():
    for script_name in SCRIPTS:
        path = Path("scripts") / script_name
        assert path.exists(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        text.encode("ascii")
        assert '$ErrorActionPreference = "Stop"' in text


def test_render_script_calls_python_renderer():
    text = Path("scripts/render_xiaozhi_config.ps1").read_text(encoding="utf-8")

    assert "integrations.xiaozhi_server.render_config" in text
    assert "--host-ip" in text
    assert "--repo-root" in text
    assert "$PSScriptRoot" in text
    assert "(Get-Location).Path" not in text


def test_render_script_uses_stable_private_ip_selection():
    text = Path("scripts/render_xiaozhi_config.ps1").read_text(encoding="utf-8")

    assert "InterfaceMetric" not in text
    assert "192.168.2." in text
    assert "127.*" in text
    assert "169.254.*" in text
    assert "10.*" in text
    assert "172.16.*" in text
    assert "172.31.*" in text
    assert "192.168.*" in text


def test_setup_script_keeps_upstream_source_under_run_directory():
    text = Path("scripts/setup_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert ".run" in text
    assert "xiaozhi-esp32-server" in text
    assert "refs/heads/main.zip" in text
    assert "$PSScriptRoot" in text
    assert "GetFullPath" in text
    assert "Resolve-Path" in text
    assert "Remove-Item -Recurse -Force -LiteralPath" in text
    assert "StartsWith" in text
    assert "Destination must resolve under" in text


def test_demo_url_script_keeps_expected_ports_and_stable_ip_selection():
    text = Path("scripts/print_local_demo_urls.ps1").read_text(encoding="utf-8")

    assert "InterfaceMetric" not in text
    assert "192.168.2." in text
    assert "127.*" in text
    assert "169.254.*" in text
    assert "http://$HostIp:8010/health" in text
    assert "http://$HostIp:8010/v1" in text
    assert "http://$HostIp:8003/xiaozhi/ota/" in text
    assert "ws://$HostIp:8000/xiaozhi/v1/" in text


def test_start_xiaozhi_script_uses_conda_environment():
    text = Path("scripts/start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "$PSScriptRoot" in text
    assert "conda run" in text
    assert "xiaozhi-esp32-server" in text
    assert "python app.py" in text
    assert "data\\.config.yaml" in text


def test_start_buddy_brain_script_uses_repo_relative_defaults():
    text = Path("scripts/start_buddy_brain.ps1").read_text(encoding="utf-8")

    assert "$PSScriptRoot" in text
    assert ".env" in text
    assert "buddy_brain.app:app" in text
    assert "--host 0.0.0.0" in text
    assert "--port $Port" in text
