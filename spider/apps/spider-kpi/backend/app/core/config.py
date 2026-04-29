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

    # FedEx Web Services. We default the host to the SANDBOX endpoint so a
    # half-configured deploy can't accidentally hit production data with
    # half-tested code; once the production project is approved by FedEx
    # (24-48 hr review cycle for Freight LTL), flip FEDEX_API_HOST to
    # 'apis.fedex.com' to switch over. Account number is the 9-digit
    # Spider Grills shipping account — used as both an explicit filter on
    # invoice/EOD calls and as the shipper account on Rate API queries.
    fedex_api_key: Optional[str] = None
    fedex_api_secret: Optional[str] = None
    fedex_account_number: Optional[str] = None
    fedex_api_host: str = Field(
        default='apis-sandbox.fedex.com',
        validation_alias=AliasChoices('FEDEX_API_HOST', 'FEDEX_HOST'),
    )

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

    # Shelob first-boot webhook. When KPI's stream writer detects a
    # MAC's first-ever telemetry event, it POSTs to this URL with
    # the X-Shelob-Webhook-Token header so Shelob can materialize the
    # bound persona onto the device shadow. Both env vars must be set
    # for the webhook to fire — empty either side is a clean no-op.
    shelob_first_boot_url: Optional[str] = Field(
        default="https://api.spidergrills.ai/api/devices/first-boot",
        validation_alias=AliasChoices("SHELOB_FIRST_BOOT_URL"),
    )
    shelob_webhook_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SHELOB_WEBHOOK_TOKEN", "KPI_WEBHOOK_TOKEN"),
    )

    # Microsoft Graph — multi-tenant Azure AD app for SharePoint
    # ingestion. The same CLIENT_ID/CLIENT_SECRET pair services every
    # registered tenant since the app is multi-tenant on the platform
    # side. Per-tenant config (tenant_id, display name, etc.) lives in
    # the microsoft_tenants table so adding tenants is INSERT, not deploy.
    ms_graph_client_id: Optional[str] = None
    ms_graph_client_secret: Optional[str] = None
    ms_graph_client_secret_id: Optional[str] = None
    ms_graph_default_tenant_id: Optional[str] = None
    sharepoint_sync_interval_minutes: int = 60

    # ShipStation (v1 / legacy API at ssapi.shipstation.com). Same
    # account ships products for multiple companies sharing infrastructure;
    # the connector filters on the explicit Spider store allowlist below
    # so we never ingest non-Spider rows.
    shipstation_api_key: Optional[str] = None
    shipstation_api_secret: Optional[str] = None
    shipstation_sync_interval_minutes: int = 60
    # Hours of historical lookback when seeding from empty. Default
    # 4 years covers Spider's full Shopify+Amazon shipment history.
    shipstation_initial_backfill_days: int = 4 * 365
    # Allowlist of ShipStation storeIds we're authorized to mirror.
    # Spider Amazon, Spider Grills Shopify, Spider Manual.
    shipstation_spider_store_ids: list[int] = Field(
        default_factory=lambda: [347763, 347804, 373275],
    )

    # Klaviyo (Spider Grills account — public key XEp4CM). Agustin wires
    # the native app to this account via the Klaviyo Mobile SDK; the
    # dashboard reads it as an intermediary so we get user-level device
    # ownership, app engagement, and Shopify line-item context keyed to
    # profiles without punching a direct app→dashboard route.
    klaviyo_api_key: Optional[str] = None
    klaviyo_api_revision: str = "2024-10-15"
    klaviyo_sync_interval_minutes: int = 60
    # Metric names we pull events for. Profile properties carry the
    # steady-state device/app info; this list is for time-series event
    # ingest (used by DAU/MAU, first-cook lifecycle, and cross-referencing
    # Shopify order items against telemetry).
    klaviyo_event_metrics: list[str] = Field(
        default_factory=lambda: [
            # Existing baseline — used by DAU/MAU, first-cook lifecycle,
            # and cross-referencing Shopify order items against telemetry.
            "Opened App",
            "First Cooking Session",
            "Placed Order",
            # Added 2026-04-28 after Agustín shipped app-side ingestion.
            # Each fires per-event with mac, device_type (Kettle / Huntsman
            # — Giant Huntsman discrimination still pending firmware), and
            # firmware_version. Cook Completed adds duration_seconds,
            # target_temp, and completed_normally.
            "Device Paired",
            "Device Unpaired",
            "Cook Completed",
        ],
    )

    # ClickUp (Spider Grills workspace)
    clickup_api_token: Optional[str] = None
    clickup_team_id: Optional[str] = None
    clickup_base_url: str = "https://api.clickup.com/api/v2"
    clickup_sync_interval_minutes: int = 15
    clickup_task_lookback_days: int = 120

    # App backend (spidergrills.app) — read-only sync via persistent SSH tunnel.
    # DB connection is always routed through 127.0.0.1:APP_BACKEND_TUNNEL_LOCAL_PORT,
    # which the autossh service forwards to APP_BACKEND_DB_HOST:APP_BACKEND_DB_PORT
    # on the remote side. Credentials live in the droplet .env only.
    app_backend_ssh_host: Optional[str] = None
    app_backend_ssh_user: str = "spider_tunnel"
    app_backend_ssh_port: int = 22
    app_backend_db_host: str = "127.0.0.1"
    app_backend_db_port: int = 5432
    app_backend_tunnel_local_port: int = 15432
    app_backend_db_url: Optional[str] = None  # e.g. postgresql+psycopg://user:pass@127.0.0.1:15432/dbname
    app_backend_sync_interval_minutes: int = 30
    app_backend_lookback_days: int = 120

    # Anthropic Claude — AI classification layer for Slack / ClickUp signals.
    # When ANTHROPIC_API_KEY is missing, the classifier short-circuits and the
    # rule-based detection + autodraft pipeline keeps working unchanged.
    anthropic_api_key: Optional[str] = None
    anthropic_classifier_model: str = "claude-haiku-4-5"
    anthropic_classifier_max_tokens: int = 512
    anthropic_classifier_timeout_seconds: float = 8.0

    # Slack — Spider Grills workspace listener.
    # Bot token + signing secret come from https://api.slack.com/apps (the Spider KPI Bot app).
    # Channels are auto-discovered; no channel list needs to live here.
    # Push alerts — real-time Slack DMs + daily morning email.
    push_alerts_enabled: bool = True
    push_alerts_recipient_email: str = "joseph@spidergrills.com"
    push_alerts_slack_recipient_emails: str = "joseph@spidergrills.com"  # csv
    push_alerts_max_per_hour: int = 8
    push_alerts_quiet_start_hour: int = 22  # 22:00 ET inclusive
    push_alerts_quiet_end_hour: int = 7     # 07:00 ET exclusive

    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_app_id: Optional[str] = None
    slack_team_id: Optional[str] = None
    slack_backfill_days: int = 30
    slack_message_retention_days: int = 180
    slack_discovery_interval_minutes: int = 60

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

    # Firmware OTA — AWS IoT Jobs.
    # Kill switch defaults to OFF. Every deploy endpoint refuses work unless
    # FIRMWARE_OTA_ENABLED=true. Credentials reuse aws_access_key_id /
    # aws_secret_access_key; the IoT data endpoint and region default to
    # Spider Grills' IoT account.
    firmware_ota_enabled: bool = Field(default=False, validation_alias=AliasChoices('FIRMWARE_OTA_ENABLED'))
    firmware_ota_aws_region: str = Field(default="us-east-2", validation_alias=AliasChoices('FIRMWARE_OTA_AWS_REGION'))
    firmware_ota_iot_endpoint: str = Field(
        default="a1gzggdqzynf8-ats.iot.us-east-2.amazonaws.com",
        validation_alias=AliasChoices('FIRMWARE_OTA_IOT_ENDPOINT'),
    )
    firmware_ota_circuit_breaker_threshold_pct: float = 10.0
    firmware_ota_circuit_breaker_window: int = 10
    firmware_ota_batch_cap: int = 50
    firmware_ota_single_rate_per_min: int = 5
    firmware_ota_wave_delay_seconds: int = 60
    firmware_ota_preview_token_ttl_minutes: int = 10
    firmware_ota_active_cook_window_seconds: int = 120

    @field_validator("firmware_ota_enabled", mode="before")
    @classmethod
    def parse_firmware_ota_enabled(cls, value: Any):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            cleaned = value.strip().strip('"').strip("'").lower()
            return cleaned in ('true', '1', 'yes', 'on', 'enabled')
        return bool(value)

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

    # CX operations cutover. Before this date, the team was using Freshdesk
    # inconsistently (tickets left open, no SLA, ad-hoc tagging). On and
    # after this date, operational KPIs (open_backlog, SLA breach, FRT,
    # resolution time, reopen rate, team load) filter to tickets
    # created_at >= cutover so the team's accountability window is honest.
    # Pre-cutover data stays accessible as a historical reference view.
    cx_cutover_date: str = Field(
        default="2026-05-01",
        validation_alias=AliasChoices('CX_CUTOVER_DATE'),
    )

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
