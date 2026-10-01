"""Inventory movements (B6, BR-INV-01..03, D-20, C-15).

Every movement is one transaction that locks the material (shared) and then its balance
row (exclusive), changes the balance, writes exactly one ledger line with the balance
after the change, and writes the audit row.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.domain import inventory
from app.domain.audit import AuditAction, AuditEntity
from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.inventory import Balance, Movement, TransactionType
from app.domain.order_state import OrderStatus, ensure_stock_movement_allowed
from app.domain.quantities import format_quantity
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material
from app.models.production import ProductionOrder, ProductionOrderMaterial
from app.repositories.inventory_repository import (
    InventoryRepository,
    LedgerTotals,
    TransactionFilter,
)
from app.repositories.production_repository import ProductionOrderRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext


@dataclass(frozen=True)
class MovementResult:
    line: InventoryTransaction
    material: Material
    balance: Balance


@dataclass(frozen=True)
class OrderMovementResult(MovementResult):
    order: ProductionOrder
    order_line: ProductionOrderMaterial


@dataclass(frozen=True)
class Reconciliation:
    """BR-INV-04 result: every balance row checked against its ledger."""

    checked: int
    mismatches: list[LedgerTotals]


class InventoryService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._inventory = InventoryRepository(session)
        self._audit = AuditService(session)

    # --- Reads ---------------------------------------------------------------------------

    def list_balances(
        self, limit: int, offset: int, low_stock: bool
    ) -> tuple[Sequence[tuple[Inventory, Material]], int]:
        with transaction(self._session):
            return self._inventory.list_balances(limit, offset, low_stock)

    def list_transactions(
        self, filters: TransactionFilter, limit: int, offset: int
    ) -> tuple[Sequence[tuple[InventoryTransaction, Material]], int]:
        if (
            filters.created_from is not None
            and filters.created_to is not None
            and filters.created_from >= filters.created_to
        ):
            raise BusinessValidationError(
                "INVALID_DATE_RANGE", "created_from must be earlier than created_to."
            )
        with transaction(self._session):
            return self._inventory.list_transactions(filters, limit, offset)

    def reconcile(self) -> Reconciliation:
        """BR-INV-04: SUM(on_hand_delta) = on_hand and SUM(reserved_delta) = reserved for
        every material; any difference means the balance and its ledger disagree."""
        with transaction(self._session):
            totals = self._inventory.ledger_totals()
        mismatches = [
            t for t in totals if t.on_hand != t.on_hand_ledger or t.reserved != t.reserved_ledger
        ]
        return Reconciliation(checked=len(totals), mismatches=mismatches)

    # --- Movements -----------------------------------------------------------------------

    def receive(
        self,
        material_id: int,
        quantity: Decimal,
        reference: str | None,
        actor: Actor,
        context: RequestContext,
    ) -> MovementResult:
        """RECEIVE: +q on hand. Refused for inactive materials (C-15)."""
        with transaction(self._session):
            material = self._material(material_id)
            if not material.active:
                raise ConflictError(
                    "MATERIAL_INACTIVE",
                    "Stock cannot be received for an inactive material.",
                    [{"material_code": material.material_code}],
                )
            inventory.validate_movement_quantity(quantity, material.decimal_places)
            row = self._inventory.lock_balance(material.id)
            movement = inventory.receive(balance_of(row), quantity)
            line = self.record_movement(
                row,
                material,
                movement,
                TransactionType.RECEIVE,
                actor,
                context,
                reference=reference,
            )
            self._audit.record(
                action=AuditAction.INVENTORY_RECEIVE,
                entity_type=AuditEntity.INVENTORY_TRANSACTION,
                entity_id=line.id,
                actor=actor,
                context=context,
                new_value={
                    "material_code": material.material_code,
                    "quantity": format_quantity(quantity, material.decimal_places),
                    "unit": material.unit,
                    "reference": reference,
                    "on_hand_after": format_quantity(
                        movement.after.on_hand, material.decimal_places
                    ),
                },
            )
        return MovementResult(line=line, material=material, balance=movement.after)

    def adjust(
        self,
        material_id: int,
        delta: Decimal,
        reason: str,
        actor: Actor,
        context: RequestContext,
    ) -> MovementResult:
        """ADJUSTMENT: signed correction with a mandatory reason. Allowed for inactive
        materials so remaining stock can be counted or written off (C-15)."""
        with transaction(self._session):
            material = self._material(material_id)
            row = self._inventory.lock_balance(material.id)
            movement = inventory.adjust(balance_of(row), delta, material.decimal_places)
            line = self.record_movement(
                row, material, movement, TransactionType.ADJUSTMENT, actor, context, reason=reason
            )
            places = material.decimal_places
            self._audit.record(
                action=AuditAction.INVENTORY_ADJUSTMENT,
                entity_type=AuditEntity.INVENTORY_TRANSACTION,
                entity_id=line.id,
                actor=actor,
                context=context,
                old_value={"on_hand": format_quantity(_on_hand_before(movement), places)},
                new_value={
                    "material_code": material.material_code,
                    "quantity_delta": format_quantity(delta, places),
                    "unit": material.unit,
                    "on_hand": format_quantity(movement.after.on_hand, places),
                },
                reason=reason,
            )
        return MovementResult(line=line, material=material, balance=movement.after)

    def issue(
        self, order_line_id: int, quantity: Decimal, actor: Actor, context: RequestContext
    ) -> OrderMovementResult:
        """ISSUE (D-10, C-05): only for a READY_TO_PRODUCE order, never more than what is
        still reserved on the line. Lock order: order -> order line -> balance (B12)."""
        return self._order_movement(order_line_id, quantity, TransactionType.ISSUE, actor, context)

    def return_stock(
        self, order_line_id: int, quantity: Decimal, actor: Actor, context: RequestContext
    ) -> OrderMovementResult:
        """RETURN (B6, C-05): only for a CANCELLED or COMPLETED order, at most what was
        issued and not yet returned."""
        return self._order_movement(order_line_id, quantity, TransactionType.RETURN, actor, context)

    def _order_movement(
        self,
        order_line_id: int,
        quantity: Decimal,
        kind: TransactionType,
        actor: Actor,
        context: RequestContext,
    ) -> OrderMovementResult:
        orders = ProductionOrderRepository(self._session)
        with transaction(self._session):
            peek = orders.get_line(order_line_id)
            if peek is None:
                raise BusinessValidationError(
                    "ORDER_MATERIAL_NOT_FOUND",
                    "Production order material line does not exist.",
                    [{"order_material_id": order_line_id}],
                )
            order = orders.get_for_update(peek.production_order_id)
            if order is None:  # lines are never orphaned (FK)
                raise RuntimeError(f"order of line {order_line_id} is missing")
            line = orders.get_line_for_update(order_line_id)
            if line is None:
                raise RuntimeError(f"line {order_line_id} vanished under the order lock")
            ensure_stock_movement_allowed(OrderStatus(order.status), kind.value)

            material = self._inventory.materials_by_id([line.material_id])[line.material_id]
            places = material.decimal_places
            inventory.validate_movement_quantity(quantity, places)
            row = self._inventory.lock_balance(material.id)
            if kind is TransactionType.ISSUE:
                inventory.ensure_issuable(quantity, line.reserved_quantity, places)
                movement = inventory.issue(balance_of(row), quantity)
                line.reserved_quantity -= quantity
                line.issued_quantity += quantity
                action = AuditAction.INVENTORY_ISSUE
            else:
                inventory.ensure_returnable(
                    quantity, line.issued_quantity, line.returned_quantity, places
                )
                movement = inventory.return_to_stock(balance_of(row), quantity)
                line.returned_quantity += quantity
                action = AuditAction.INVENTORY_RETURN
            ledger_line = self.record_movement(
                row,
                material,
                movement,
                kind,
                actor,
                context,
                production_order_id=order.id,
                order_material_id=line.id,
            )
            self._audit.record(
                action=action,
                entity_type=AuditEntity.PRODUCTION_ORDER_MATERIAL,
                entity_id=line.id,
                actor=actor,
                context=context,
                new_value={
                    "material_code": material.material_code,
                    "quantity": format_quantity(quantity, places),
                    "unit": material.unit,
                    "order_number": order.order_number,
                },
            )
        return OrderMovementResult(
            line=ledger_line,
            material=material,
            balance=movement.after,
            order=order,
            order_line=line,
        )

    def _material(self, material_id: int) -> Material:
        material = self._inventory.get_material_for_share(material_id)
        if material is None:
            raise BusinessValidationError(
                "MATERIAL_NOT_FOUND",
                "Material does not exist.",
                [{"material_id": material_id}],
            )
        return material

    def record_movement(
        self,
        row: Inventory,
        material: Material,
        movement: Movement,
        kind: TransactionType,
        actor: Actor,
        context: RequestContext,
        *,
        reference: str | None = None,
        reason: str | None = None,
        production_order_id: int | None = None,
        order_material_id: int | None = None,
    ) -> InventoryTransaction:
        """Update the balance and write its single ledger line (BR-INV-03).

        Runs inside the caller's transaction, with the balance row already locked.
        """
        row.on_hand_quantity = movement.after.on_hand
        row.reserved_quantity = movement.after.reserved
        self._session.flush()
        return self._inventory.add_transaction(
            InventoryTransaction(
                type=kind.value,
                material_id=material.id,
                warehouse_id=row.warehouse_id,
                on_hand_delta=movement.on_hand_delta,
                reserved_delta=movement.reserved_delta,
                on_hand_after=movement.after.on_hand,
                reserved_after=movement.after.reserved,
                production_order_id=production_order_id,
                order_material_id=order_material_id,
                reference=reference,
                reason=reason,
                created_by=actor.user_id,
                request_id=context.request_id,
            )
        )


def balance_of(row: Inventory) -> Balance:
    return Balance(on_hand=row.on_hand_quantity, reserved=row.reserved_quantity)


def _on_hand_before(movement: Movement) -> Decimal:
    return movement.after.on_hand - movement.on_hand_delta
