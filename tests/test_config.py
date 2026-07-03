from pathlib import Path

from buddy_brain.config import Settings, load_device_profiles


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_settings_are_safe_for_local_demo():
    settings = Settings(_env_file=None)

    assert settings.app_name == "Buddy Core"
    assert settings.persona == "cheerful"
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
    monkeypatch.setenv("PERSONA", "calm")

    settings = Settings(_env_file=None)

    assert settings.openai_base_url == "http://127.0.0.1:8001/v1"
    assert settings.openai_api_key == "not-needed"
    assert settings.model_name == "local-qwen"
    assert settings.persona == "calm"


def test_load_device_profiles_from_simple_yaml(tmp_path):
    config_path = tmp_path / "devices.yaml"
    config_path.write_text(
        "\n".join(
            [
                "devices:",
                "  esp32-luna:",
                "    child_name: Luna",
                "    age_group: kindergarten",
                "    english_level: starter",
                "    persona: coach",
            ]
        ),
        encoding="utf-8",
    )

    profiles = load_device_profiles(config_path)

    assert profiles["esp32-luna"].child_name == "Luna"
    assert profiles["esp32-luna"].age_group == "kindergarten"
    assert profiles["esp32-luna"].english_level == "starter"
    assert profiles["esp32-luna"].persona == "coach"


def test_devices_example_config_loads_supported_personas():
    profiles = load_device_profiles(REPO_ROOT / "config" / "devices.example.yaml")

    assert set(profiles) == {"debug-device-a", "debug-device-b", "esp32-fc012ccf1754"}
    assert profiles["debug-device-a"].persona == "cheerful"
    assert profiles["debug-device-b"].persona == "calm"
    assert profiles["esp32-fc012ccf1754"].persona == "coach"
