"""Production orders (B7, BR-PO-01..05, D-06, D-21).

This service is the only writer of ``production_orders.status`` (BR-PO-02); every
action locks the order row first (BR-PO-03) and asks ``domain.order_state`` whether it
is allowed. Lock order (B12): idempotency key -> document_sequences -> product (shared)
-> production_orders.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain import inventory
from app.domain.audit import AuditAction, AuditEntity, changed_fields
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.explode import validate_order_quantity
from app.domain.inventory import TransactionType
from app.domain.operations import OperationStatus
from app.domain.order_state import OrderAction, OrderStatus, ensure_allowed, transition
from app.domain.quantities import format_quantity
from app.domain.reservation import RequiredLine, decide
from app.models.master_data import Material, Product
from app.models.production import (
    ProductionOperation,
    ProductionOrder,
    ProductionOrderMaterial,
)
from app.models.work_center import WorkCenter
from app.repositories.bom_repository import BomRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.production_repository import ProductionOrderRepository
from app.repositories.routing_repository import RoutingRepository
from app.services.audit_service import AuditService
from app.services.bom_service import explode_header
from app.services.context import Actor, RequestContext
from app.services.inventory_service import InventoryService, balance_of

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


@dataclass(frozen=True)
class MaterialCheck:
    """One line of the reservation check (BR-INV-05): required vs available."""

    material_id: int
    material_code: str
    unit: str
    decimal_places: int
    required: Decimal
    available: Decimal
    shortage: Decimal


@dataclass(frozen=True)
class ReservationResult:
    view: OrderView
    checks: list[MaterialCheck]


def format_order_number(year: int, value: int) -> str:
    """D-21: PO-YYYY-NNNNN."""
    return f"PO-{year:04d}-{value:05d}"


class ProductionOrderService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._orders = ProductionOrderRepository(session)
        self._audit = AuditService(session)

    # --- Reads (BR-AUTH-03) ------------------------------------------------------------
    # ``scope`` is the viewer's work center when they are a WORKER (domain.scope), else
    # None. Orders outside it are reported as not found, never as forbidden.

    def list_orders(
        self,
        limit: int,
        offset: int,
        scope: int | None,
        status: OrderStatus | None = None,
        product_id: int | None = None,
    ) -> tuple[list[OrderView], int]:
        with transaction(self._session):
            rows, total = self._orders.list_orders(
                limit, offset, status.value if status else None, product_id, scope
            )
            return [OrderView(order, product) for order, product in rows], total

    def get_order(self, order_id: int, scope: int | None) -> OrderView:
        with transaction(self._session):
            return OrderView(*self._visible(order_id, scope))

    def list_materials(
        self, order_id: int, scope: int | None
    ) -> list[tuple[ProductionOrderMaterial, Material]]:
        with transaction(self._session):
            self._visible(order_id, scope)
            return list(self._orders.lines_with_materials(order_id))

    def list_operations(
        self, order_id: int, scope: int | None
    ) -> list[tuple[ProductionOperation, WorkCenter]]:
        """A WORKER sees only the operations at their own work center (D-18)."""
        with transaction(self._session):
            self._visible(order_id, scope)
            return list(self._orders.operations_with_work_centers(order_id, scope))

    def _visible(self, order_id: int, scope: int | None) -> tuple[ProductionOrder, Product]:
        found = self._orders.get_in_scope(order_id, scope)
        if found is None:
            raise NotFoundError("ORDER_NOT_FOUND", "Production order not found.")
        return found

    # --- Commands -----------------------------------------------------------------------

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

    def plan(self, order_id: int, actor: Actor, context: RequestContext) -> ReservationResult:
        """B7 plan, atomic (D-07): snapshot BOM and routing (D-04), create the material
        lines and PENDING operations, then reserve all or nothing (D-08).

        Lock order (B12): order row -> inventory rows by ascending material_id.
        """
        with transaction(self._session):
            order = self._lock(order_id)
            before = OrderStatus(order.status)
            ensure_allowed(before, OrderAction.PLAN)
            product = self._product(order)
            if not product.active:  # BR-MD-04
                raise ConflictError("PRODUCT_INACTIVE", "The product is inactive.")
            boms, routings = BomRepository(self._session), RoutingRepository(self._session)
            bom = boms.active_for_product(product.id)
            if bom is None:
                raise ConflictError("NO_ACTIVE_BOM", "The product has no ACTIVE BOM.")
            routing = routings.active_for_product(product.id)
            if routing is None:
                raise ConflictError("NO_ACTIVE_ROUTING", "The product has no ACTIVE routing.")

            # D-04: what the order will use, frozen now; later master data edits do not
            # change it.
            order.bom_header_id, order.routing_id = bom.id, routing.id
            lines = [
                ProductionOrderMaterial(
                    production_order_id=order.id,
                    material_id=requirement.material_id,
                    required_quantity=requirement.required_quantity,
                )
                for requirement in explode_header(boms, bom, order.planned_quantity)
            ]
            self._orders.add_lines(lines)
            self._orders.add_operations(
                [
                    ProductionOperation(
                        production_order_id=order.id,
                        sequence=step.sequence,
                        operation_type=step.operation_type,
                        work_center_id=step.work_center_id,
                        status=OperationStatus.PENDING.value,
                    )
                    for step in routing.steps
                ]
            )
            checks, reserved = self._reserve(order, lines, actor, context)
            after = transition(
                before,
                OrderAction.PLAN,
                OrderStatus.READY_TO_PRODUCE if reserved else OrderStatus.MATERIAL_SHORTAGE,
            )
            order.status = after.value
            self._session.flush()
            self._audit_status(
                AuditAction.ORDER_PLANNED,
                order,
                before,
                after,
                actor,
                context,
                {"bom_version": bom.version, "routing_version": routing.version},
            )
        return ReservationResult(OrderView(order, product), checks)

    def check_materials(
        self, order_id: int, actor: Actor, context: RequestContext
    ) -> ReservationResult:
        """D-09: the explicit way out of MATERIAL_SHORTAGE, on the snapshotted lines."""
        with transaction(self._session):
            order = self._lock(order_id)
            before = OrderStatus(order.status)
            ensure_allowed(before, OrderAction.CHECK_MATERIALS)
            lines = self._orders.lines_for_order(order.id)
            checks, reserved = self._reserve(order, lines, actor, context)
            after = transition(
                before,
                OrderAction.CHECK_MATERIALS,
                OrderStatus.READY_TO_PRODUCE if reserved else OrderStatus.MATERIAL_SHORTAGE,
            )
            order.status = after.value
            self._session.flush()
            self._audit_status(
                AuditAction.ORDER_MATERIALS_CHECKED, order, before, after, actor, context, {}
            )
            product = self._product(order)
        return ReservationResult(OrderView(order, product), checks)

    def start(self, order_id: int, actor: Actor, context: RequestContext) -> OrderView:
        """D-11: READY_TO_PRODUCE -> IN_PROGRESS only once every line is fully issued."""
        with transaction(self._session):
            order = self._lock(order_id)
            before = OrderStatus(order.status)
            ensure_allowed(before, OrderAction.START)
            lines = self._orders.lines_for_order(order.id)
            missing = [line for line in lines if line.issued_quantity < line.required_quantity]
            if missing:
                stock = InventoryRepository(self._session)
                materials = stock.materials_by_id([line.material_id for line in missing])
                raise ConflictError(
                    "MATERIALS_NOT_FULLY_ISSUED",
                    "Every material must be issued in full before production starts.",
                    [
                        {
                            "material_code": materials[line.material_id].material_code,
                            "required": format_quantity(
                                line.required_quantity, materials[line.material_id].decimal_places
                            ),
                            "issued": format_quantity(
                                line.issued_quantity, materials[line.material_id].decimal_places
                            ),
                        }
                        for line in missing
                    ],
                )
            after = transition(before, OrderAction.START, OrderStatus.IN_PROGRESS)
            order.status = after.value
            order.started_at = self._clock.now()
            self._session.flush()
            self._audit_status(AuditAction.ORDER_STARTED, order, before, after, actor, context, {})
            product = self._product(order)
        return OrderView(order, product)

    def cancel(
        self, order_id: int, reason: str, actor: Actor, context: RequestContext
    ) -> OrderView:
        """D-13: from DRAFT, MATERIAL_SHORTAGE or READY_TO_PRODUCE. Releases what is still
        reserved (one RELEASE line per material), cancels the operations; issued material
        stays issued until the warehouse returns it (C-05).

        Lock order (B12): order row -> balance rows by ascending material_id.
        """
        with transaction(self._session):
            order = self._lock(order_id)
            before = OrderStatus(order.status)
            ensure_allowed(before, OrderAction.CANCEL)
            lines = [
                line for line in self._orders.lines_for_order(order.id) if line.reserved_quantity
            ]
            stock = InventoryRepository(self._session)
            material_ids = sorted(line.material_id for line in lines)
            materials = stock.materials_by_id(material_ids)
            rows = stock.lock_balances(material_ids)
            ledger = InventoryService(self._session)
            released: dict[str, str] = {}
            for line in sorted(lines, key=lambda line: line.material_id):
                material, row = materials[line.material_id], rows[line.material_id]
                movement = inventory.release(balance_of(row), line.reserved_quantity)
                ledger.record_movement(
                    row,
                    material,
                    movement,
                    TransactionType.RELEASE,
                    actor,
                    context,
                    reason=reason,
                    production_order_id=order.id,
                    order_material_id=line.id,
                )
                released[material.material_code] = format_quantity(
                    line.reserved_quantity, material.decimal_places
                )
                line.reserved_quantity = Decimal(0)
            for operation in self._orders.operations_for_order(order.id):
                operation.status = OperationStatus.CANCELLED.value
            after = transition(before, OrderAction.CANCEL, OrderStatus.CANCELLED)
            order.status = after.value
            order.cancel_reason = reason
            self._session.flush()
            self._audit.record(
                action=AuditAction.ORDER_CANCELLED,
                entity_type=AuditEntity.PRODUCTION_ORDER,
                entity_id=order.id,
                actor=actor,
                context=context,
                old_value={"status": before.value},
                new_value={"status": after.value, "released": released},
                reason=reason,
            )
            product = self._product(order)
        return OrderView(order, product)

    def _reserve(
        self,
        order: ProductionOrder,
        lines: list[ProductionOrderMaterial],
        actor: Actor,
        context: RequestContext,
    ) -> tuple[list[MaterialCheck], bool]:
        """B6 reservation algorithm, steps 3-6, inside the caller's transaction.

        All or nothing (D-08): one shortage anywhere and nothing is reserved; every
        line still reports its shortage (BR-INV-05).
        """
        stock = InventoryRepository(self._session)
        material_ids = sorted(line.material_id for line in lines)
        materials = stock.materials_by_id(material_ids)
        rows = stock.lock_balances(material_ids)  # ascending material_id (B12)
        decision = decide(
            [RequiredLine(line.material_id, line.required_quantity) for line in lines],
            {material_id: balance_of(row) for material_id, row in rows.items()},
        )
        ledger = InventoryService(self._session)
        by_material = {line.material_id: line for line in lines}
        for check in decision.checks:
            line = by_material[check.material_id]
            line.shortage_quantity = check.shortage
            if decision.reservable:
                row = rows[check.material_id]
                movement = inventory.reserve(balance_of(row), line.required_quantity)
                ledger.record_movement(
                    row,
                    materials[check.material_id],
                    movement,
                    TransactionType.RESERVE,
                    actor,
                    context,
                    production_order_id=order.id,
                    order_material_id=line.id,
                )
                line.reserved_quantity = line.required_quantity
        self._session.flush()
        checks = [
            MaterialCheck(
                material_id=check.material_id,
                material_code=materials[check.material_id].material_code,
                unit=materials[check.material_id].unit,
                decimal_places=materials[check.material_id].decimal_places,
                required=check.required,
                available=check.available,
                shortage=check.shortage,
            )
            for check in decision.checks
        ]
        return checks, decision.reservable

    def _audit_status(
        self,
        action: AuditAction,
        order: ProductionOrder,
        before: OrderStatus,
        after: OrderStatus,
        actor: Actor,
        context: RequestContext,
        extra: dict[str, Any],
    ) -> None:
        """BR-PO-04: every status change is audited with the old and new status."""
        self._audit.record(
            action=action,
            entity_type=AuditEntity.PRODUCTION_ORDER,
            entity_id=order.id,
            actor=actor,
            context=context,
            old_value={"status": before.value},
            new_value={"status": after.value, **extra},
        )

    def _product(self, order: ProductionOrder) -> Product:
        product = self._session.get(Product, order.product_id)
        if product is None:  # impossible: products are never deleted (D-19)
            raise RuntimeError(f"product {order.product_id} of order {order.id} is missing")
        return product

    def _lock(self, order_id: int) -> ProductionOrder:
        order = self._orders.get_for_update(order_id)
        if order is None:
            raise NotFoundError("ORDER_NOT_FOUND", "Production order not found.")
        return order

    @staticmethod
    def _ensure_future(due_date: datetime, now: datetime) -> None:
        if due_date <= now:
            raise BusinessValidationError("INVALID_DUE_DATE", "due_date must be in the future.")
