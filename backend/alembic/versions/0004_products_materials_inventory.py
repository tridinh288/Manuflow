"""Create products, materials and inventory balances.

Inventory is created now, not in Phase 4, so every material has its zero balance row
from the moment it exists (BR-INV-01) and BR-INV-02 holds from day one.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def _code_check(table: str, column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"REGEXP_LIKE({column}, '^[A-Z0-9-]{{3,32}}$', 'c')",
        name=op.f(f"ck_{table}_code_format"),
    )


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=8), server_default=sa.text("'pcs'"), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("product_code", name=op.f("uq_products_product_code")),
        _code_check("products", "product_code"),
        sa.CheckConstraint("unit = 'pcs'", name=op.f("ck_products_unit_pcs")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "materials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("material_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=8), nullable=False),
        sa.Column("decimal_places", sa.SmallInteger(), nullable=False),
        sa.Column(
            "minimum_stock",
            sa.Numeric(precision=18, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_materials")),
        sa.UniqueConstraint("material_code", name=op.f("uq_materials_material_code")),
        _code_check("materials", "material_code"),
        sa.CheckConstraint("unit IN ('kg', 'pcs', 'm', 'l')", name=op.f("ck_materials_unit_valid")),
        sa.CheckConstraint(
            "decimal_places BETWEEN 0 AND 4", name=op.f("ck_materials_decimal_places_range")
        ),
        sa.CheckConstraint(
            "unit <> 'pcs' OR decimal_places = 0", name=op.f("ck_materials_pcs_whole_units")
        ),
        sa.CheckConstraint(
            "minimum_stock >= 0", name=op.f("ck_materials_minimum_stock_non_negative")
        ),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "inventory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "on_hand_quantity",
            sa.Numeric(precision=18, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reserved_quantity",
            sa.Numeric(precision=18, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory")),
        sa.UniqueConstraint(
            "warehouse_id", "material_id", name=op.f("uq_inventory_warehouse_id_material_id")
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"], name=op.f("fk_inventory_warehouse_id_warehouses")
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], name=op.f("fk_inventory_material_id_materials")
        ),
        sa.CheckConstraint("on_hand_quantity >= 0", name=op.f("ck_inventory_on_hand_non_negative")),
        sa.CheckConstraint(
            "reserved_quantity >= 0", name=op.f("ck_inventory_reserved_non_negative")
        ),
        sa.CheckConstraint(
            "reserved_quantity <= on_hand_quantity",
            name=op.f("ck_inventory_reserved_within_on_hand"),
        ),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("inventory")
    op.drop_table("materials")
    op.drop_table("products")
