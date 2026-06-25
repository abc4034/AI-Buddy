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


def test_setup_script_keeps_upstream_source_under_run_directory():
    text = Path("scripts/setup_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert ".run" in text
    assert "xiaozhi-esp32-server" in text
    assert "refs/heads/main.zip" in text


def test_start_xiaozhi_script_uses_conda_environment():
    text = Path("scripts/start_xiaozhi_server.ps1").read_text(encoding="utf-8")

    assert "conda run" in text
    assert "xiaozhi-esp32-server" in text
    assert "python app.py" in text
