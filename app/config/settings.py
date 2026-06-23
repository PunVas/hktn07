"""
Centralized application configuration via pydantic-settings.
All settings are loaded from environment variables / .env file.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./prguardian.db"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Harness API
    harness_api_key: str = ""
    harness_base_url: str = "https://app.harness.io"
    harness_account_id: str = ""
    harness_org_id: str = ""
    harness_project_id: str = ""

    # Queue
    rq_queue_name: str = "pr_guardian"
    worker_max_retries: int = 3

    # CORS
    cors_origins: List[str] = ["http://localhost:3000", "chrome-extension://*"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
