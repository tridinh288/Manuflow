"""B6 / B13: quantity scale checks and formatting, Decimal only."""

from decimal import Decimal

import pytest

from app.domain.errors import BusinessValidationError
from app.domain.quantities import ensure_scale, format_quantity, scale_of


@pytest.mark.parametrize(
    ("value", "scale"),
    [("204", 0), ("204.000", 3), ("0.5", 1), ("1E+2", 0), ("14.28", 2)],
)
def test_scale_of(value: str, scale: int) -> None:
    assert scale_of(Decimal(value)) == scale


@pytest.mark.parametrize(
    ("value", "places"), [("58", 0), ("14.280", 2), ("20.000", 0), ("0.1234", 4)]
)
def test_b6_values_within_scale_accepted(value: str, places: int) -> None:
    # Trailing zeros do not count: "14.280" has two significant decimals.
    ensure_scale(Decimal(value), places, field="quantity")


@pytest.mark.parametrize(("value", "places"), [("58.8", 0), ("14.2801", 3), ("0.5", 0)])
def test_b6_extra_decimals_rejected_never_rounded(value: str, places: int) -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        ensure_scale(Decimal(value), places, field="quantity")
    assert exc_info.value.code == "INVALID_QUANTITY_SCALE"


@pytest.mark.parametrize(
    ("value", "places", "text"),
    [("204", 3, "204.000"), ("840", 0, "840"), ("14.28", 3, "14.280"), ("0", 4, "0.0000")],
)
def test_b13_quantities_formatted_as_strings_with_material_scale(
    value: str, places: int, text: str
) -> None:
    assert format_quantity(Decimal(value), places) == text
