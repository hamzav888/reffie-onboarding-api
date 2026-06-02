import json as _json
from typing import Any

from pydantic import field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class _CommaListEnvSource(EnvSettingsSource):
    """EnvSettingsSource that falls back to comma-separated parsing for list fields."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return _json.loads(value)
        except (ValueError, TypeError):
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            raise


class _CommaListDotEnvSource(DotEnvSettingsSource):
    """DotEnvSettingsSource that falls back to comma-separated parsing for list fields."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return _json.loads(value)
        except (ValueError, TypeError):
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            raise


class Settings(BaseSettings):
    # extra='ignore' lets Railway/OS platform env vars pass through without crashing.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    hubspot_token: str
    hubspot_base_url: str = "https://api.hubapi.com"
    google_client_id: str
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://reffie-onboarding.vercel.app",
    ]
    # HubSpot webhook HMAC secret. Empty string disables webhook processing (returns 503).
    hubspot_webhook_secret: str = ""
    # Pipeline-specific stage IDs that represent Closed Won (comma-separated in env).
    hubspot_closed_won_stage_ids: list[str] = []

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CommaListEnvSource(settings_cls),
            _CommaListDotEnvSource(settings_cls, env_file=".env", env_file_encoding="utf-8"),
            file_secret_settings,
        )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> Any:
        """Split a comma-separated string into a list; pass lists through unchanged."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("hubspot_closed_won_stage_ids", mode="before")
    @classmethod
    def _parse_stage_ids(cls, v: Any) -> Any:
        """Split a comma-separated string into a list; pass lists through unchanged."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


settings = Settings()  # type: ignore[call-arg]


def get_settings() -> Settings:
    """FastAPI dependency that returns the application settings singleton."""
    return settings
