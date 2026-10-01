from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    materials: Mapped[list["ProductionOrderMaterial"]] = relationship(
        order_by="ProductionOrderMaterial.material_id", lazy="selectin"
    )
    operations: Mapped[list["ProductionOperation"]] = relationship(
        order_by="ProductionOperation.sequence", lazy="selectin"
    )


class ProductionOrderMaterial(Base):
    """One material line of an order, snapshotted by plan (D-04).

    ``reserved_quantity`` is what is *still* reserved: RESERVE sets it to required,
    ISSUE moves quantity from reserved to issued, RELEASE sets it back to 0 (B11).
    """

    __tablename__ = "production_order_materials"
    __table_args__ = (
        UniqueConstraint("production_order_id", "material_id"),
        CheckConstraint("required_quantity > 0", name="required_positive"),
        CheckConstraint(
            "reserved_quantity >= 0 AND issued_quantity >= 0 AND returned_quantity >= 0 "
            "AND shortage_quantity >= 0",
            name="quantities_non_negative",
        ),
        CheckConstraint(
            "reserved_quantity + issued_quantity <= required_quantity",
            name="reserved_and_issued_within_required",
        ),
        CheckConstraint("returned_quantity <= issued_quantity", name="returned_within_issued"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    production_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("production_orders.id"))
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"))
    required_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    issued_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    shortage_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))


OPERATION_STATUS_CHECK = "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')"


class ProductionOperation(Base):
    """One routing step instantiated for an order by plan (B8)."""

    __tablename__ = "production_operations"
    __table_args__ = (
        UniqueConstraint("production_order_id", "sequence"),
        Index("ix_production_operations_work_center_id_status", "work_center_id", "status"),
        CheckConstraint(OPERATION_STATUS_CHECK, name="status_valid"),
        CheckConstraint(
            "good_quantity >= 0 AND rejected_quantity >= 0", name="quantities_non_negative"
        ),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    production_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("production_orders.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    operation_type: Mapped[str] = mapped_column(String(32))
    work_center_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("work_centers.id"))
    status: Mapped[str] = mapped_column(String(32))
    good_quantity: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_quantity: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class OperationProgressLog(Base):
    """One progress report or correction (BR-OP-06, D-15). Append-only (DB triggers)."""

    __tablename__ = "operation_progress_logs"
    __table_args__ = (
        Index("ix_operation_progress_logs_operation_id_created_at", "operation_id", "created_at"),
        CheckConstraint("good_delta <> 0 OR rejected_delta <> 0", name="reports_something"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("production_operations.id"))
    good_delta: Mapped[int] = mapped_column(Integer)
    rejected_delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500))
    reported_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    idem_key: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=text("CURRENT_TIMESTAMP(6)")
    )
