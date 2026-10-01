"""Inventory balances and movements (B6, BR-INV-01..03, D-20): pure, no I/O.

``available = on_hand - reserved`` is always derived, never stored, and never negative.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.quantities import ensure_scale

# DECIMAL(18,4) holds at most 14 integer digits.
MAX_BALANCE = Decimal(10) ** 14


class TransactionType(StrEnum):
    RECEIVE = "RECEIVE"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"


@dataclass(frozen=True)
class Balance:
    on_hand: Decimal
    reserved: Decimal

    @property
    def available(self) -> Decimal:
        return self.on_hand - self.reserved


@dataclass(frozen=True)
class Movement:
    """One ledger line: signed deltas and the balance after them (BR-INV-03)."""

    on_hand_delta: Decimal
    reserved_delta: Decimal
    after: Balance


def validate_movement_quantity(quantity: Decimal, decimal_places: int) -> None:
    """A movement quantity is positive and within the material's scale (B6)."""
    if quantity <= 0:
        raise BusinessValidationError("INVALID_QUANTITY", "Quantity must be greater than 0.")
    ensure_scale(quantity, decimal_places, field="quantity")


def receive(balance: Balance, quantity: Decimal) -> Movement:
    """RECEIVE: on_hand +q, reserved unchanged (B6)."""
    after = Balance(balance.on_hand + quantity, balance.reserved)
    _ensure_representable(after)
    return Movement(on_hand_delta=quantity, reserved_delta=Decimal(0), after=after)


def _ensure_representable(balance: Balance) -> None:
    if balance.on_hand >= MAX_BALANCE:
        raise BusinessValidationError(
            "QUANTITY_TOO_LARGE", "The resulting stock exceeds the supported range."
        )
    if balance.on_hand < 0 or balance.reserved < 0 or balance.reserved > balance.on_hand:
        # D-20: defended here, by the service and by the database CHECKs.
        raise ConflictError(
            "INVALID_BALANCE", "The movement would leave an impossible stock balance."
        )
