"""BR-AUD-01..06 (test 22 of B15): audit rows live and die with the business change."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.domain.audit import SENSITIVE_KEY_PARTS, AuditAction, AuditEntity
from app.models.audit_log import AuditLog
from app.services.audit_service import AuditOutsideTransactionError, AuditService
from app.services.context import Actor, RequestContext

PASSWORD = "correct-horse-battery-staple"
CONTEXT = RequestContext(request_id="req-test", ip_address="10.0.0.5")


def audit_rows(session: Session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id)))


def record(session: Session, **overrides: object) -> AuditLog:
    values: dict[str, object] = {
        "action": AuditAction.LOGIN_SUCCESS,
        "entity_type": AuditEntity.USER,
        "entity_id": None,
        "actor": Actor(user_id=None, username="system"),
        "context": CONTEXT,
    }
    values.update(overrides)
    return AuditService(session).record(**values)  # type: ignore[arg-type]


# --- BR-AUD-01 / BR-AUD-03: login is audited with full context --------------------------


def test_br_aud_01_successful_login_is_audited_with_request_context(
    db_client: TestClient, db_session: Session, user_factory
) -> None:
    user = user_factory("pm01")
    db_client.post(
        "/api/v1/auth/login",
        json={"username": "pm01", "password": PASSWORD},
        headers={"X-Request-ID": "req-login-1"},
    )
    [row] = audit_rows(db_session)
    assert (row.action, row.entity_type, row.entity_id) == ("LOGIN_SUCCESS", "user", user.id)
    assert (row.actor_user_id, row.actor_username) == (user.id, "pm01")
    assert (row.request_id, row.ip_address) == ("req-login-1", "testclient")
    assert row.new_value is None
    assert row.created_at.tzinfo is not None


def test_br_aud_01_failed_logins_are_audited_including_unknown_users(
    db_client: TestClient, db_session: Session, user_factory
) -> None:
    user = user_factory("wh01", role=Role.WAREHOUSE)
    db_client.post("/api/v1/auth/login", json={"username": "wh01", "password": "wrong-pass"})
    db_client.post("/api/v1/auth/login", json={"username": "ghost", "password": "whatever"})

    known, unknown = audit_rows(db_session)
    assert known.action == unknown.action == "LOGIN_FAILED"
    assert (known.actor_user_id, known.entity_id) == (user.id, user.id)
    assert known.new_value == {
        "outcome": "BAD_PASSWORD",
        "failed_login_count": 1,
        "locked_until": None,
    }
    assert (unknown.actor_user_id, unknown.actor_username, unknown.entity_id) == (
        None,
        "ghost",
        None,
    )
    assert unknown.new_value is not None
    assert unknown.new_value["outcome"] == "UNKNOWN_USER"


# --- BR-AUD-02: same transaction as the business change -------------------------------


def test_br_aud_02_audit_row_is_rolled_back_with_its_transaction(db_session: Session) -> None:
    with pytest.raises(RuntimeError, match="business failure"), db_session.begin():
        record(db_session)
        raise RuntimeError("business failure after the audit row was written")
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_br_aud_02_audit_row_is_committed_with_its_transaction(db_session: Session) -> None:
    with db_session.begin():
        record(db_session)
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_br_aud_02_recording_outside_a_transaction_is_refused(db_session: Session) -> None:
    assert not db_session.in_transaction()
    with pytest.raises(AuditOutsideTransactionError):
        record(db_session)


def test_br_aud_02_failed_login_audit_survives_the_rejected_request(
    db_client: TestClient, db_session: Session
) -> None:
    response = db_client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert response.status_code == 401
    assert len(audit_rows(db_session)) == 1


# --- BR-AUD-05: no secrets stored ------------------------------------------------------


def test_br_aud_05_sensitive_keys_are_stripped_before_storage(db_session: Session) -> None:
    with db_session.begin():
        row = record(
            db_session,
            old_value={"password_hash": "$argon2id$...", "full_name": "Old"},
            new_value={
                "full_name": "New",
                "password": "hunter2-hunter2",
                "nested": {"access_token": "eyJ...", "role": "ADMIN"},
                "headers": [{"Authorization": "Bearer eyJ..."}],
            },
        )
    db_session.expire(row)
    assert row.old_value == {"full_name": "Old"}
    assert row.new_value == {"full_name": "New", "nested": {"role": "ADMIN"}, "headers": [{}]}


def test_br_aud_05_no_audit_row_contains_secrets_after_logins(
    db_client: TestClient, db_session: Session, user_factory
) -> None:
    user_factory("pm01")
    for username, password in [("pm01", PASSWORD), ("pm01", "typo-password-1"), ("x", "p-9")]:
        db_client.post("/api/v1/auth/login", json={"username": username, "password": password})

    dumped = db_session.scalars(
        text(
            "SELECT CONCAT_WS('|', actor_username, action, entity_type, reason, "
            "CAST(old_value AS CHAR), CAST(new_value AS CHAR)) FROM audit_logs"
        )
    ).all()
    assert len(dumped) == 3
    for line in dumped:
        lowered = line.lower()
        for secret in (PASSWORD, "typo-password-1", "p-9", "$argon2"):
            assert secret.lower() not in lowered
        for key in SENSITIVE_KEY_PARTS:
            assert f'"{key}' not in lowered


# --- BR-AUD-06: append-only enforced by the database ----------------------------------


def test_br_aud_06_audit_rows_cannot_be_updated_or_deleted(db_session: Session) -> None:
    with db_session.begin():
        record(db_session)

    for statement in (update(AuditLog).values(action="TAMPERED"), delete(AuditLog)):
        with pytest.raises(DBAPIError, match="append-only"), db_session.begin():
            db_session.execute(statement)

    [row] = audit_rows(db_session)
    assert row.action == "LOGIN_SUCCESS"
