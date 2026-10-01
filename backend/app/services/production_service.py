"""Production orders (B7, BR-PO-01..05, D-06, D-21).

This service is the only writer of ``production_orders.status`` (BR-PO-02); every
action locks the order row first (BR-PO-03) and asks ``domain.order_state`` whether it
is allowed. Lock order (B12): idempotency key -> document_sequences -> product (shared)
-> production_orders.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity, changed_fields
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.explode import validate_order_quantity
from app.domain.order_state import OrderAction, OrderStatus, ensure_allowed
from app.models.master_data import Product
from app.models.production import ProductionOrder
from app.repositories.production_repository import ProductionOrderRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext

_AUDITED_FIELDS = ("planned_quantity", "due_date", "notes")


@dataclass(frozen=True)
class NewOrder:
    product_id: int
    planned_quantity: Any  # validated by D-06 rules, not by type coercion
    due_date: datetime
    notes: str | None = None


@dataclass(frozen=True)
class OrderUpdate:
    """PATCH: only the fields named in ``provided`` change."""

    provided: frozenset[str] = field(default_factory=frozenset)
    planned_quantity: Any = None
    due_date: datetime | None = None
    notes: str | None = None


@dataclass(frozen=True)
class OrderView:
    order: ProductionOrder
    product: Product


def format_order_number(year: int, value: int) -> str:
    """D-21: PO-YYYY-NNNNN."""
    return f"PO-{year:04d}-{value:05d}"


class ProductionOrderService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._orders = ProductionOrderRepository(session)
        self._audit = AuditService(session)

    def create(self, data: NewOrder, actor: Actor, context: RequestContext) -> OrderView:
        quantity = validate_order_quantity(data.planned_quantity)
        now = self._clock.now()
        self._ensure_future(data.due_date, now)
        with transaction(self._session):
            value = self._orders.next_order_value(now.year)
            product = self._orders.get_product_for_share(data.product_id)
            if product is None:
                raise BusinessValidationError(
                    "PRODUCT_NOT_FOUND",
                    "Product does not exist.",
                    [{"product_id": data.product_id}],
                )
            if not product.active:
                raise ConflictError("PRODUCT_INACTIVE", "The product is inactive.")
            order = self._orders.add(
                ProductionOrder(
                    order_number=format_order_number(now.year, value),
                    product_id=product.id,
                    planned_quantity=quantity,
                    due_date=data.due_date.astimezone(UTC),  # D-23
                    status=OrderStatus.DRAFT.value,
                    notes=data.notes,
                    created_by=actor.user_id,
                )
            )
            self._audit.record(
                action=AuditAction.ORDER_CREATED,
                entity_type=AuditEntity.PRODUCTION_ORDER,
                entity_id=order.id,
                actor=actor,
                context=context,
                new_value={
                    "order_number": order.order_number,
                    "product_code": product.product_code,
                    "planned_quantity": order.planned_quantity,
                    "due_date": order.due_date,
                    "status": order.status,
                },
            )
        return OrderView(order, product)

    def update(
        self, order_id: int, update: OrderUpdate, actor: Actor, context: RequestContext
    ) -> OrderView:
        """B7: only planned_quantity, due_date and notes, and only while DRAFT."""
        if "planned_quantity" in update.provided:
            validate_order_quantity(update.planned_quantity)
        if "due_date" in update.provided and update.due_date is not None:
            self._ensure_future(update.due_date, self._clock.now())
        with transaction(self._session):
            order = self._lock(order_id)
            ensure_allowed(OrderStatus(order.status), OrderAction.UPDATE)
            before = {name: getattr(order, name) for name in _AUDITED_FIELDS}
            if "planned_quantity" in update.provided:
                order.planned_quantity = update.planned_quantity
            if "due_date" in update.provided and update.due_date is not None:
                order.due_date = update.due_date.astimezone(UTC)  # D-23
            if "notes" in update.provided:
                order.notes = update.notes
            self._session.flush()
            old, new = changed_fields(before, {n: getattr(order, n) for n in _AUDITED_FIELDS})
            if new:
                self._audit.record(
                    action=AuditAction.ORDER_UPDATED,
                    entity_type=AuditEntity.PRODUCTION_ORDER,
                    entity_id=order.id,
                    actor=actor,
                    context=context,
                    old_value=old,
                    new_value=new,
                )
            product = self._session.get(Product, order.product_id)
            if product is None:  # impossible: products are never deleted (D-19)
                raise RuntimeError(f"product {order.product_id} of order {order.id} is missing")
        return OrderView(order, product)

    def _lock(self, order_id: int) -> ProductionOrder:
        order = self._orders.get_for_update(order_id)
        if order is None:
            raise NotFoundError("ORDER_NOT_FOUND", "Production order not found.")
        return order

    @staticmethod
    def _ensure_future(due_date: datetime, now: datetime) -> None:
        if due_date <= now:
            raise BusinessValidationError("INVALID_DUE_DATE", "due_date must be in the future.")
