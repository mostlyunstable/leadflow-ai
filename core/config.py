"""
Production Configuration Management.
Uses Pydantic Settings for strictly validated, environment-aware configuration.
Enforces fail-closed rules in production environments.
"""

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application Environment ──────────────────────────────────────────────
    ENVIRONMENT: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description="Application environment (development, testing, staging, production)",
    )
    APP_NAME: str = "LeadFlow AI"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = Field(default=False)
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)

    # ── Security & Authentication ────────────────────────────────────────────
    # In production, SECRET_KEY and ENCRYPTION_KEY must be supplied and secure.
    SECRET_KEY: str = Field(
        default="leadflow-dev-secret-key-change-in-production-min32chars",
        description="Secret key for JWT generation and session signing",
    )
    ENCRYPTION_KEY: str = Field(
        default="54eO49uV2JgI7e9FqQ3P6x7V0A5b2N1M4K8L9O2P3Q=",  # Default 32-byte urlsafe b64
        description="32-byte url-safe base64 key for Fernet symmetric encryption of OAuth tokens",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    DASHBOARD_API_KEY: Optional[str] = Field(
        default=None,
        description="Fallback API key for service-to-service automation",
    )
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:8000", "http://127.0.0.1:8000"],
    )

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="sqlite:///./outreach.db",
        description="Database connection string (PostgreSQL for production)",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300

    # ── Queue & Cache (Redis) ────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for distributed job queue and rate limiting",
    )
    QUEUE_JOB_TIMEOUT_SECONDS: int = 300
    JOB_LEASE_SECONDS: int = 60
    MAX_JOB_RETRIES: int = 3

    # ── Rate Limiting ────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 120
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    # ── Email Sending & Policy ───────────────────────────────────────────────
    DAILY_SEND_LIMIT: int = 50
    HOURLY_SEND_LIMIT: int = 15
    MIN_DELAY_SECONDS: int = 30
    MAX_DELAY_SECONDS: int = 120
    MAX_RETRIES: int = 3
    FOLLOWUP_1_DAYS: int = 2
    FOLLOWUP_2_DAYS: int = 5
    REPLY_CHECK_INTERVAL_MINUTES: int = 5
    MAX_BOUNCE_RATE_PERCENT: float = 5.0
    UNSUBSCRIBE_FOOTER: str = (
        "\n\n---\nIf you'd prefer not to hear from me, just reply 'unsubscribe' "
        "and I'll remove you immediately."
    )

    # ── Gmail OAuth & Credentials ────────────────────────────────────────────
    GMAIL_CREDENTIALS_FILE: str = str(BASE_DIR / "config" / "credentials" / "credentials.json")
    GMAIL_SCOPES: List[str] = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    # ── AI & LLM Engine ──────────────────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = Field(default=None)
    OPENAI_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    OPENAI_MODEL: str = "meta/llama-3.1-70b-instruct"
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_MAX_TOKENS: int = 500
    OPENAI_TIMEOUT_SECONDS: int = 30

    # ── Website Scraping & Enrichment ────────────────────────────────────────
    SCRAPE_TIMEOUT: int = 10
    SCRAPE_MAX_REDIRECTS: int = 3
    SCRAPE_MAX_CONTENT_LENGTH: int = 3 * 1024 * 1024  # 3 MB
    SCRAPE_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 LeadFlowBot/2.0"
    )
    BROWSER_HEADLESS: bool = True
    BROWSER_TIMEOUT_MS: int = 15000

    # ── Observability & Logging ──────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = BASE_DIR / "logs"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 5

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    def validate_production_readiness(self):
        """
        Fail closed in production: refuse to start if sensitive parameters are missing,
        insecure, or using SQLite in production.
        """
        if self.ENVIRONMENT == AppEnvironment.PRODUCTION:
            errors = []
            if not self.SECRET_KEY or "dev-secret" in self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                errors.append("Production requires a strong SECRET_KEY (min 32 characters)")
            if not self.ENCRYPTION_KEY or "54eO49uV2JgI7e9FqQ3P6x7V0A5b2N1M4K8L9O2P3Q=" in self.ENCRYPTION_KEY:
                errors.append("Production requires a custom 32-byte ENCRYPTION_KEY for credentials at rest")
            if "sqlite" in self.DATABASE_URL.lower():
                errors.append("Production requires PostgreSQL (SQLite is not permitted in production)")
            if not self.DASHBOARD_API_KEY and not self.SECRET_KEY:
                errors.append("Production requires an authentication secret key")
            if errors:
                raise ValueError(
                    "Production configuration validation failed:\n - " + "\n - ".join(errors)
                )


# Global settings instance
settings = Settings()
# Create logs directory
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
