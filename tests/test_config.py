from pathlib import Path

from buddy_brain.config import Settings


def test_default_settings_are_safe_for_local_demo():
    settings = Settings(_env_file=None)

    assert settings.openai_base_url == "https://api.deepseek.com"
    assert settings.model_name == "deepseek-v4-flash"
    assert settings.database_path == Path("data/buddy_memory.db")
    assert settings.openai_api_key == ""
    assert settings.demo_user_id == "demo-mia"
    assert settings.recent_episode_limit == 8


def test_settings_accept_local_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "not-needed")
    monkeypatch.setenv("MODEL_NAME", "local-qwen")

    settings = Settings(_env_file=None)

    assert settings.openai_base_url == "http://127.0.0.1:8001/v1"
    assert settings.openai_api_key == "not-needed"
    assert settings.model_name == "local-qwen"
