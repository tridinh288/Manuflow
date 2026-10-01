"""Create production_order_materials and production_operations (D-04, B8, B11).

Also adds the foreign key from inventory_transactions.order_material_id.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _quantity(name: str, *, default: bool = True) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.Numeric(precision=18, scale=4),
        server_default=sa.text("0") if default else None,
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "production_order_materials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("production_order_id", sa.BigInteger(), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=False),
        _quantity("required_quantity", default=False),
        _quantity("reserved_quantity"),
        _quantity("issued_quantity"),
        _quantity("returned_quantity"),
        _quantity("shortage_quantity"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_order_materials")),
        sa.UniqueConstraint(
            "production_order_id",
            "material_id",
            name=op.f("uq_production_order_materials_production_order_id_material_id"),
        ),
        sa.ForeignKeyConstraint(
            ["production_order_id"],
            ["production_orders.id"],
            name=op.f("fk_production_order_materials_production_order_id_production_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
            name=op.f("fk_production_order_materials_material_id_materials"),
        ),
        sa.CheckConstraint(
            "required_quantity > 0", name=op.f("ck_production_order_materials_required_positive")
        ),
        sa.CheckConstraint(
            "reserved_quantity >= 0 AND issued_quantity >= 0 AND returned_quantity >= 0 "
            "AND shortage_quantity >= 0",
            name=op.f("ck_production_order_materials_quantities_non_negative"),
        ),
        sa.CheckConstraint(
            "reserved_quantity + issued_quantity <= required_quantity",
            name=op.f("ck_production_order_materials_reserved_and_issued_within_required"),
        ),
        sa.CheckConstraint(
            "returned_quantity <= issued_quantity",
            name=op.f("ck_production_order_materials_returned_within_issued"),
        ),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "production_operations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("production_order_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("work_center_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("good_quantity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rejected_quantity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_operations")),
        sa.UniqueConstraint(
            "production_order_id",
            "sequence",
            name=op.f("uq_production_operations_production_order_id_sequence"),
        ),
        sa.ForeignKeyConstraint(
            ["production_order_id"],
            ["production_orders.id"],
            name=op.f("fk_production_operations_production_order_id_production_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["work_center_id"],
            ["work_centers.id"],
            name=op.f("fk_production_operations_work_center_id_work_centers"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_production_operations_status_valid"),
        ),
        sa.CheckConstraint(
            "good_quantity >= 0 AND rejected_quantity >= 0",
            name=op.f("ck_production_operations_quantities_non_negative"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_production_operations_work_center_id_status",
        "production_operations",
        ["work_center_id", "status"],
    )
    op.create_foreign_key(
        op.f("fk_inventory_transactions_order_material_id_production_order_materials"),
        "inventory_transactions",
        "production_order_materials",
        ["order_material_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_inventory_transactions_order_material_id_production_order_materials"),
        "inventory_transactions",
        type_="foreignkey",
    )
    op.drop_table("production_operations")
    op.drop_table("production_order_materials")
