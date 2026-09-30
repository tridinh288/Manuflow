from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_OPTIONS, Base
from app.db.types import UTCDateTime

TYPE_CHECK = "type IN ('RECEIVE', 'RESERVE', 'RELEASE', 'ISSUE', 'RETURN', 'ADJUSTMENT')"


class InventoryTransaction(Base):
    """The inventory ledger (BR-INV-03): one line per material per balance change.

    Append-only: DB triggers reject every UPDATE and DELETE. ``production_order_id`` and
    ``order_material_id`` get their foreign keys when production orders exist (Phase 5).
    """

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        Index("ix_inventory_transactions_material_id_created_at", "material_id", "created_at"),
        Index("ix_inventory_transactions_production_order_id", "production_order_id"),
        Index("ix_inventory_transactions_created_at", "created_at"),
        CheckConstraint(TYPE_CHECK, name="type_valid"),
        CheckConstraint("on_hand_delta <> 0 OR reserved_delta <> 0", name="moves_something"),
        CheckConstraint("on_hand_after >= 0", name="on_hand_after_non_negative"),
        CheckConstraint("reserved_after >= 0", name="reserved_after_non_negative"),
        CheckConstraint("reserved_after <= on_hand_after", name="reserved_after_within_on_hand"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"))
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    on_hand_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    reserved_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    on_hand_after: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    reserved_after: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    production_order_id: Mapped[int | None] = mapped_column(BigInteger)
    order_material_id: Mapped[int | None] = mapped_column(BigInteger)
    reference: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=text("CURRENT_TIMESTAMP(6)")
    )
