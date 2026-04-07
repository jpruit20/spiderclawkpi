import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

from pydantic import AliasChoices, Field, field_validator
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

    @field_validator('ga4_client_email', mode='before')
    @classmethod
    def normalize_ga4_client_email(cls, value: Any):
        if not isinstance(value, str):
            return value
        cleaned = value.strip().strip('"').strip("'")
        return cleaned or None

    @field_validator('ga4_private_key', mode='before')
    @classmethod
    def normalize_ga4_private_key(cls, value: Any):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1]
        return cleaned or None

    @field_validator('ga4_project_id', mode='before')
    @classmethod
    def normalize_ga4_project_id(cls, value: Any):
        if not isinstance(value, str):
            return value
        cleaned = value.strip().strip('"').strip("'")
        return cleaned or None

    @field_validator('ga4_property_id', mode='before')
    @classmethod
    def normalize_ga4_property_id(cls, value: Any):
        if not isinstance(value, str):
            return value
        cleaned = value.strip().strip('"').strip("'")
        return cleaned or None

    app_name: str = "Spider KPI Decision Engine"
    env: str = "development"
    debug: bool = False
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://spider:spider@db:5432/spider_kpi"
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    app_password: str = "change-me"
    auth_disabled: bool = False
    jwt_secret: str = "change-me"

    shopify_store_url: Optional[str] = None
    shopify_admin_access_token: Optional[str] = None
    shopify_api_key: Optional[str] = None
    shopify_api_secret: Optional[str] = None
    shopify_api_version: str = "2026-01"
    shopify_webhook_secret: Optional[str] = None

    triplewhale_api_key: Optional[str] = None

    ga4_property_id: Optional[str] = Field(default=None, validation_alias=AliasChoices('GA4_PROPERTY_ID', 'GOOGLE_ANALYTICS_PROPERTY_ID', 'GA_PROPERTY_ID'))
    ga4_client_email: Optional[str] = Field(default=None, validation_alias=AliasChoices('GA4_CLIENT_EMAIL', 'GOOGLE_ANALYTICS_CLIENT_EMAIL', 'GOOGLE_CLIENT_EMAIL'))
    ga4_private_key: Optional[str] = Field(default=None, validation_alias=AliasChoices('GA4_PRIVATE_KEY', 'GOOGLE_ANALYTICS_PRIVATE_KEY', 'GOOGLE_PRIVATE_KEY'))
    ga4_project_id: Optional[str] = Field(default=None, validation_alias=AliasChoices('GA4_PROJECT_ID', 'GOOGLE_ANALYTICS_PROJECT_ID', 'GOOGLE_PROJECT_ID'))
    ga4_data_api_base_url: str = Field(default='https://analyticsdata.googleapis.com/v1beta', validation_alias=AliasChoices('GA4_DATA_API_BASE_URL', 'GOOGLE_ANALYTICS_DATA_API_BASE_URL'))
    ga4_admin_api_base_url: str = Field(default='https://analyticsadmin.googleapis.com/v1beta', validation_alias=AliasChoices('GA4_ADMIN_API_BASE_URL', 'GOOGLE_ANALYTICS_ADMIN_API_BASE_URL'))

    clarity_project_id: Optional[str] = Field(default=None, validation_alias=AliasChoices('CLARITY_PROJECT_ID', 'MICROSOFT_CLARITY_PROJECT_ID'))
    clarity_api_token: Optional[str] = Field(default=None, validation_alias=AliasChoices('CLARITY_API_TOKEN', 'CLARITY_API_KEY', 'MICROSOFT_CLARITY_API_TOKEN', 'MICROSOFT_CLARITY_API_KEY'))
    clarity_base_url: str = Field(default='https://www.clarity.ms/export-data/api/v1/project-live-insights', validation_alias=AliasChoices('CLARITY_BASE_URL', 'MICROSOFT_CLARITY_BASE_URL'))
    clarity_endpoint: Optional[str] = Field(default=None, validation_alias=AliasChoices('CLARITY_ENDPOINT', 'MICROSOFT_CLARITY_ENDPOINT'))

    freshdesk_domain: Optional[str] = None
    freshdesk_api_key: Optional[str] = None
    freshdesk_api_user: Optional[str] = None

    sync_interval_minutes: int = 5
    historical_start_date: str = "2024-01-01"
    backfill_days: int = 824

    def ga4_validation_errors(self) -> list[str]:
        fields = [self.ga4_client_email, self.ga4_private_key, self.ga4_project_id, self.ga4_property_id]
        if not any(fields):
            return []

        errors: list[str] = []
        if not self.ga4_client_email:
            errors.append('GA4_CLIENT_EMAIL missing')
        elif not self.ga4_client_email.endswith('.iam.gserviceaccount.com'):
            errors.append('GA4_CLIENT_EMAIL must end with .iam.gserviceaccount.com')

        if not self.ga4_private_key:
            errors.append('GA4_PRIVATE_KEY missing')
        else:
            normalized_key = self.ga4_private_key.replace('\\n', '\n').strip()
            if '-----BEGIN PRIVATE KEY-----' not in normalized_key or '-----END PRIVATE KEY-----' not in normalized_key:
                errors.append('GA4_PRIVATE_KEY must contain a valid PEM header/footer')

        if not self.ga4_project_id:
            errors.append('GA4_PROJECT_ID missing')
        elif re.fullmatch(r'\d+', self.ga4_project_id):
            errors.append('GA4_PROJECT_ID must be a non-numeric string')

        if not self.ga4_property_id:
            errors.append('GA4_PROPERTY_ID missing')
        elif not re.fullmatch(r'\d+', self.ga4_property_id):
            errors.append('GA4_PROPERTY_ID must be numeric')

        return errors

    def ga4_invalid_message(self) -> str:
        return 'GA4 service-account credentials invalid or incomplete. Use client_email/private_key/project_id from Google service-account JSON and grant that service account access to the GA4 property.'

    def masked_ga4_client_email(self) -> str:
        email = (self.ga4_client_email or '').strip()
        if not email or '@' not in email:
            return 'missing'
        local, domain = email.split('@', 1)
        if len(local) <= 4:
            masked_local = local[0] + '***' if local else '***'
        else:
            masked_local = f'{local[:2]}***{local[-2:]}'
        return f'{masked_local}@{domain}'


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
