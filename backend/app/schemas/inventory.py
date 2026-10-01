from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.inventory import TransactionType
from app.domain.quantities import format_quantity
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material
from app.repositories.inventory_repository import LedgerTotals
from app.schemas.common import MAX_ID
from app.services.inventory_service import (
    MovementResult,
    OrderMovementResult,
    Reconciliation,
)

# B13: quantities are strings; the per-material scale is checked by the domain (B6).
QuantityString = Annotated[str, StringConstraints(pattern=r"^\d{1,14}(\.\d{1,4})?$", strict=True)]


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int = Field(gt=0, le=MAX_ID)
    quantity: QuantityString
    reference: str | None = Field(default=None, min_length=1, max_length=64)


SignedQuantityString = Annotated[
    str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$", strict=True)
]


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int = Field(gt=0, le=MAX_ID)
    quantity_delta: SignedQuantityString  # negative decreases stock
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class MovementResponse(BaseModel):
    transaction_id: int
    type: TransactionType
    material_id: int
    material_code: str
    unit: str
    on_hand_delta: str
    reserved_delta: str
    on_hand_quantity: str
    reserved_quantity: str
    available_quantity: str
    reference: str | None
    reason: str | None
    created_at: datetime

    @classmethod
    def of(cls, result: MovementResult) -> "MovementResponse":
        line, material, balance = result.line, result.material, result.balance
        places = material.decimal_places

        def fmt(value: Decimal) -> str:
            return format_quantity(value, places)

        return cls(
            transaction_id=line.id,
            type=TransactionType(line.type),
            material_id=material.id,
            material_code=material.material_code,
            unit=material.unit,
            on_hand_delta=fmt(line.on_hand_delta),
            reserved_delta=fmt(line.reserved_delta),
            on_hand_quantity=fmt(balance.on_hand),
            reserved_quantity=fmt(balance.reserved),
            available_quantity=fmt(balance.available),
            reference=line.reference,
            reason=line.reason,
            created_at=line.created_at,
        )


def to_decimal(value: str) -> Decimal:
    return Decimal(value)


class BalanceResponse(BaseModel):
    material_id: int
    material_code: str
    material_name: str
    unit: str
    active: bool
    on_hand_quantity: str
    reserved_quantity: str
    available_quantity: str
    minimum_stock: str
    low_stock: bool
    below_minimum_by: str

    @classmethod
    def of(cls, row: Inventory, material: Material) -> "BalanceResponse":
        places = material.decimal_places
        available = row.on_hand_quantity - row.reserved_quantity
        shortfall = max(Decimal(0), material.minimum_stock - available)
        return cls(
            material_id=material.id,
            material_code=material.material_code,
            material_name=material.name,
            unit=material.unit,
            active=material.active,
            on_hand_quantity=format_quantity(row.on_hand_quantity, places),
            reserved_quantity=format_quantity(row.reserved_quantity, places),
            available_quantity=format_quantity(available, places),
            minimum_stock=format_quantity(material.minimum_stock, places),
            low_stock=available < material.minimum_stock,  # D-25
            below_minimum_by=format_quantity(shortfall, places),
        )


class TransactionResponse(BaseModel):
    id: int
    type: TransactionType
    material_id: int
    material_code: str
    unit: str
    on_hand_delta: str
    reserved_delta: str
    on_hand_after: str
    reserved_after: str
    production_order_id: int | None
    order_material_id: int | None
    reference: str | None
    reason: str | None
    created_by: int | None
    request_id: str | None
    created_at: datetime

    @classmethod
    def of(cls, line: InventoryTransaction, material: Material) -> "TransactionResponse":
        places = material.decimal_places
        return cls(
            id=line.id,
            type=TransactionType(line.type),
            material_id=material.id,
            material_code=material.material_code,
            unit=material.unit,
            on_hand_delta=format_quantity(line.on_hand_delta, places),
            reserved_delta=format_quantity(line.reserved_delta, places),
            on_hand_after=format_quantity(line.on_hand_after, places),
            reserved_after=format_quantity(line.reserved_after, places),
            production_order_id=line.production_order_id,
            order_material_id=line.order_material_id,
            reference=line.reference,
            reason=line.reason,
            created_by=line.created_by,
            request_id=line.request_id,
            created_at=line.created_at,
        )


class MismatchResponse(BaseModel):
    material_id: int
    material_code: str
    on_hand_quantity: str
    on_hand_ledger_sum: str
    reserved_quantity: str
    reserved_ledger_sum: str

    @classmethod
    def of(cls, totals: LedgerTotals) -> "MismatchResponse":
        # Unformatted on purpose: a corrupted value may carry digits the material forbids.
        return cls(
            material_id=totals.material_id,
            material_code=totals.material_code,
            on_hand_quantity=str(totals.on_hand),
            on_hand_ledger_sum=str(totals.on_hand_ledger),
            reserved_quantity=str(totals.reserved),
            reserved_ledger_sum=str(totals.reserved_ledger),
        )


class ReconciliationResponse(BaseModel):
    consistent: bool
    checked_materials: int
    mismatches: list[MismatchResponse]

    @classmethod
    def of(cls, result: Reconciliation) -> "ReconciliationResponse":
        return cls(
            consistent=not result.mismatches,
            checked_materials=result.checked,
            mismatches=[MismatchResponse.of(m) for m in result.mismatches],
        )


class OrderMovementRequest(BaseModel):
    """ISSUE / RETURN against one material line of a production order (D-10)."""

    model_config = ConfigDict(extra="forbid")

    order_material_id: int = Field(gt=0, le=MAX_ID)
    quantity: QuantityString


class OrderMovementResponse(MovementResponse):
    production_order_id: int
    order_number: str
    order_material_id: int
    line_required_quantity: str
    line_reserved_quantity: str
    line_issued_quantity: str
    line_returned_quantity: str

    @classmethod
    def of_order(cls, result: OrderMovementResult) -> "OrderMovementResponse":
        places = result.material.decimal_places
        line = result.order_line
        return cls(
            **MovementResponse.of(result).model_dump(),
            production_order_id=result.order.id,
            order_number=result.order.order_number,
            order_material_id=line.id,
            line_required_quantity=format_quantity(line.required_quantity, places),
            line_reserved_quantity=format_quantity(line.reserved_quantity, places),
            line_issued_quantity=format_quantity(line.issued_quantity, places),
            line_returned_quantity=format_quantity(line.returned_quantity, places),
        )
