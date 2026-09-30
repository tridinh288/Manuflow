"""Material quantities: always ``Decimal``, never ``float`` (B2, B6, D-05).

A quantity with more fractional digits than its material allows is rejected, never
rounded silently (B6). The one rounding function of the system, ``quantize_up``, is
added with BOM explosion (D-05).
"""

from decimal import Decimal

from app.domain.errors import BusinessValidationError

MAX_DECIMAL_PLACES = 4  # DECIMAL(18,4)


def scale_of(value: Decimal) -> int:
    """Number of fractional digits actually present (``Decimal("1.50")`` -> 2)."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def ensure_scale(value: Decimal, decimal_places: int, *, field: str) -> None:
    """Reject values with more fractional digits than the material allows (B6)."""
    if scale_of(value.normalize()) > decimal_places:
        raise BusinessValidationError(
            "INVALID_QUANTITY_SCALE",
            f"{field} allows at most {decimal_places} decimal places.",
            [{"field": field, "decimal_places": decimal_places}],
        )


def format_quantity(value: Decimal, decimal_places: int) -> str:
    """Canonical string for the API (B13): ``Decimal("204")``, 3 -> ``"204.000"``."""
    return str(value.quantize(Decimal(1).scaleb(-decimal_places)))
