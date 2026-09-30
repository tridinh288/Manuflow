"""D-22 / C-08: key format, request fingerprint and expiry as pure functions."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import BusinessValidationError
from app.domain.idempotency import is_expired, request_fingerprint, validate_idempotency_key

SECRET = b"server-side-fingerprint-secret"


@pytest.mark.parametrize(
    "key", ["3f2b8c1e-9d4a-4c7b-8e2f-1a2b3c4d5e6f", "retry_key_0001", "a" * 128]
)
def test_d22_well_formed_keys_accepted(key: str) -> None:
    validate_idempotency_key(key)


@pytest.mark.parametrize("key", ["short", "a" * 129, "has space here", "semi;colon-key", ""])
def test_d22_malformed_keys_rejected(key: str) -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_idempotency_key(key)
    assert exc_info.value.code == "INVALID_IDEMPOTENCY_KEY"


def test_d22_fingerprint_ignores_key_order() -> None:
    first = request_fingerprint("POST", "/api/v1/users", {"a": 1, "b": {"x": 1, "y": 2}}, SECRET)
    second = request_fingerprint("post", "/api/v1/users", {"b": {"y": 2, "x": 1}, "a": 1}, SECRET)
    assert first == second


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/v1/users", {"a": 1}),
        ("POST", "/api/v1/users/2", {"a": 1}),
        ("POST", "/api/v1/users", {"a": 2}),
        ("POST", "/api/v1/users", {"a": "1"}),
    ],
    ids=["method", "path", "value", "type"],
)
def test_d22_fingerprint_changes_with_method_path_or_body(
    method: str, path: str, body: dict[str, object]
) -> None:
    base = request_fingerprint("POST", "/api/v1/users", {"a": 1}, SECRET)
    assert request_fingerprint(method, path, body, SECRET) != base


def test_b16_fingerprint_is_keyed_so_passwords_cannot_be_brute_forced_offline() -> None:
    body = {"username": "wh02", "password": "guessable-password"}
    fingerprint = request_fingerprint("POST", "/api/v1/users", body, SECRET)
    unkeyed = hashlib.sha256(
        json.dumps(
            {"method": "POST", "path": "/api/v1/users", "body": body},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert fingerprint != unkeyed
    assert fingerprint != request_fingerprint("POST", "/api/v1/users", body, b"other-secret")


def test_c08_key_expires_exactly_at_ttl() -> None:
    created = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    ttl = timedelta(hours=24)
    assert not is_expired(created, created + ttl - timedelta(microseconds=1), ttl)
    assert is_expired(created, created + ttl, ttl)
