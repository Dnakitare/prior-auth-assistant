"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Keys
    anthropic_api_key: str = ""

    # AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/prior_auth"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Application
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"


settings = Settings()
