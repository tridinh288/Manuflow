"""Create work_centers, users and append-only audit_logs.

work_centers is created here because users.work_center_id references it (D-18);
its endpoints come in Phase 3.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        mysql.DATETIME(fsp=6),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


def _updated_at() -> sa.Column[object]:
    return sa.Column(
        "updated_at",
        mysql.DATETIME(fsp=6),
        server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "work_centers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_centers")),
        sa.UniqueConstraint("code", name=op.f("uq_work_centers_code")),
        sa.CheckConstraint(
            "REGEXP_LIKE(code, '^[A-Z0-9-]{3,32}$', 'c')",
            name=op.f("ck_work_centers_code_format"),
        ),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("work_center_id", sa.BigInteger(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("first_failed_login_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("locked_until", mysql.DATETIME(fsp=6), nullable=True),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.ForeignKeyConstraint(
            ["work_center_id"],
            ["work_centers.id"],
            name=op.f("fk_users_work_center_id_work_centers"),
        ),
        sa.CheckConstraint(
            "role IN ('ADMIN', 'PRODUCTION_MANAGER', 'WAREHOUSE', 'WORKER')",
            name=op.f("ck_users_role_valid"),
        ),
        sa.CheckConstraint(
            "role <> 'WORKER' OR work_center_id IS NOT NULL",
            name=op.f("ck_users_worker_has_work_center"),
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0", name=op.f("ck_users_failed_login_count_non_negative")
        ),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_logs_actor_user_id_users")
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_audit_logs_entity_type_entity_id", "audit_logs", ["entity_type", "entity_id"]
    )
    op.create_index(
        "ix_audit_logs_actor_user_id_created_at", "audit_logs", ["actor_user_id", "created_at"]
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # BR-AUD-06: audit rows can only be inserted, whatever the application code does.
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_audit_logs_no_{event.lower()} BEFORE {event} ON audit_logs "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'audit_logs is append-only (BR-AUD-06)'"
        )


def downgrade() -> None:
    op.drop_table("audit_logs")  # also drops its triggers
    op.drop_table("users")
    op.drop_table("work_centers")
