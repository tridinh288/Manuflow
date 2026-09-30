"""Create versioned BOMs: bom_headers and bom_items (D-02, D-03, BR-BOM-01..04).

``active_flag`` is a stored generated column: 1 for ACTIVE, NULL otherwise. The unique
index on (product_id, active_flag) lets a product have any number of DRAFT and RETIRED
versions but at most one ACTIVE one, whatever the application does (BR-BOM-04).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "bom_headers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "active_flag",
            sa.SmallInteger(),
            sa.Computed("(CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END)", persisted=True),
            nullable=True,
        ),
        sa.Column("activated_at", mysql.DATETIME(fsp=6), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bom_headers")),
        sa.UniqueConstraint(
            "product_id", "version", name=op.f("uq_bom_headers_product_id_version")
        ),
        sa.UniqueConstraint(
            "product_id", "active_flag", name=op.f("uq_bom_headers_product_id_active_flag")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_bom_headers_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_bom_headers_created_by_users")
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_bom_headers_status_valid")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_bom_headers_version_positive")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "bom_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bom_header_id", sa.BigInteger(), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=False),
        sa.Column("qty_per_unit", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column(
            "scrap_rate",
            sa.Numeric(precision=5, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bom_items")),
        sa.UniqueConstraint(
            "bom_header_id", "material_id", name=op.f("uq_bom_items_bom_header_id_material_id")
        ),
        sa.ForeignKeyConstraint(
            ["bom_header_id"],
            ["bom_headers.id"],
            name=op.f("fk_bom_items_bom_header_id_bom_headers"),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], name=op.f("fk_bom_items_material_id_materials")
        ),
        sa.CheckConstraint("qty_per_unit > 0", name=op.f("ck_bom_items_qty_per_unit_positive")),
        sa.CheckConstraint(
            "scrap_rate >= 0 AND scrap_rate < 1", name=op.f("ck_bom_items_scrap_rate_range")
        ),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("bom_items")
    op.drop_table("bom_headers")
