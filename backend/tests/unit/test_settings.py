"""B16: secrets and CORS are validated at startup."""

import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Environment, Settings

DB_URL = "mysql+pymysql://user:pass@localhost/db"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": DB_URL, "migration_database_url": DB_URL}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("env", [Environment.TEST, Environment.PROD])
def test_b16_default_jwt_secret_rejected_outside_dev(env: Environment) -> None:
    with pytest.raises(ValidationError, match="non-default"):
        _settings(env=env, jwt_secret=DEV_JWT_SECRET)


def test_b16_default_jwt_secret_allowed_in_dev() -> None:
    assert _settings(env=Environment.DEV, jwt_secret=DEV_JWT_SECRET).env is Environment.DEV


def test_b16_short_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        _settings(env=Environment.DEV, jwt_secret="too-short")


def test_b16_jwt_secret_error_does_not_leak_value() -> None:
    secret = "short-but-sensitive"
    with pytest.raises(ValidationError) as exc_info:
        _settings(env=Environment.PROD, jwt_secret=secret)
    assert secret not in str(exc_info.value)


def test_b16_wildcard_cors_origin_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit origins"):
        _settings(cors_origins=["*"])


def test_d24_risk_thresholds_have_spec_defaults() -> None:
    settings = _settings()
    assert str(settings.risk_gap) == "0.20"
    assert settings.due_soon_hours == 48
    assert settings.shortage_alert_days == 3
    assert settings.jwt_expire_minutes == 30
    assert settings.idempotency_ttl_hours == 24
