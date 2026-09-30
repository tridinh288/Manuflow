"""Inventory movements (B6, BR-INV-01..03, D-20, C-15).

Every movement is one transaction that locks the material (shared) and then its balance
row (exclusive), changes the balance, writes exactly one ledger line with the balance
after the change, and writes the audit row.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.domain import inventory
from app.domain.audit import AuditAction, AuditEntity
from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.inventory import Balance, Movement, TransactionType
from app.domain.quantities import format_quantity
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material
from app.repositories.inventory_repository import InventoryRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext


@dataclass(frozen=True)
class MovementResult:
    line: InventoryTransaction
    material: Material
    balance: Balance


class InventoryService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._inventory = InventoryRepository(session)
        self._audit = AuditService(session)

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
            movement = inventory.receive(_balance(row), quantity)
            line = self._apply(
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
            movement = inventory.adjust(_balance(row), delta, material.decimal_places)
            line = self._apply(
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

    def _material(self, material_id: int) -> Material:
        material = self._inventory.get_material_for_share(material_id)
        if material is None:
            raise BusinessValidationError(
                "MATERIAL_NOT_FOUND",
                "Material does not exist.",
                [{"material_id": material_id}],
            )
        return material

    def _apply(
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
    ) -> InventoryTransaction:
        """Update the balance and write its single ledger line (BR-INV-03)."""
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
                reference=reference,
                reason=reason,
                created_by=actor.user_id,
                request_id=context.request_id,
            )
        )


def _balance(row: Inventory) -> Balance:
    return Balance(on_hand=row.on_hand_quantity, reserved=row.reserved_quantity)


def _on_hand_before(movement: Movement) -> Decimal:
    return movement.after.on_hand - movement.on_hand_delta
