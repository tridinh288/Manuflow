"""The CLI bootstraps the first ADMIN through the same audited service as the API."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import main
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.user import User


def test_cli_creates_admin_from_env_password(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BOOTSTRAP_PASSWORD", "first-admin-password")
    exit_code = main(
        [
            "create-user",
            "--username",
            "admin",
            "--full-name",
            "System Admin",
            "--role",
            "ADMIN",
            "--password-env",
            "BOOTSTRAP_PASSWORD",
        ],
        session_factory=lambda: db_session,
    )
    assert exit_code == 0
    output = capsys.readouterr()
    assert "first-admin-password" not in output.out + output.err

    user = db_session.scalars(select(User).where(User.username == "admin")).one()
    assert user.role is Role.ADMIN
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "USER_CREATED")).all()
    assert (row.actor_user_id, row.actor_username) == (None, "cli")


def test_cli_reports_domain_errors_without_traceback(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BOOTSTRAP_PASSWORD", "short")
    exit_code = main(
        [
            "create-user",
            "--username",
            "admin",
            "--full-name",
            "Admin",
            "--role",
            "ADMIN",
            "--password-env",
            "BOOTSTRAP_PASSWORD",
        ],
        session_factory=lambda: db_session,
    )
    assert exit_code == 1
    assert "INVALID_PASSWORD" in capsys.readouterr().err
