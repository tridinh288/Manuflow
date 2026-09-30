"""Audit vocabulary and payload preparation (BR-AUD-01, BR-AUD-03, BR-AUD-05)."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

# BR-AUD-05. A key is removed when its lower-cased name *contains* one of these, so
# variants such as "new_password", "access_token" or "jwt_secret" are covered too.
SENSITIVE_KEY_PARTS = ("password", "token", "authorization", "secret", "api_key")


class AuditAction(StrEnum):
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"


class AuditEntity(StrEnum):
    USER = "user"


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def to_audit_payload(value: Any) -> Any:
    """JSON-safe copy with sensitive keys removed at every depth.

    Decimals become strings (never floats), datetimes ISO 8601, enums their value.
    """
    if isinstance(value, Mapping):
        return {
            str(key): to_audit_payload(item)
            for key, item in value.items()
            if not is_sensitive_key(str(key))
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [to_audit_payload(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def changed_fields(
    old: Mapping[str, Any], new: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only the fields whose value differs, as (old_value, new_value) (BR-AUD-03)."""
    keys = [key for key in new if old.get(key) != new[key]]
    return {key: old.get(key) for key in keys}, {key: new[key] for key in keys}
