from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MYSQL_TABLE_OPTIONS, Base
from app.db.types import UTCDateTime
from app.models.bom import ACTIVE_FLAG, STATUS_CHECK

OPERATION_TYPE_CHECK = (
    "operation_type IN ('CUTTING', 'CNC', 'WELDING', 'PAINTING', 'ASSEMBLY', 'QC')"
)


class Routing(Base):
    """Same lifecycle and single-ACTIVE guarantee as BOM versions (D-03, BR-BOM-04)."""

    __tablename__ = "routings"
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

    steps: Mapped[list["RoutingStep"]] = relationship(
        back_populates="routing",
        order_by="RoutingStep.sequence",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RoutingStep(Base):
    __tablename__ = "routing_steps"
    __table_args__ = (
        UniqueConstraint("routing_id", "sequence"),  # BR-RT-01
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(OPERATION_TYPE_CHECK, name="operation_type_valid"),  # BR-RT-02
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    routing_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("routings.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    operation_type: Mapped[str] = mapped_column(String(32))
    work_center_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("work_centers.id"))

    routing: Mapped[Routing] = relationship(back_populates="steps")
