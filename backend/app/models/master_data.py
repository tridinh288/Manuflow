"""Products, materials and the inventory balance row created with each material."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_OPTIONS, Base

CODE_CHECK = "REGEXP_LIKE({column}, '^[A-Z0-9-]{{3,32}}$', 'c')"  # BR-MD-01


class MaterialUnit(StrEnum):
    KG = "kg"
    PCS = "pcs"
    M = "m"
    L = "l"


def _created_at() -> Mapped[datetime]:
    return mapped_column(DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)"))


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DATETIME(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(CODE_CHECK.format(column="product_code"), name="code_format"),
        CheckConstraint("unit = 'pcs'", name="unit_pcs"),  # BR-MD-03
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(8), server_default=text("'pcs'"))
    description: Mapped[str | None] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint(CODE_CHECK.format(column="material_code"), name="code_format"),
        CheckConstraint("unit IN ('kg', 'pcs', 'm', 'l')", name="unit_valid"),  # BR-MD-02
        CheckConstraint("decimal_places BETWEEN 0 AND 4", name="decimal_places_range"),
        CheckConstraint("unit <> 'pcs' OR decimal_places = 0", name="pcs_whole_units"),
        CheckConstraint("minimum_stock >= 0", name="minimum_stock_non_negative"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    material_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(8))
    decimal_places: Mapped[int] = mapped_column(SmallInteger)
    minimum_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Inventory(Base):
    """Balance per material (BR-INV-01); movements and the ledger arrive in Phase 4.

    ``available = on_hand - reserved`` is computed, never stored.
    """

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "material_id"),
        # BR-INV-02 / D-20: the database is the last line of defence.
        CheckConstraint("on_hand_quantity >= 0", name="on_hand_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved_quantity <= on_hand_quantity", name="reserved_within_on_hand"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"))
    on_hand_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    updated_at: Mapped[datetime] = _updated_at()
