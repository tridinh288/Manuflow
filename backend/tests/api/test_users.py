"""User administration: validation, D-18, BR-AUTH-04 and BR-AUD-01 audit rows."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.work_center import WorkCenter

USERS = "/api/v1/users"
NEW_PASSWORD = "brand-new-password-1"


def new_user(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "username": "wh02",
        "password": NEW_PASSWORD,
        "full_name": "Warehouse Two",
        "role": "WAREHOUSE",
    }
    body.update(overrides)
    return body


def login(client: TestClient, username: str, password: str) -> httpx.Response:
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def audit_rows(session: Session, action: str) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.fixture
def admin(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.ADMIN)
    return headers


# --- Create ---------------------------------------------------------------------------


def test_create_user_returns_user_without_secrets_and_user_can_log_in(
    db_client: TestClient, admin: dict[str, str]
) -> None:
    response = db_client.post(USERS, json=new_user(), headers=admin)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "username",
        "full_name",
        "role",
        "work_center_id",
        "active",
        "locked_until",
    }
    assert (body["username"], body["role"], body["active"]) == ("wh02", "WAREHOUSE", True)
    assert login(db_client, "wh02", NEW_PASSWORD).status_code == 200


def test_create_worker_with_active_work_center(
    db_client: TestClient, admin: dict[str, str], work_center_factory
) -> None:
    work_center = work_center_factory("WC-WELD")
    response = db_client.post(
        USERS, json=new_user(role="WORKER", work_center_id=work_center.id), headers=admin
    )
    assert response.status_code == 201
    assert response.json()["work_center_id"] == work_center.id


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"role": "WORKER"}, 422, "WORK_CENTER_REQUIRED"),
        ({"password": "short-pw1"}, 422, "VALIDATION_ERROR"),
        ({"username": "no spaces"}, 422, "VALIDATION_ERROR"),
        ({"role": "SUPERUSER"}, 422, "VALIDATION_ERROR"),
        ({"created_by": 1}, 422, "VALIDATION_ERROR"),
        ({"role": "WORKER", "work_center_id": 999_999}, 422, "WORK_CENTER_NOT_FOUND"),
    ],
    ids=["worker-no-wc", "short-password", "bad-username", "bad-role", "extra-field", "wc-404"],
)
def test_create_user_rejects_invalid_input(
    db_client: TestClient,
    admin: dict[str, str],
    overrides: dict[str, Any],
    status: int,
    code: str,
) -> None:
    response = db_client.post(USERS, json=new_user(**overrides), headers=admin)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert NEW_PASSWORD not in response.text


def test_d18_non_worker_cannot_have_work_center(
    db_client: TestClient, admin: dict[str, str], work_center_factory
) -> None:
    work_center = work_center_factory()
    response = db_client.post(USERS, json=new_user(work_center_id=work_center.id), headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WORK_CENTER_NOT_ALLOWED"


def test_br_md_04_inactive_work_center_cannot_be_assigned(
    db_client: TestClient, db_session: Session, admin: dict[str, str], work_center_factory
) -> None:
    work_center: WorkCenter = work_center_factory()
    with db_session.begin():
        work_center.active = False
    response = db_client.post(
        USERS, json=new_user(role="WORKER", work_center_id=work_center.id), headers=admin
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORK_CENTER_INACTIVE"


@pytest.mark.parametrize("username", ["wh02", "WH02"])
def test_duplicate_username_is_409_case_insensitively(
    db_client: TestClient, admin: dict[str, str], username: str
) -> None:
    assert db_client.post(USERS, json=new_user(), headers=admin).status_code == 201
    response = db_client.post(USERS, json=new_user(username=username), headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


def test_br_aud_01_user_creation_is_audited_without_password(
    db_client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    user_id = db_client.post(USERS, json=new_user(), headers=admin).json()["id"]
    [row] = audit_rows(db_session, "USER_CREATED")
    assert (row.entity_type, row.entity_id) == ("user", user_id)
    assert row.actor_username is not None and row.actor_username != "wh02"
    assert row.new_value == {
        "username": "wh02",
        "full_name": "Warehouse Two",
        "role": "WAREHOUSE",
        "work_center_id": None,
        "active": True,
    }


# --- List -----------------------------------------------------------------------------


def test_list_users_is_paginated(
    db_client: TestClient, admin: dict[str, str], user_factory
) -> None:
    for _ in range(3):
        user_factory()
    page = db_client.get(USERS, params={"limit": 2, "offset": 1}, headers=admin).json()
    assert page["total"] == 4  # the admin + 3
    assert len(page["items"]) == 2
    assert "password_hash" not in page["items"][0]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_list_users_rejects_out_of_range_paging(
    db_client: TestClient, admin: dict[str, str], params: dict[str, int]
) -> None:
    assert db_client.get(USERS, params=params, headers=admin).status_code == 422


# --- Update ---------------------------------------------------------------------------


def test_unknown_user_is_404(db_client: TestClient, admin: dict[str, str]) -> None:
    response = db_client.patch(f"{USERS}/999999", json={"full_name": "X"}, headers=admin)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_br_auth_04_deactivation_blocks_login_and_existing_token(
    db_client: TestClient, db_session: Session, admin: dict[str, str], user_factory
) -> None:
    target = user_factory("wh09", role=Role.WAREHOUSE)
    response = login(db_client, "wh09", "correct-horse-battery-staple")
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    patched = db_client.patch(f"{USERS}/{target.id}", json={"active": False}, headers=admin)
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    assert db_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert login(db_client, "wh09", "correct-horse-battery-staple").status_code == 401
    [row] = audit_rows(db_session, "USER_DEACTIVATED")
    assert (row.old_value, row.new_value) == ({"active": True}, {"active": False})


def test_br_aud_01_role_change_is_audited_with_old_and_new_role(
    db_client: TestClient, db_session: Session, admin: dict[str, str], user_factory
) -> None:
    target = user_factory(role=Role.WAREHOUSE)
    response = db_client.patch(
        f"{USERS}/{target.id}", json={"role": "PRODUCTION_MANAGER"}, headers=admin
    )
    assert response.status_code == 200
    [row] = audit_rows(db_session, "USER_ROLE_CHANGED")
    assert (row.old_value, row.new_value) == (
        {"role": "WAREHOUSE"},
        {"role": "PRODUCTION_MANAGER"},
    )


def test_d18_worker_moved_to_other_role_must_drop_work_center(
    db_client: TestClient, admin: dict[str, str], user_factory
) -> None:
    worker = user_factory(role=Role.WORKER)
    url = f"{USERS}/{worker.id}"
    refused = db_client.patch(url, json={"role": "WAREHOUSE"}, headers=admin)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "WORK_CENTER_NOT_ALLOWED"

    moved = db_client.patch(url, json={"role": "WAREHOUSE", "work_center_id": None}, headers=admin)
    assert moved.status_code == 200
    assert (moved.json()["role"], moved.json()["work_center_id"]) == ("WAREHOUSE", None)


def test_password_reset_replaces_credentials_and_audit_hides_them(
    db_client: TestClient, db_session: Session, admin: dict[str, str], user_factory
) -> None:
    target = user_factory("wh07", role=Role.WAREHOUSE)
    response = db_client.patch(
        f"{USERS}/{target.id}", json={"password": NEW_PASSWORD}, headers=admin
    )
    assert response.status_code == 200
    assert login(db_client, "wh07", "correct-horse-battery-staple").status_code == 401
    assert login(db_client, "wh07", NEW_PASSWORD).status_code == 200

    [row] = audit_rows(db_session, "USER_UPDATED")
    assert (row.old_value, row.new_value) == ({}, {"credentials_reset": True})


@pytest.mark.parametrize("field", ["role", "full_name", "active", "password"])
def test_explicit_null_for_required_field_is_422(
    db_client: TestClient, admin: dict[str, str], user_factory, field: str
) -> None:
    target = user_factory()
    response = db_client.patch(f"{USERS}/{target.id}", json={field: None}, headers=admin)
    assert response.status_code == 422


def test_no_op_update_writes_no_audit_row(
    db_client: TestClient, db_session: Session, admin: dict[str, str], user_factory
) -> None:
    target = user_factory(role=Role.WAREHOUSE)
    response = db_client.patch(f"{USERS}/{target.id}", json={"role": "WAREHOUSE"}, headers=admin)
    assert response.status_code == 200
    assert db_session.scalars(select(AuditLog).where(AuditLog.action.like("USER_%"))).all() == []


# --- C-12: the last active ADMIN is protected ------------------------------------------


def _me(client: TestClient, headers: dict[str, str]) -> int:
    user_id: int = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    return user_id


@pytest.mark.parametrize(
    "change", [{"active": False}, {"role": "WAREHOUSE"}], ids=["deactivate", "demote"]
)
def test_c12_sole_admin_cannot_remove_their_own_admin_access(
    db_client: TestClient, db_session: Session, admin: dict[str, str], change: dict[str, Any]
) -> None:
    response = db_client.patch(f"{USERS}/{_me(db_client, admin)}", json=change, headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN"
    assert db_client.get("/api/v1/auth/me", headers=admin).json()["role"] == "ADMIN"
    assert audit_rows(db_session, "USER_DEACTIVATED") == []


def test_c12_admin_can_step_down_while_another_admin_remains(
    db_client: TestClient, admin: dict[str, str], user_factory
) -> None:
    user_factory(role=Role.ADMIN)
    response = db_client.patch(
        f"{USERS}/{_me(db_client, admin)}", json={"role": "WAREHOUSE"}, headers=admin
    )
    assert response.status_code == 200


def test_c12_remaining_admin_is_protected_after_the_other_is_deactivated(
    db_client: TestClient, admin: dict[str, str], user_factory
) -> None:
    other = user_factory(role=Role.ADMIN)
    assert (
        db_client.patch(f"{USERS}/{other.id}", json={"active": False}, headers=admin).status_code
        == 200
    )
    response = db_client.patch(
        f"{USERS}/{_me(db_client, admin)}", json={"active": False}, headers=admin
    )
    assert response.json()["error"]["code"] == "LAST_ADMIN"
