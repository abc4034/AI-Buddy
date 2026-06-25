from pathlib import Path

import pytest

from integrations.xiaozhi_server.render_config import (
    default_output_path,
    render_config,
    write_config,
)


def test_render_config_uses_lan_ip_for_all_device_facing_urls():
    rendered = render_config("192.168.2.9")

    assert "websocket: ws://192.168.2.9:8000/xiaozhi/v1/" in rendered
    assert "vision_explain: http://192.168.2.9:8003/mcp/vision/explain" in rendered
    assert "base_url: http://192.168.2.9:8010/v1" in rendered
    assert "type: openai" in rendered
    assert "model_name: deepseek-v4-flash" in rendered
    assert "LLM: BuddyBrainLLM" in rendered
    assert "Memory: nomem" in rendered
    assert "Intent: nointent" in rendered
    assert "api_key: local" in rendered
    assert "${HOST_IP}" not in rendered


@pytest.mark.parametrize("bad_ip", ["127.0.0.1", "localhost", "999.1.1.1", "", "8.8.8.8"])
def test_render_config_rejects_unusable_device_ip(bad_ip):
    with pytest.raises(ValueError):
        render_config(bad_ip)


def test_write_config_creates_parent_directories(tmp_path):
    output = tmp_path / ".run" / "xiaozhi-esp32-server" / "main" / "xiaozhi-server" / "data" / ".config.yaml"

    written = write_config("192.168.2.9", output)

    assert written == output
    assert output.exists()
    assert "BuddyBrainLLM" in output.read_text(encoding="utf-8")


def test_default_output_path_points_to_xiaozhi_runtime_data():
    repo_root = Path("C:/workspace/AI Buddy")

    path = default_output_path(repo_root)

    assert path.as_posix().endswith(".run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml")
