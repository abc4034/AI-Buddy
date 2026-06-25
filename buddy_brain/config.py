from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Buddy Brain"
    host: str = "0.0.0.0"
    port: int = 8010
    database_path: Path = Path("data/buddy_memory.db")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
