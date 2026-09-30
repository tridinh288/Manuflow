"""Idempotency keys (D-22): key format and request fingerprint, pure functions."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from typing import Any

from app.domain.errors import BusinessValidationError

# UUIDs are recommended; any opaque token of safe characters is accepted.
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def validate_idempotency_key(key: str) -> None:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise BusinessValidationError(
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must be 8-128 characters: letters, digits, '-' or '_'.",
        )


def request_fingerprint(method: str, path: str, payload: Any, secret: bytes) -> str:
    """HMAC-SHA256 of method, path and the validated body in canonical JSON.

    Key order and whitespace do not matter; any change of value, path or method does.
    Keyed with a server secret because bodies may contain passwords: a plain hash stored
    in the database could be brute-forced offline.
    """
    canonical = json.dumps(
        {"method": method.upper(), "path": path, "body": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()


def is_expired(created_at: datetime, now: datetime, ttl: timedelta) -> bool:
    """C-08: a key older than the TTL is treated as if it did not exist."""
    return now - created_at >= ttl
