from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MYSQL_TABLE_OPTIONS, Base
from app.db.types import UTCDateTime

# BR-BOM-04: NULL for every status but ACTIVE, so the unique index on
# (product_id, active_flag) allows many DRAFT/RETIRED versions but one ACTIVE.
ACTIVE_FLAG = "(CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END)"
STATUS_CHECK = "status IN ('DRAFT', 'ACTIVE', 'RETIRED')"


class BomHeader(Base):
    __tablename__ = "bom_headers"
    __table_args__ = (
        UniqueConstraint("product_id", "version"),
        UniqueConstraint("product_id", "active_flag"),
        CheckConstraint(STATUS_CHECK, name="status_valid"),
        CheckConstraint("version > 0", name="version_positive"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    active_flag: Mapped[int | None] = mapped_column(
        SmallInteger, Computed(ACTIVE_FLAG, persisted=True)
    )
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )

    items: Mapped[list["BomItem"]] = relationship(
        back_populates="header",
        order_by="BomItem.material_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BomItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        UniqueConstraint("bom_header_id", "material_id"),  # BR-BOM-02
        CheckConstraint("qty_per_unit > 0", name="qty_per_unit_positive"),  # BR-BOM-01
        CheckConstraint("scrap_rate >= 0 AND scrap_rate < 1", name="scrap_rate_range"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bom_header_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bom_headers.id"))
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"))
    qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    scrap_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), server_default=text("0"))

    header: Mapped[BomHeader] = relationship(back_populates="items")
