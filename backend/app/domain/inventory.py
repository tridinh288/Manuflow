"""Inventory balances and movements (B6, BR-INV-01..03, D-20): pure, no I/O.

``available = on_hand - reserved`` is always derived, never stored, and never negative.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.quantities import ensure_scale, format_quantity

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


def adjust(balance: Balance, delta: Decimal, decimal_places: int) -> Movement:
    """ADJUSTMENT: on_hand +/-q, reserved unchanged. The result may never drop below what
    is reserved for orders, so available stock never goes negative (D-20)."""
    if delta == 0:
        raise BusinessValidationError("INVALID_QUANTITY", "quantity_delta cannot be 0.")
    ensure_scale(abs(delta), decimal_places, field="quantity_delta")
    after = Balance(balance.on_hand + delta, balance.reserved)
    if after.on_hand < balance.reserved:
        raise ConflictError(
            "ADJUSTMENT_BELOW_RESERVED",
            "The adjustment would leave less stock on hand than is reserved.",
            [
                {
                    "on_hand": format_quantity(balance.on_hand, decimal_places),
                    "reserved": format_quantity(balance.reserved, decimal_places),
                    "quantity_delta": format_quantity(delta, decimal_places),
                }
            ],
        )
    _ensure_representable(after)
    return Movement(on_hand_delta=delta, reserved_delta=Decimal(0), after=after)


def reserve(balance: Balance, quantity: Decimal) -> Movement:
    """RESERVE: reserved +q, on hand unchanged; only within what is available (D-20)."""
    if quantity > balance.available:
        raise ConflictError("INSUFFICIENT_STOCK", "Not enough available stock to reserve.", [])
    after = Balance(balance.on_hand, balance.reserved + quantity)
    _ensure_representable(after)
    return Movement(on_hand_delta=Decimal(0), reserved_delta=quantity, after=after)


def release(balance: Balance, quantity: Decimal) -> Movement:
    """RELEASE: give back what an order still reserves; reserved -q (B6, D-13)."""
    after = Balance(balance.on_hand, balance.reserved - quantity)
    _ensure_representable(after)
    return Movement(on_hand_delta=Decimal(0), reserved_delta=-quantity, after=after)


def issue(balance: Balance, quantity: Decimal) -> Movement:
    """ISSUE: hand reserved stock to production; on_hand -q and reserved -q (D-10)."""
    after = Balance(balance.on_hand - quantity, balance.reserved - quantity)
    _ensure_representable(after)
    return Movement(on_hand_delta=-quantity, reserved_delta=-quantity, after=after)


def return_to_stock(balance: Balance, quantity: Decimal) -> Movement:
    """RETURN: issued material comes back; on_hand +q, reserved unchanged (B6)."""
    after = Balance(balance.on_hand + quantity, balance.reserved)
    _ensure_representable(after)
    return Movement(on_hand_delta=quantity, reserved_delta=Decimal(0), after=after)


def ensure_issuable(quantity: Decimal, still_reserved: Decimal, decimal_places: int) -> None:
    """D-10: never more than what is still reserved on the order's line."""
    if quantity > still_reserved:
        raise ConflictError(
            "EXCEEDS_RESERVED",
            "The quantity exceeds what is still reserved for this order line.",
            [
                {
                    "quantity": format_quantity(quantity, decimal_places),
                    "still_reserved": format_quantity(still_reserved, decimal_places),
                }
            ],
        )


def ensure_returnable(
    quantity: Decimal, issued: Decimal, returned: Decimal, decimal_places: int
) -> None:
    """B6: RETURN q <= issued - returned for the order's line."""
    if quantity > issued - returned:
        raise ConflictError(
            "EXCEEDS_RETURNABLE",
            "The quantity exceeds what was issued and not yet returned.",
            [
                {
                    "quantity": format_quantity(quantity, decimal_places),
                    "returnable": format_quantity(issued - returned, decimal_places),
                }
            ],
        )


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
