from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./certificates.db"
    storage_dir: Path = Path("storage")
    max_recipients: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()
