"""Application settings, read only from environment variables (B14)."""

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only acceptable when ENV=dev; the app refuses to start with it anywhere else (B16).
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-do-not-use"  # noqa: S105
MIN_JWT_SECRET_BYTES = 32


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    # hide_input_in_errors: a failed validation must not print secrets or DB passwords.
    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    env: Environment = Environment.DEV
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr
    migration_database_url: SecretStr

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_expire_minutes: int = Field(default=30, gt=0)
    cors_origins: list[str] = Field(default_factory=list)

    idempotency_ttl_hours: int = Field(default=24, gt=0)

    # Phase 9 assistant (B17): provider and model are configuration; without a key the
    # assistant is off and the rest of the system is unaffected.
    # "anthropic" needs ASSISTANT_API_KEY; "ollama" is a free local model (no key) reached
    # through Ollama's OpenAI-compatible API at ASSISTANT_BASE_URL.
    assistant_provider: Literal["anthropic", "ollama"] = "anthropic"
    assistant_api_key: SecretStr | None = None
    assistant_model: str = Field(default="claude-sonnet-5", min_length=1, max_length=100)
    assistant_base_url: str = "http://host.docker.internal:11434/v1"
    assistant_max_steps: int = Field(default=6, ge=1, le=12)

    # Risk thresholds (D-24).
    risk_gap: Decimal = Field(default=Decimal("0.20"), gt=0, lt=1)
    due_soon_hours: int = Field(default=48, gt=0)
    shortage_alert_days: int = Field(default=3, gt=0)

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, origins: list[str]) -> list[str]:
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return origins

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> Self:
        secret = self.jwt_secret.get_secret_value()
        if len(secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        if self.env is not Environment.DEV and secret == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set to a non-default value outside ENV=dev")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields come from the environment
