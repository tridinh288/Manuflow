from collections.abc import Sequence

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from app.domain.order_state import OPEN_STATUSES
from app.models.master_data import Material, Product
from app.models.production import (
    DocumentSequence,
    OperationProgressLog,
    ProductionOperation,
    ProductionOrder,
    ProductionOrderMaterial,
)
from app.models.work_center import WorkCenter

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

    def get_line_for_update(self, line_id: int) -> ProductionOrderMaterial | None:
        return self._session.get(
            ProductionOrderMaterial, line_id, with_for_update=True, populate_existing=True
        )

    def get_line(self, line_id: int) -> ProductionOrderMaterial | None:
        return self._session.get(ProductionOrderMaterial, line_id, populate_existing=True)

    def operations_for_order(self, order_id: int) -> list[ProductionOperation]:
        return list(
            self._session.scalars(
                select(ProductionOperation)
                .where(ProductionOperation.production_order_id == order_id)
                .order_by(ProductionOperation.sequence)
                .execution_options(populate_existing=True)
            )
        )

    # --- Reads (BR-AUTH-03: ``work_center_id`` limits a WORKER to their work center) ------

    @staticmethod
    def _in_scope(work_center_id: int | None) -> list[object]:
        if work_center_id is None:
            return []
        return [
            exists().where(
                ProductionOperation.production_order_id == ProductionOrder.id,
                ProductionOperation.work_center_id == work_center_id,
            )
        ]

    def list_orders(
        self,
        limit: int,
        offset: int,
        status: str | None,
        product_id: int | None,
        work_center_id: int | None,
    ) -> tuple[Sequence[tuple[ProductionOrder, Product]], int]:
        conditions: list[object] = self._in_scope(work_center_id)
        if status is not None:
            conditions.append(ProductionOrder.status == status)
        if product_id is not None:
            conditions.append(ProductionOrder.product_id == product_id)
        base = (
            select(ProductionOrder, Product)
            .join(Product, Product.id == ProductionOrder.product_id)
            .where(*conditions)  # type: ignore[arg-type]
        )
        total = self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self._session.execute(
            base.order_by(ProductionOrder.due_date, ProductionOrder.id).limit(limit).offset(offset)
        ).all()
        return [(order, product) for order, product in rows], total

    def get_in_scope(
        self, order_id: int, work_center_id: int | None
    ) -> tuple[ProductionOrder, Product] | None:
        row = self._session.execute(
            select(ProductionOrder, Product)
            .join(Product, Product.id == ProductionOrder.product_id)
            .where(ProductionOrder.id == order_id, *self._in_scope(work_center_id))  # type: ignore[arg-type]
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else (row[0], row[1])

    def lines_with_materials(
        self, order_id: int
    ) -> Sequence[tuple[ProductionOrderMaterial, Material]]:
        rows = self._session.execute(
            select(ProductionOrderMaterial, Material)
            .join(Material, Material.id == ProductionOrderMaterial.material_id)
            .where(ProductionOrderMaterial.production_order_id == order_id)
            .order_by(Material.material_code)
        ).all()
        return [(line, material) for line, material in rows]

    def operations_with_work_centers(
        self, order_id: int, work_center_id: int | None
    ) -> Sequence[tuple[ProductionOperation, WorkCenter]]:
        conditions = [ProductionOperation.production_order_id == order_id]
        if work_center_id is not None:
            conditions.append(ProductionOperation.work_center_id == work_center_id)
        rows = self._session.execute(
            select(ProductionOperation, WorkCenter)
            .join(WorkCenter, WorkCenter.id == ProductionOperation.work_center_id)
            .where(*conditions)
            .order_by(ProductionOperation.sequence)
        ).all()
        return [(operation, center) for operation, center in rows]

    def get_operation(self, operation_id: int) -> ProductionOperation | None:
        return self._session.get(ProductionOperation, operation_id, populate_existing=True)

    def lock_operations(self, order_id: int) -> list[ProductionOperation]:
        """BR-OP-07: after the order row, every operation of the order by sequence."""
        return list(
            self._session.scalars(
                select(ProductionOperation)
                .where(ProductionOperation.production_order_id == order_id)
                .order_by(ProductionOperation.sequence)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def add_progress_log(self, log: OperationProgressLog) -> OperationProgressLog:
        self._session.add(log)
        self._session.flush()
        return log
