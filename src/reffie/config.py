from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    hubspot_token: str
    jwt_secret: str


settings = Settings()  # type: ignore[call-arg]
