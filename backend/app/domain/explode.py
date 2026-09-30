"""BOM explosion (B5, BR-BOM-05, D-05, D-06): pure, no database, no I/O.

    required_quantity = qty_per_unit x quantity x (1 + scrap_rate)

computed in ``Decimal`` and rounded *up* to the material's decimal places.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.domain.errors import BusinessValidationError
from app.domain.quantities import quantize_up

# DECIMAL(18,4) holds at most 14 integer digits.
MAX_REQUIRED_QUANTITY = Decimal(10) ** 14


@dataclass(frozen=True)
class ExplosionLine:
    material_id: int
    material_code: str
    unit: str
    decimal_places: int
    qty_per_unit: Decimal
    scrap_rate: Decimal


@dataclass(frozen=True)
class MaterialRequirement:
    material_id: int
    material_code: str
    unit: str
    decimal_places: int
    qty_per_unit: Decimal
    scrap_rate: Decimal
    required_quantity: Decimal


def validate_order_quantity(quantity: object) -> int:
    """D-06: a whole, positive number of product units. ``True`` and ``1.0`` are not."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise BusinessValidationError(
            "INVALID_QUANTITY", "Quantity must be a positive whole number of units."
        )
    return quantity


def explode(lines: Iterable[ExplosionLine], quantity: int) -> list[MaterialRequirement]:
    """One requirement per material, sorted by material code (BR-BOM-05)."""
    validate_order_quantity(quantity)
    requirements = []
    for line in lines:
        exact = line.qty_per_unit * quantity * (Decimal(1) + line.scrap_rate)
        required = quantize_up(exact, line.decimal_places)
        if required >= MAX_REQUIRED_QUANTITY:
            raise BusinessValidationError(
                "QUANTITY_TOO_LARGE",
                "The required quantity exceeds the supported range.",
                [{"material_code": line.material_code}],
            )
        requirements.append(
            MaterialRequirement(
                material_id=line.material_id,
                material_code=line.material_code,
                unit=line.unit,
                decimal_places=line.decimal_places,
                qty_per_unit=line.qty_per_unit,
                scrap_rate=line.scrap_rate,
                required_quantity=required,
            )
        )
    return sorted(requirements, key=lambda r: r.material_code)
