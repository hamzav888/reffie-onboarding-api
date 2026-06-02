from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    hubspot_token: str
    hubspot_base_url: str = "https://api.hubapi.com"
    jwt_secret: str
    google_client_id: str
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://reffie-onboarding.vercel.app",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> Any:
        """Split a comma-separated string into a list; pass lists through unchanged."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


settings = Settings()  # type: ignore[call-arg]


def get_settings() -> Settings:
    """FastAPI dependency that returns the application settings singleton."""
    return settings
