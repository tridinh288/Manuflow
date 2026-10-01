"""Create document_sequences and production_orders (D-21, B7, B11).

Also adds the foreign key from inventory_transactions.production_order_id, which waited
for this table since Phase 4.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", "year", name=op.f("pk_document_sequences")),
        sa.CheckConstraint(
            "next_value > 0", name=op.f("ck_document_sequences_next_value_positive")
        ),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "production_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("bom_header_id", sa.BigInteger(), nullable=True),
        sa.Column("routing_id", sa.BigInteger(), nullable=True),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
        sa.Column("completed_quantity", sa.Integer(), nullable=True),
        sa.Column("due_date", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_production_orders_order_number")),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_production_orders_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["bom_header_id"],
            ["bom_headers.id"],
            name=op.f("fk_production_orders_bom_header_id_bom_headers"),
        ),
        sa.ForeignKeyConstraint(
            ["routing_id"], ["routings.id"], name=op.f("fk_production_orders_routing_id_routings")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_production_orders_created_by_users")
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'MATERIAL_SHORTAGE', 'READY_TO_PRODUCE', 'IN_PROGRESS', "
            "'COMPLETED', 'CANCELLED')",
            name=op.f("ck_production_orders_status_valid"),
        ),
        sa.CheckConstraint(
            "planned_quantity > 0", name=op.f("ck_production_orders_planned_quantity_positive")
        ),
        sa.CheckConstraint(
            "completed_quantity IS NULL OR completed_quantity >= 0",
            name=op.f("ck_production_orders_completed_quantity_non_negative"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_production_orders_status_due_date", "production_orders", ["status", "due_date"]
    )
    op.create_foreign_key(
        op.f("fk_inventory_transactions_production_order_id_production_orders"),
        "inventory_transactions",
        "production_orders",
        ["production_order_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_inventory_transactions_production_order_id_production_orders"),
        "inventory_transactions",
        type_="foreignkey",
    )
    op.drop_table("production_orders")
    op.drop_table("document_sequences")
