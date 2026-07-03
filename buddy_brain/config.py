from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeviceProfileConfig(BaseModel):
    child_name: str = "Mia"
    age_group: str = "primary school"
    english_level: str = "beginner"
    persona: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Buddy Core"
    persona: str = "cheerful"
    host: str = "0.0.0.0"
    port: int = 8010
    database_path: Path = Path("data/buddy_memory.db")
    device_config_path: Path = Path("config/devices.yaml")
    openai_base_url: str = "https://api.deepseek.com"
    openai_api_key: str = Field(default="", repr=False)
    model_name: str = "deepseek-v4-flash"
    memory_model_name: str | None = None
    demo_user_id: str = "demo-mia"
    demo_device_id: str = "esp32-fc012ccf1754"
    recent_episode_limit: int = 8
    request_timeout_seconds: float = 60.0

    @property
    def effective_memory_model(self) -> str:
        return self.memory_model_name or self.model_name


def load_device_profiles(path: Path) -> dict[str, DeviceProfileConfig]:
    path = Path(path)
    if not path.exists():
        return {}

    devices: dict[str, dict[str, str]] = {}
    current_device_id: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "devices:":
            continue
        if raw_line.startswith("  ") and not raw_line.startswith("    ") and stripped.endswith(":"):
            current_device_id = _unquote_scalar(stripped[:-1])
            devices[current_device_id] = {}
            continue
        if raw_line.startswith("    ") and current_device_id:
            key, separator, value = stripped.partition(":")
            if separator:
                devices[current_device_id][key.strip()] = _unquote_scalar(value.strip())

    return {
        device_id: DeviceProfileConfig(**values)
        for device_id, values in devices.items()
    }


def _unquote_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
