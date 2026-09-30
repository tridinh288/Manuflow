"""B6 / D-20: pure inventory movement rules."""

from decimal import Decimal

import pytest

from app.domain.errors import BusinessValidationError
from app.domain.inventory import Balance, receive, validate_movement_quantity


def test_br_inv_03_receipt_moves_on_hand_only_and_reports_the_balance_after() -> None:
    movement = receive(Balance(Decimal("250.000"), Decimal("100")), Decimal("40.5"))
    assert (movement.on_hand_delta, movement.reserved_delta) == (Decimal("40.5"), Decimal(0))
    assert movement.after == Balance(Decimal("290.500"), Decimal("100"))
    assert movement.after.available == Decimal("190.500")


@pytest.mark.parametrize(
    ("quantity", "places", "code"),
    [
        ("0", 3, "INVALID_QUANTITY"),
        ("-1", 3, "INVALID_QUANTITY"),
        ("1.5", 0, "INVALID_QUANTITY_SCALE"),
        ("0.0001", 3, "INVALID_QUANTITY_SCALE"),
    ],
)
def test_b6_movement_quantity_positive_and_within_scale(
    quantity: str, places: int, code: str
) -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_movement_quantity(Decimal(quantity), places)
    assert exc_info.value.code == code


def test_br_inv_02_receipt_beyond_decimal_18_4_is_rejected() -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        receive(Balance(Decimal("99999999999999"), Decimal(0)), Decimal("1"))
    assert exc_info.value.code == "QUANTITY_TOO_LARGE"
