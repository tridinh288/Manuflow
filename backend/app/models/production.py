from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_OPTIONS, Base
from app.db.types import UTCDateTime

ORDER_STATUS_CHECK = (
    "status IN ('DRAFT', 'MATERIAL_SHORTAGE', 'READY_TO_PRODUCE', 'IN_PROGRESS', "
    "'COMPLETED', 'CANCELLED')"
)


class DocumentSequence(Base):
    """Per-year counters for document numbers, locked FOR UPDATE (D-21)."""

    __tablename__ = "document_sequences"
    __table_args__ = (
        PrimaryKeyConstraint("name", "year"),
        CheckConstraint("next_value > 0", name="next_value_positive"),
        MYSQL_TABLE_OPTIONS,
    )

    name: Mapped[str] = mapped_column(String(32))
    year: Mapped[int] = mapped_column(Integer)
    next_value: Mapped[int] = mapped_column(Integer)


class ProductionOrder(Base):
    """``status`` is written only by ProductionOrderService (BR-PO-02)."""

    __tablename__ = "production_orders"
    __table_args__ = (
        Index("ix_production_orders_status_due_date", "status", "due_date"),
        CheckConstraint(ORDER_STATUS_CHECK, name="status_valid"),
        CheckConstraint("planned_quantity > 0", name="planned_quantity_positive"),
        CheckConstraint(
            "completed_quantity IS NULL OR completed_quantity >= 0",
            name="completed_quantity_non_negative",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), unique=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    # D-04: the BOM and routing versions snapshotted by plan.
    bom_header_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bom_headers.id"))
    routing_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("routings.id"))
    planned_quantity: Mapped[int] = mapped_column(Integer)
    completed_quantity: Mapped[int | None] = mapped_column(Integer)
    due_date: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(String(1000))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
