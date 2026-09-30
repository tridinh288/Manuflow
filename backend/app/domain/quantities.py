"""Material quantities: always ``Decimal``, never ``float`` (B2, B6, D-05).

A quantity with more fractional digits than its material allows is rejected, never
rounded silently (B6). ``quantize_up`` is the one rounding function of the system (D-05).
"""

from decimal import ROUND_CEILING, Decimal

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
    """Canonical string for the API (B13): ``Decimal("204")``, 3 -> ``"204.000"``.

    Only pads; a value with more significant decimals is a bug upstream, never rounded.
    """
    if scale_of(value.normalize()) > decimal_places:
        raise ValueError(f"{value} has more than {decimal_places} decimal places")
    return str(value.quantize(Decimal(1).scaleb(-decimal_places)))


def quantize_up(value: Decimal, decimal_places: int) -> Decimal:
    """D-05: round *up* to the material's decimal places (58.8 pcs -> 59 pcs).

    Rounding down would leave the shop floor short; the only rounding in the system.
    """
    return value.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_CEILING)
