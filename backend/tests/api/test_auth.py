"""BR-AUTH-01, 04, 05 and C-01 through the HTTP API."""

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.core.security import TokenService
from app.models.user import User

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
PASSWORD = "correct-horse-battery-staple"
GENERIC_MESSAGE = "Invalid username or password."


def login(client: TestClient, username: str, password: str = PASSWORD) -> httpx.Response:
    return client.post(LOGIN, json={"username": username, "password": password})


def token_for(client: TestClient, username: str) -> str:
    response = login(client, username)
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def update_user(session: Session, user: User, **values: object) -> None:
    if session.in_transaction():
        session.commit()
    with session.begin():
        for name, value in values.items():
            setattr(user, name, value)


def assert_invalid_credentials(response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("INVALID_CREDENTIALS", GENERIC_MESSAGE)


# --- Login ----------------------------------------------------------------------------


def test_br_auth_01_login_returns_bearer_token_for_the_user(
    db_client: TestClient, user_factory, app: FastAPI, clock: FixedClock
) -> None:
    user = user_factory("pm01")
    response = login(db_client, "pm01")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert app.state.token_service.verify(body["access_token"], clock.now()) == user.id


@pytest.mark.parametrize("scenario", ["wrong_password", "unknown_user", "inactive_user"])
def test_br_auth_05_every_login_failure_gets_the_same_generic_error(
    db_client: TestClient, user_factory, scenario: str
) -> None:
    user_factory("wh01", role=Role.WAREHOUSE, active=scenario != "inactive_user")
    username = "ghost" if scenario == "unknown_user" else "wh01"
    password = "not-the-password" if scenario == "wrong_password" else PASSWORD
    assert_invalid_credentials(login(db_client, username, password))


def test_br_auth_01_login_rejects_identity_fields_in_body(
    db_client: TestClient, user_factory
) -> None:
    user_factory("pm01")
    response = db_client.post(
        LOGIN, json={"username": "pm01", "password": PASSWORD, "role": "ADMIN", "user_id": 1}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert PASSWORD not in response.text


# --- Lockout (BR-AUTH-05, C-06) -------------------------------------------------------


def test_br_auth_05_five_failures_lock_account_for_15_minutes(
    db_client: TestClient, user_factory, clock: FixedClock
) -> None:
    user_factory("wh01", role=Role.WAREHOUSE)
    for _ in range(5):
        assert_invalid_credentials(login(db_client, "wh01", "wrong-password"))

    # Correct password is refused while locked, with the same generic message.
    assert_invalid_credentials(login(db_client, "wh01"))
    clock.advance(timedelta(minutes=14, seconds=59))
    assert_invalid_credentials(login(db_client, "wh01"))

    clock.advance(timedelta(seconds=1))
    assert login(db_client, "wh01").status_code == 200


def test_br_auth_05_failures_outside_the_window_do_not_lock(
    db_client: TestClient, user_factory, clock: FixedClock
) -> None:
    user_factory("wh01", role=Role.WAREHOUSE)
    for _ in range(4):
        login(db_client, "wh01", "wrong-password")
    clock.advance(timedelta(minutes=15))
    login(db_client, "wh01", "wrong-password")
    assert login(db_client, "wh01").status_code == 200


def test_br_auth_05_successful_login_resets_the_failure_count(
    db_client: TestClient, user_factory
) -> None:
    user_factory("wh01", role=Role.WAREHOUSE)
    for _ in range(2):
        for _ in range(4):
            login(db_client, "wh01", "wrong-password")
        assert login(db_client, "wh01").status_code == 200


# --- Token authentication -------------------------------------------------------------


def test_br_auth_01_me_returns_caller_with_role_permissions(
    db_client: TestClient, user_factory
) -> None:
    worker = user_factory("worker01", role=Role.WORKER)
    response = db_client.get(ME, headers=bearer(token_for(db_client, "worker01")))
    assert response.status_code == 200
    assert response.json() == {
        "id": worker.id,
        "username": "worker01",
        "full_name": "Test User",
        "role": "WORKER",
        "work_center_id": worker.work_center_id,
        "permissions": ["master:read", "operation:report", "order:read"],
    }


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, "NOT_AUTHENTICATED"),
        ({"Authorization": "Basic cG0wMTpwYXNz"}, "NOT_AUTHENTICATED"),
        ({"Authorization": "Bearer not-a-jwt"}, "INVALID_TOKEN"),
    ],
    ids=["missing", "wrong-scheme", "garbage"],
)
def test_br_auth_01_missing_or_invalid_token_is_401(
    db_client: TestClient, headers: dict[str, str], code: str
) -> None:
    response = db_client.get(ME, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == code


def test_br_auth_01_token_signed_with_another_secret_is_rejected(
    db_client: TestClient, user_factory, clock: FixedClock
) -> None:
    user = user_factory("pm01")
    forged = TokenService("attacker-controlled-secret-0123456789", 30).issue(user.id, clock.now())
    assert db_client.get(ME, headers=bearer(forged.access_token)).status_code == 401


def test_b16_token_expires_after_30_minutes(
    db_client: TestClient, user_factory, clock: FixedClock
) -> None:
    user_factory("pm01")
    headers = bearer(token_for(db_client, "pm01"))
    clock.advance(timedelta(minutes=29, seconds=59))
    assert db_client.get(ME, headers=headers).status_code == 200
    clock.advance(timedelta(seconds=1))
    assert db_client.get(ME, headers=headers).json()["error"]["code"] == "INVALID_TOKEN"


def test_br_auth_04_deactivated_user_token_rejected_on_next_request(
    db_client: TestClient, db_session: Session, user_factory
) -> None:
    user = user_factory("pm01")
    headers = bearer(token_for(db_client, "pm01"))
    assert db_client.get(ME, headers=headers).status_code == 200

    update_user(db_session, user, active=False)
    assert db_client.get(ME, headers=headers).status_code == 401


def test_c01_role_change_applies_to_an_existing_token(
    db_client: TestClient, db_session: Session, user_factory
) -> None:
    user = user_factory("pm01")
    headers = bearer(token_for(db_client, "pm01"))

    update_user(db_session, user, role=Role.ADMIN)
    body = db_client.get(ME, headers=headers).json()
    assert body["role"] == "ADMIN"
    assert "users:manage" in body["permissions"]
    assert "order:plan" not in body["permissions"]
