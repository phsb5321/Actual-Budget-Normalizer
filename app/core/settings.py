"""Configuration and environment settings for the Actual Budget Normalizer."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for the Actual Budget Normalizer."""

    groq_api_key: str
    deepseek_model: str = "deepseek-r1-distill-llama-70b"
    deepseek_temperature: float = 0.6
    deepseek_max_completion_tokens: int = 4096
    deepseek_top_p: float = 0.95
    deepseek_stream: bool = True
    deepseek_stop: list[str] | None = None
    categories_file: str = "categories.json"
    payees_file: str = "payees.json"
    database_url: str = "jobs.db"
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


def get_settings() -> "Settings":
    """Return an instance of the application settings."""
    return Settings()
