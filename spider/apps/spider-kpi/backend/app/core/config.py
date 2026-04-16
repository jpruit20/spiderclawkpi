import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional, Union

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
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
    database_url: str = Field(
        default="postgresql+psycopg://spider:spider@db:5432/spider_kpi",
        validation_alias=AliasChoices('DATABASE_URL', 'KPI_DATABASE_URL'),
    )
    cors_origins: Union[str, List[str]] = Field(default_factory=lambda: ["http://localhost:3000"])

    app_password: str = "change-me"
    auth_disabled: bool = False
    jwt_secret: str = "change-me"
    allowed_signup_domains: Union[str, List[str]] = Field(default_factory=lambda: ["spidergrills.com", "alignmachineworks.com"])
    auth_email_from: str = Field(default='no-reply@spidergrills.app')
    auth_email_region: Optional[str] = Field(default='us-east-2')

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

    # ClickUp (Spider Grills workspace)
    clickup_api_token: Optional[str] = None
    clickup_team_id: Optional[str] = None
    clickup_base_url: str = "https://api.clickup.com/api/v2"
    clickup_sync_interval_minutes: int = 15
    clickup_task_lookback_days: int = 120

    aws_telemetry_url: Optional[str] = None
    aws_telemetry_local_path: Optional[str] = None
    aws_telemetry_api_token: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: Optional[str] = None
    aws_telemetry_dynamodb_table: Optional[str] = None
    aws_telemetry_lookback_hours: int = 24 * 30
    aws_telemetry_session_gap_minutes: int = 20
    aws_telemetry_max_scan_pages: int = 10
    aws_telemetry_target_devices_per_sync: int = 25
    aws_telemetry_scan_segments: int = 8
    aws_telemetry_min_session_seconds: int = 300
    aws_telemetry_merge_gap_seconds: int = 180
    aws_telemetry_test_device_prefixes: str = 'test,qa,dev,demo,stage,staging'
    aws_telemetry_test_models: str = ''
    aws_telemetry_test_device_ids: str = ''

    reddit_enabled: bool = Field(default=True)
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_sync_interval_minutes: int = 30
    youtube_api_key: Optional[str] = None
    google_places_api_key: Optional[str] = None
    google_places_id: Optional[str] = None  # Spider Grills place ID

    # Amazon SP-API
    amazon_sp_client_id: Optional[str] = None
    amazon_sp_client_secret: Optional[str] = None
    amazon_sp_refresh_token: Optional[str] = None
    amazon_sp_app_id: Optional[str] = None
    amazon_marketplace_id: str = "ATVPDKIKX0DER"  # US marketplace
    amazon_sp_region: str = "us-east-1"
    amazon_sync_interval_minutes: int = 360  # every 6 hours

    github_token: Optional[str] = Field(default=None, validation_alias=AliasChoices('GITHUB_TOKEN', 'GH_TOKEN'))
    github_owner: str = Field(default='spider-grills', validation_alias=AliasChoices('GITHUB_OWNER', 'GH_OWNER'))
    github_repo: str = Field(default='venom-firmware', validation_alias=AliasChoices('GITHUB_REPO', 'GH_REPO'))

    # AI assistant
    ai_assistant_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('AI_ASSISTANT_ENABLED')
    )
    ai_assistant_model: str = Field(
        default="sonnet",
        validation_alias=AliasChoices('AI_ASSISTANT_MODEL')
    )
    anthropic_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices('ANTHROPIC_API_KEY'))
    workspace_root: str = Field(
        default="",
        validation_alias=AliasChoices('WORKSPACE_ROOT', 'KPI_WORKSPACE_ROOT'),
    )

    @field_validator("ai_assistant_enabled", mode="before")
    @classmethod
    def parse_ai_assistant_enabled(cls, value: Any):
        """Parse various boolean string representations from env vars."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            cleaned = value.strip().strip('"').strip("'").lower()
            return cleaned in ('true', '1', 'yes', 'on', 'enabled')
        return bool(value)

    @field_validator("workspace_root", mode="before")
    @classmethod
    def detect_workspace_root(cls, value: Any):
        if isinstance(value, str) and value.strip():
            return value.strip()
        # Auto-detect: prefer the production droplet path, fall back to dev
        for candidate in [
            "/opt/spiderclawkpi/spider/apps/spider-kpi",
            str(ROOT_DIR),
        ]:
            if os.path.isdir(os.path.join(candidate, "frontend", "src")):
                return candidate
        return str(ROOT_DIR)

    sync_interval_minutes: int = 5
    clarity_sync_interval_minutes: int = 120  # Data is daily-granularity; polling less often avoids 429s
    historical_start_date: str = "2024-01-01"
    backfill_days: int = 824

    @field_validator("allowed_signup_domains", mode="before")
    @classmethod
    def parse_allowed_signup_domains(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return [item.strip().lower() for item in stripped.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

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
