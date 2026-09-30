"""BR-AUD-03 / BR-AUD-05: audit payloads are JSON-safe and never carry secrets."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.permissions import Role
from app.domain.audit import changed_fields, is_sensitive_key, to_audit_payload


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "password_hash",
        "token",
        "authorization",
        "secret",
        "api_key",
        "new_password",
        "Access_Token",
        "AUTHORIZATION",
        "jwt_secret",
    ],
)
def test_br_aud_05_sensitive_keys_detected(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["username", "role", "quantity", "reason", "material_code"])
def test_br_aud_05_ordinary_keys_kept(key: str) -> None:
    assert not is_sensitive_key(key)


def test_br_aud_05_sensitive_keys_removed_at_every_depth() -> None:
    payload = {
        "username": "pm01",
        "password": "hunter2-hunter2",
        "nested": {"access_token": "abc", "api_key": "k", "keep": 1},
        "items": [{"Authorization": "Bearer x", "code": "BOLT-M8"}],
    }
    assert to_audit_payload(payload) == {
        "username": "pm01",
        "nested": {"keep": 1},
        "items": [{"code": "BOLT-M8"}],
    }


def test_br_aud_03_values_become_json_safe_without_floats() -> None:
    payload = {
        "quantity": Decimal("204.000"),
        "at": datetime(2026, 9, 30, 7, 32, 10, 123456, tzinfo=UTC),
        "role": Role.WAREHOUSE,
        "codes": ("A", "B"),
    }
    assert to_audit_payload(payload) == {
        "quantity": "204.000",
        "at": "2026-09-30T07:32:10.123456+00:00",
        "role": "WAREHOUSE",
        "codes": ["A", "B"],
    }


def test_br_aud_03_only_changed_fields_are_kept() -> None:
    old = {"name": "Frame", "active": True, "unit": "pcs"}
    new = {"name": "Frame A", "active": True, "unit": "pcs"}
    assert changed_fields(old, new) == ({"name": "Frame"}, {"name": "Frame A"})
