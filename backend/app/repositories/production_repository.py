from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.order_state import OPEN_STATUSES
from app.models.master_data import Product
from app.models.production import (
    DocumentSequence,
    ProductionOperation,
    ProductionOrder,
    ProductionOrderMaterial,
)

ORDER_SEQUENCE = "production_order"


class ProductionOrderRepository:
    """Queries and row locks for production orders; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def next_order_value(self, year: int) -> int:
        """D-21: take the next value of the year's counter under a row lock.

        The upsert makes the first order of a year race-free; the lock then serializes
        concurrent creations. A rollback returns the value, so numbers never skip.
        """
        self._session.execute(
            text(
                "INSERT INTO document_sequences (name, year, next_value) VALUES (:name, :year, 1) "
                "ON DUPLICATE KEY UPDATE next_value = next_value"
            ),
            {"name": ORDER_SEQUENCE, "year": year},
        )
        sequence = self._session.scalars(
            select(DocumentSequence)
            .where(DocumentSequence.name == ORDER_SEQUENCE, DocumentSequence.year == year)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        value = sequence.next_value
        sequence.next_value = value + 1
        self._session.flush()
        return value

    def get_product_for_share(self, product_id: int) -> Product | None:
        """Shared lock: serializes with a product deactivation (C-13)."""
        return self._session.scalars(
            select(Product)
            .where(Product.id == product_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).one_or_none()

    def get(self, order_id: int) -> ProductionOrder | None:
        return self._session.get(ProductionOrder, order_id, populate_existing=True)

    def get_for_update(self, order_id: int) -> ProductionOrder | None:
        """BR-PO-03: every action locks the order row first."""
        return self._session.get(
            ProductionOrder, order_id, with_for_update=True, populate_existing=True
        )

    def add(self, order: ProductionOrder) -> ProductionOrder:
        self._session.add(order)
        self._session.flush()
        self._session.refresh(order, ["created_at"])
        return order

    def open_order_numbers(self, product_id: int) -> list[str]:
        return list(
            self._session.scalars(
                select(ProductionOrder.order_number)
                .where(
                    ProductionOrder.product_id == product_id,
                    ProductionOrder.status.in_([s.value for s in OPEN_STATUSES]),
                )
                .order_by(ProductionOrder.order_number)
            )
        )

    def add_lines(self, lines: list[ProductionOrderMaterial]) -> None:
        self._session.add_all(lines)
        self._session.flush()

    def add_operations(self, operations: list[ProductionOperation]) -> None:
        self._session.add_all(operations)
        self._session.flush()

    def lines_for_order(self, order_id: int) -> list[ProductionOrderMaterial]:
        """Material lines in material_id order; changed only under the order row lock."""
        return list(
            self._session.scalars(
                select(ProductionOrderMaterial)
                .where(ProductionOrderMaterial.production_order_id == order_id)
                .order_by(ProductionOrderMaterial.material_id)
                .execution_options(populate_existing=True)
            )
        )
