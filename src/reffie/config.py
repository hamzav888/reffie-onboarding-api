from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    hubspot_token: str
    hubspot_base_url: str = "https://api.hubapi.com"
    jwt_secret: str
    google_client_id: str


settings = Settings()  # type: ignore[call-arg]
