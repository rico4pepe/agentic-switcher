"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    aws_region: str | None = None
    bedrock_model_id: str | None = None
    vendor_a_api_key: str = "vendor_a_test_key"
    vendor_b_api_key: str = "vendor_b_test_key"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
