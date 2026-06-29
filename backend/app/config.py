"""Application configuration.

All configuration is environment-driven so the same image can be deployed
anywhere (local, Railway, etc.) by changing variables only -- never code.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    app_env: str = "dev"

    # Storage. SQLite for local/demo; Postgres (DATABASE_URL) for production.
    database_url: str = "sqlite:///./better_email.db"

    # Security
    secret_key: str = "dev-only-insecure-change-me"
    owner_api_key: str = "dev-owner-key-change-me"
    owner_email: str = "owner@example.com"
    cors_origins: str = "http://localhost:5173"

    # LLM
    llm_provider: str = "mock"
    llm_model: str = "mock-small"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    llm_redact_pii: bool = True

    # Connector
    connector: str = "mock"
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_redirect_uri: str = "http://localhost:8000/api/connectors/gmail/callback"

    # Triage
    forgotten_after_hours: int = 24

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        """Fail fast on insecure production configuration."""
        if self.is_prod:
            insecure = {"dev-only-insecure-change-me", "", "change-me"}
            if self.secret_key in insecure:
                raise RuntimeError(
                    "SECRET_KEY must be set to a strong value in production."
                )
            if self.owner_api_key in {"dev-owner-key-change-me", "", "change-me"}:
                raise RuntimeError(
                    "OWNER_API_KEY must be set to a strong value in production."
                )
            if "*" in self.cors_origin_list:
                raise RuntimeError("CORS_ORIGINS must not be '*' in production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
