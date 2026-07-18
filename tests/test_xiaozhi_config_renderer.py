from pathlib import Path

import pytest

from integrations.xiaozhi_server.render_config import (
    default_output_path,
    resolve_output_path,
    render_config,
    write_config,
)


def test_render_config_uses_lan_ip_for_all_device_facing_urls():
    rendered = render_config("192.168.2.9")

    assert "websocket: ws://192.168.2.9:8000/xiaozhi/v1/" in rendered
    assert "vision_explain: http://192.168.2.9:8003/mcp/vision/explain" in rendered
    assert "LLM: ChatGLMLLM" in rendered
    assert "Memory: nomem" in rendered
    assert "Intent: nointent" in rendered
    assert "BuddyCoreLLM" not in rendered
    assert ":8010/" not in rendered
    assert "${HOST_IP}" not in rendered


@pytest.mark.parametrize("bad_ip", ["127.0.0.1", "localhost", "999.1.1.1", "", "8.8.8.8"])
def test_render_config_rejects_unusable_device_ip(bad_ip):
    with pytest.raises(ValueError):
        render_config(bad_ip)


def test_write_config_creates_parent_directories(tmp_path):
    repo_root = tmp_path / "repo"
    output = repo_root / "xiaozhi_server" / "data" / ".config.yaml"

    written = write_config("192.168.2.9", output, repo_root=repo_root)

    assert written == output
    assert output.exists()
    assert "ChatGLMLLM" in output.read_text(encoding="utf-8")


def test_default_output_path_points_to_xiaozhi_runtime_data():
    repo_root = Path("C:/workspace/AI Buddy")

    path = default_output_path(repo_root)

    assert path.as_posix().endswith("xiaozhi_server/data/.config.yaml")
    assert ".run" not in path.parts


def test_resolve_output_path_rejects_paths_outside_xiaozhi_runtime_data(tmp_path):
    repo_root = tmp_path / "repo"
    outside_output = tmp_path / "outside" / ".config.yaml"

    with pytest.raises(ValueError, match="under"):
        resolve_output_path(repo_root, outside_output)


def test_resolve_output_path_allows_custom_path_under_xiaozhi_runtime_data(tmp_path):
    repo_root = tmp_path / "repo"
    output = repo_root / "xiaozhi_server" / "data" / "custom.config.yaml"

    resolved = resolve_output_path(repo_root, output)

    assert resolved == output.resolve(strict=False)


def test_resolve_output_path_resolves_relative_output_from_repo_root(tmp_path):
    repo_root = tmp_path / "repo"
    output = Path("xiaozhi_server") / "data" / "custom.config.yaml"

    resolved = resolve_output_path(repo_root, output)

    assert resolved == (repo_root / output).resolve(strict=False)


def test_write_config_rejects_output_outside_xiaozhi_runtime_data(tmp_path):
    repo_root = tmp_path / "repo"
    output = tmp_path / "outside" / ".config.yaml"

    with pytest.raises(ValueError, match="under"):
        write_config("192.168.2.9", output, repo_root=repo_root)
