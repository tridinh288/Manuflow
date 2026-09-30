"""Test 1 and 2 of B15: BOM explosion as a pure function (BR-BOM-05, D-05, D-06)."""

from decimal import Decimal

import pytest

from app.domain.errors import BusinessValidationError
from app.domain.explode import ExplosionLine, explode, validate_order_quantity
from app.domain.quantities import format_quantity, quantize_up

# The worked example of B5, verbatim.
STEEL = ExplosionLine(1, "STEEL-001", "kg", 3, Decimal("2.0000"), Decimal("0.02"))
BOLT = ExplosionLine(2, "BOLT-M8", "pcs", 0, Decimal("8"), Decimal("0.05"))
PAINT = ExplosionLine(3, "PAINT-RED", "kg", 3, Decimal("0.2000"), Decimal("0"))

B5_EXPECTED = {
    100: {"BOLT-M8": "840", "PAINT-RED": "20.000", "STEEL-001": "204.000"},
    7: {"BOLT-M8": "59", "PAINT-RED": "1.400", "STEEL-001": "14.280"},
}


@pytest.mark.parametrize("quantity", [100, 7])
def test_br_bom_05_worked_example_of_b5(quantity: int) -> None:
    result = explode([STEEL, BOLT, PAINT], quantity)
    assert {
        r.material_code: format_quantity(r.required_quantity, r.decimal_places) for r in result
    } == B5_EXPECTED[quantity]


def test_br_bom_05_bolts_58_8_round_up_to_59() -> None:
    [bolt] = explode([BOLT], 7)
    assert BOLT.qty_per_unit * 7 * (1 + BOLT.scrap_rate) == Decimal("58.800")
    assert bolt.required_quantity == Decimal("59")


def test_br_bom_05_result_is_sorted_by_material_code_and_decimal_only() -> None:
    result = explode([STEEL, PAINT, BOLT], 100)
    assert [r.material_code for r in result] == ["BOLT-M8", "PAINT-RED", "STEEL-001"]
    assert all(isinstance(r.required_quantity, Decimal) for r in result)


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        ("58.8", 0, "59"),
        ("58.0", 0, "58"),
        ("14.2800", 3, "14.280"),
        ("14.2801", 3, "14.281"),  # any excess rounds up, never down
        ("0.0001", 0, "1"),
        ("1.23456", 4, "1.2346"),
    ],
)
def test_d05_quantize_up_always_rounds_up(value: str, places: int, expected: str) -> None:
    assert quantize_up(Decimal(value), places) == Decimal(expected)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, 1.0, True, "100", None], ids=repr)
def test_d06_invalid_quantity_is_rejected(quantity: object) -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_order_quantity(quantity)
    assert exc_info.value.code == "INVALID_QUANTITY"


def test_br_bom_05_result_beyond_decimal_18_4_is_rejected() -> None:
    huge = ExplosionLine(9, "HUGE", "kg", 3, Decimal("99999999"), Decimal("0"))
    with pytest.raises(BusinessValidationError) as exc_info:
        explode([huge], 10_000_000)
    assert exc_info.value.code == "QUANTITY_TOO_LARGE"


def test_b13_formatting_never_rounds_silently() -> None:
    with pytest.raises(ValueError, match="decimal places"):
        format_quantity(Decimal("58.8"), 0)
