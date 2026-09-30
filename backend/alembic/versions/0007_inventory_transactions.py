"""Create the append-only inventory ledger (BR-INV-03, BR-INV-04, D-20).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _quantity(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.Numeric(precision=18, scale=4), nullable=False)


def upgrade() -> None:
    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        _quantity("on_hand_delta"),
        _quantity("reserved_delta"),
        _quantity("on_hand_after"),
        _quantity("reserved_after"),
        sa.Column("production_order_id", sa.BigInteger(), nullable=True),
        sa.Column("order_material_id", sa.BigInteger(), nullable=True),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_transactions")),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            name=op.f("fk_inventory_transactions_material_id_materials"),
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_inventory_transactions_warehouse_id_warehouses"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_inventory_transactions_created_by_users")
        ),
        sa.CheckConstraint(
            "type IN ('RECEIVE', 'RESERVE', 'RELEASE', 'ISSUE', 'RETURN', 'ADJUSTMENT')",
            name=op.f("ck_inventory_transactions_type_valid"),
        ),
        sa.CheckConstraint(
            "on_hand_delta <> 0 OR reserved_delta <> 0",
            name=op.f("ck_inventory_transactions_moves_something"),
        ),
        sa.CheckConstraint(
            "on_hand_after >= 0", name=op.f("ck_inventory_transactions_on_hand_after_non_negative")
        ),
        sa.CheckConstraint(
            "reserved_after >= 0",
            name=op.f("ck_inventory_transactions_reserved_after_non_negative"),
        ),
        sa.CheckConstraint(
            "reserved_after <= on_hand_after",
            name=op.f("ck_inventory_transactions_reserved_after_within_on_hand"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_inventory_transactions_material_id_created_at",
        "inventory_transactions",
        ["material_id", "created_at"],
    )
    op.create_index(
        "ix_inventory_transactions_production_order_id",
        "inventory_transactions",
        ["production_order_id"],
    )
    op.create_index(
        "ix_inventory_transactions_created_at", "inventory_transactions", ["created_at"]
    )

    # BR-INV-03: ledger lines are never modified or deleted.
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_inventory_transactions_no_{event.lower()} "
            f"BEFORE {event} ON inventory_transactions FOR EACH ROW "
            "SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'inventory_transactions is append-only (BR-INV-03)'"
        )


def downgrade() -> None:
    op.drop_table("inventory_transactions")  # also drops its triggers
