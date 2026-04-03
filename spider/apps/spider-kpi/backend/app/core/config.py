import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    normalized = stripped.replace("'", '"')
                    try:
                        parsed = json.loads(normalized)
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                trimmed = stripped.strip('[]')
                if trimmed and '://' in trimmed:
                    return [item.strip().strip('"').strip("'") for item in trimmed.split(',') if item.strip()]
            return [item.strip().strip('"').strip("'") for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        runtime_host = os.getenv("SPIDER_DB_RUNTIME_HOST")
        if runtime_host and "@db:" in cleaned:
            cleaned = cleaned.replace("@db:", f"@{runtime_host}:")
        return cleaned

    app_name: str = "Spider KPI Decision Engine"
    env: str = "development"
    debug: bool = False
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://spider:spider@db:5432/spider_kpi"
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    app_password: str = "spider-kpi"
    auth_disabled: bool = True
    jwt_secret: str = "change-me"

    shopify_store_url: Optional[str] = None
    shopify_api_key: Optional[str] = None
    shopify_webhook_secret: Optional[str] = None

    triplewhale_api_key: Optional[str] = None

    freshdesk_domain: Optional[str] = None
    freshdesk_api_key: Optional[str] = None
    freshdesk_api_user: Optional[str] = None

    sync_interval_minutes: int = 5
    backfill_days: int = 365


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
