"""B16: Argon2 password hashes and HS256 access tokens."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import InvalidTokenError, PasswordHasher, TokenService

SECRET = "unit-test-secret-0123456789abcdefghij"
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def hasher() -> PasswordHasher:
    return PasswordHasher()


def test_b16_password_stored_as_argon2_hash(hasher: PasswordHasher) -> None:
    password_hash = hasher.hash("correct-horse-battery")
    assert password_hash.startswith("$argon2")
    assert "correct-horse-battery" not in password_hash
    assert hasher.verify("correct-horse-battery", password_hash)
    assert not hasher.verify("wrong-password!", password_hash)


def test_b16_token_has_required_claims_and_no_role() -> None:
    issued = TokenService(SECRET, 30).issue(42, NOW)
    claims = jwt.decode(
        issued.access_token, SECRET, algorithms=["HS256"], options={"verify_exp": False}
    )
    assert set(claims) == {"sub", "exp", "iat", "jti"}
    assert claims["sub"] == "42"
    assert claims["exp"] - claims["iat"] == 30 * 60 == issued.expires_in


def test_b16_token_verifies_until_expiry() -> None:
    service = TokenService(SECRET, 30)
    token = service.issue(42, NOW).access_token
    assert service.verify(token, NOW + timedelta(minutes=29, seconds=59)) == 42
    with pytest.raises(InvalidTokenError):
        service.verify(token, NOW + timedelta(minutes=30))


def test_b16_each_token_has_unique_jti() -> None:
    service = TokenService(SECRET, 30)
    first, second = (
        jwt.decode(service.issue(1, NOW).access_token, options={"verify_signature": False})
        for _ in range(2)
    )
    assert first["jti"] != second["jti"]


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode({"sub": "1", "iat": 0, "exp": 2**40, "jti": "x"}, "another-secret-" * 3),
        jwt.encode({"sub": "1", "iat": 0, "exp": 2**40}, SECRET),  # no jti
        jwt.encode({"sub": "admin", "iat": 0, "exp": 2**40, "jti": "x"}, SECRET),
        jwt.encode({"sub": "1", "iat": 0, "exp": 2**40, "jti": "x"}, SECRET, algorithm="HS512"),
        jwt.encode({"sub": "1", "iat": 0, "exp": 2**40, "jti": "x"}, None, algorithm="none"),
    ],
    ids=["garbage", "wrong-secret", "missing-jti", "non-numeric-sub", "other-alg", "alg-none"],
)
def test_b16_invalid_tokens_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        TokenService(SECRET, 30).verify(token, NOW)
