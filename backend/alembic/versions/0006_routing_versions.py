"""Create versioned routings: routings and routing_steps (BR-RT-01..03, D-03).

Same single-ACTIVE mechanism as bom_headers: a stored generated ``active_flag`` with a
unique index on (product_id, active_flag).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "routings",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routings")),
        sa.UniqueConstraint("product_id", "version", name=op.f("uq_routings_product_id_version")),
        sa.UniqueConstraint(
            "product_id", "active_flag", name=op.f("uq_routings_product_id_active_flag")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_routings_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_routings_created_by_users")
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name=op.f("ck_routings_status_valid")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_routings_version_positive")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "routing_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("routing_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("work_center_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routing_steps")),
        sa.UniqueConstraint(
            "routing_id", "sequence", name=op.f("uq_routing_steps_routing_id_sequence")
        ),
        sa.ForeignKeyConstraint(
            ["routing_id"], ["routings.id"], name=op.f("fk_routing_steps_routing_id_routings")
        ),
        sa.ForeignKeyConstraint(
            ["work_center_id"],
            ["work_centers.id"],
            name=op.f("fk_routing_steps_work_center_id_work_centers"),
        ),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_routing_steps_sequence_positive")),
        sa.CheckConstraint(
            "operation_type IN ('CUTTING', 'CNC', 'WELDING', 'PAINTING', 'ASSEMBLY', 'QC')",
            name=op.f("ck_routing_steps_operation_type_valid"),
        ),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("routing_steps")
    op.drop_table("routings")
