"""Create the append-only operation progress log (BR-OP-06, D-15).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_progress_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("good_delta", sa.Integer(), nullable=False),
        sa.Column("rejected_delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reported_by", sa.BigInteger(), nullable=True),
        sa.Column("idem_key", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_progress_logs")),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["production_operations.id"],
            name=op.f("fk_operation_progress_logs_operation_id_production_operations"),
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"],
            ["users.id"],
            name=op.f("fk_operation_progress_logs_reported_by_users"),
        ),
        sa.CheckConstraint(
            "good_delta <> 0 OR rejected_delta <> 0",
            name=op.f("ck_operation_progress_logs_reports_something"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_operation_progress_logs_operation_id_created_at",
        "operation_progress_logs",
        ["operation_id", "created_at"],
    )
    # BR-OP-06: the log is never modified.
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_operation_progress_logs_no_{event.lower()} "
            f"BEFORE {event} ON operation_progress_logs FOR EACH ROW "
            "SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'operation_progress_logs is append-only (BR-OP-06)'"
        )


def downgrade() -> None:
    op.drop_table("operation_progress_logs")  # also drops its triggers
