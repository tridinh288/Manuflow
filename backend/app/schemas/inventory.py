from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.inventory import TransactionType
from app.domain.quantities import format_quantity
from app.services.inventory_service import MovementResult

# B13: quantities are strings; the per-material scale is checked by the domain (B6).
QuantityString = Annotated[str, StringConstraints(pattern=r"^\d{1,14}(\.\d{1,4})?$", strict=True)]


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int = Field(gt=0)
    quantity: QuantityString
    reference: str | None = Field(default=None, min_length=1, max_length=64)


SignedQuantityString = Annotated[
    str, StringConstraints(pattern=r"^-?\d{1,14}(\.\d{1,4})?$", strict=True)
]


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int = Field(gt=0)
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
