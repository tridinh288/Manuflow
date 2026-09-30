"""Password hashing (Argon2) and JWT access tokens (B16)."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

JWT_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ["sub", "exp", "iat", "jti"]


class PasswordHasher:
    def __init__(self) -> None:
        self._hash = PasswordHash((Argon2Hasher(),))
        # Verified against when the username does not exist, so an unknown user takes as
        # long to reject as a wrong password (no username probing by timing).
        self._dummy_hash = self._hash.hash(secrets.token_urlsafe(16))

    def hash(self, password: str) -> str:
        return self._hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._hash.verify(password, password_hash)

    def burn_verification_time(self, password: str) -> None:
        self._hash.verify(password, self._dummy_hash)


class InvalidTokenError(Exception):
    """The token is malformed, forged, expired or missing a required claim."""


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    expires_in: int


class TokenService:
    """HS256 access tokens with ``sub``, ``exp``, ``iat``, ``jti``.

    Expiry is checked against the injected clock rather than PyJWT's wall clock, so
    tests can pin time (D-24).
    """

    def __init__(self, secret: str, expire_minutes: int) -> None:
        self._secret = secret
        self._lifetime = timedelta(minutes=expire_minutes)

    def issue(self, user_id: int, now: datetime) -> IssuedToken:
        claims = {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int((now + self._lifetime).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._secret, algorithm=JWT_ALGORITHM)
        return IssuedToken(access_token=token, expires_in=int(self._lifetime.total_seconds()))

    def verify(self, token: str, now: datetime) -> int:
        """Return the user id in ``sub``; raise ``InvalidTokenError`` otherwise."""
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                options={
                    "require": _REQUIRED_CLAIMS,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("token rejected") from exc

        expires_at = claims["exp"]
        subject = claims["sub"]
        if not isinstance(expires_at, int) or now.timestamp() >= expires_at:
            raise InvalidTokenError("token expired")
        if not isinstance(subject, str) or not subject.isdigit():
            raise InvalidTokenError("invalid subject")
        return int(subject)
