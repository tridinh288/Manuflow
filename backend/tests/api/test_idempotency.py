"""D-22 / C-03 / C-08 through the API (test 12 of B15, sequential part)."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.idempotency import RequiredIdempotency
from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User

USERS = "/api/v1/users"
KEY = "3f2b8c1e-9d4a-4c7b-8e2f-1a2b3c4d5e6f"
PASSWORD = "brand-new-password-1"


def body(username: str = "wh02", **overrides: Any) -> dict[str, Any]:
    return {
        "username": username,
        "password": PASSWORD,
        "full_name": "Warehouse Two",
        "role": "WAREHOUSE",
        **overrides,
    }


def with_key(headers: dict[str, str], key: str = KEY) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key}


def count(session: Session, model: type, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


@pytest.fixture
def admin(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.ADMIN)
    return headers


def test_d22_same_key_and_body_replays_the_first_response_once(
    db_client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    first = db_client.post(USERS, json=body(), headers=with_key(admin))
    second = db_client.post(USERS, json=body(), headers=with_key(admin))

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    # The effect happened exactly once.
    assert count(db_session, User, User.username == "wh02") == 1
    assert count(db_session, AuditLog, AuditLog.action == "USER_CREATED") == 1
    assert count(db_session, IdempotencyKey) == 1


def test_d22_key_order_in_body_does_not_matter(
    db_client: TestClient, admin: dict[str, str]
) -> None:
    db_client.post(USERS, json=body(), headers=with_key(admin))
    reordered = dict(reversed(list(body().items())))
    response = db_client.post(USERS, json=reordered, headers=with_key(admin))
    assert response.headers.get("Idempotent-Replayed") == "true"


def test_d22_same_key_with_different_body_is_422(
    db_client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    db_client.post(USERS, json=body(), headers=with_key(admin))
    response = db_client.post(USERS, json=body("wh03"), headers=with_key(admin))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert count(db_session, User, User.username == "wh03") == 0


def test_d22_same_key_on_another_endpoint_is_422(
    db_client: TestClient, admin: dict[str, str], user_factory
) -> None:
    target = user_factory(role=Role.WAREHOUSE)
    db_client.post(USERS, json=body(), headers=with_key(admin))
    response = db_client.patch(
        f"{USERS}/{target.id}", json={"full_name": "X"}, headers=with_key(admin)
    )
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_d22_keys_are_scoped_per_user(db_client: TestClient, login_as) -> None:
    admin_a, admin_b = login_as(Role.ADMIN), login_as(Role.ADMIN)
    first = db_client.post(USERS, json=body("wh10"), headers=with_key(admin_a))
    second = db_client.post(USERS, json=body("wh11"), headers=with_key(admin_b))
    assert (first.status_code, second.status_code) == (201, 201)
    assert "Idempotent-Replayed" not in second.headers


def test_c03_failed_request_is_not_stored_and_can_be_retried_with_the_same_key(
    db_client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    assert db_client.post(USERS, json=body("taken"), headers=admin).status_code == 201

    failed = db_client.post(USERS, json=body("taken"), headers=with_key(admin))
    assert failed.status_code == 409
    assert count(db_session, IdempotencyKey) == 0  # rolled back with the failed change

    retried = db_client.post(USERS, json=body("free"), headers=with_key(admin))
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers


def test_c08_expired_key_is_treated_as_new(
    db_client: TestClient, db_session: Session, user_factory, clock: FixedClock
) -> None:
    user_factory("admin01", role=Role.ADMIN)

    def fresh_admin_headers() -> dict[str, str]:
        response = db_client.post(
            "/api/v1/auth/login",
            json={"username": "admin01", "password": "correct-horse-battery-staple"},
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    db_client.post(USERS, json=body("wh20"), headers=with_key(fresh_admin_headers()))

    clock.advance(timedelta(hours=23, minutes=59))
    within_ttl = db_client.post(USERS, json=body("wh21"), headers=with_key(fresh_admin_headers()))
    assert within_ttl.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    clock.advance(timedelta(minutes=1))
    after_ttl = db_client.post(USERS, json=body("wh21"), headers=with_key(fresh_admin_headers()))
    assert after_ttl.status_code == 201
    assert "Idempotent-Replayed" not in after_ttl.headers
    assert count(db_session, IdempotencyKey) == 1  # the expired row was replaced


def test_d22_patch_replay_does_not_repeat_the_audit_row(
    db_client: TestClient, db_session: Session, admin: dict[str, str], user_factory
) -> None:
    target = user_factory(role=Role.WAREHOUSE)
    url = f"{USERS}/{target.id}"
    for _ in range(2):
        response = db_client.patch(
            url, json={"role": "PRODUCTION_MANAGER"}, headers=with_key(admin)
        )
        assert response.status_code == 200
    assert count(db_session, AuditLog, AuditLog.action == "USER_ROLE_CHANGED") == 1


@pytest.mark.parametrize("key", ["short", "x" * 129, "bad key!"])
def test_d22_malformed_key_is_422(db_client: TestClient, admin: dict[str, str], key: str) -> None:
    response = db_client.post(USERS, json=body(), headers=with_key(admin, key))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_b16_stored_key_row_holds_no_password(
    db_client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    db_client.post(USERS, json=body(), headers=with_key(admin))
    row = db_session.scalars(select(IdempotencyKey)).one()
    stored = f"{row.request_hash} {row.response_body}"
    assert PASSWORD not in stored
    assert "password" not in stored.lower()


def test_d22_required_key_missing_is_422(app: FastAPI, db_client: TestClient) -> None:
    @app.post("/_probe/required-key")
    def probe(idempotent: RequiredIdempotency) -> dict[str, str | None]:
        return {"key": idempotent.key}

    response = db_client.post("/_probe/required-key")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    accepted = db_client.post("/_probe/required-key", headers={"Idempotency-Key": KEY})
    assert accepted.json() == {"key": KEY}
