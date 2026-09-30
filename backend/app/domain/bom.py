"""BOM version rules (BR-BOM-01..04, D-02, D-03): pure validation, no I/O."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.quantities import MAX_DECIMAL_PLACES, ensure_scale


class VersionStatus(StrEnum):
    """Shared by BOM and routing versions (D-03)."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class BomLine:
    material_id: int
    qty_per_unit: Decimal
    scrap_rate: Decimal = Decimal(0)


def ensure_editable(status: VersionStatus) -> None:
    """BR-BOM-03 / D-03: ACTIVE and RETIRED versions are frozen."""
    if status is not VersionStatus.DRAFT:
        raise ConflictError(
            "VERSION_NOT_EDITABLE",
            "Only DRAFT versions can be changed; create a new version instead.",
            [{"status": status.value}],
        )


def validate_lines(lines: list[BomLine]) -> None:
    """BR-BOM-01 (quantities) and BR-BOM-02 (each material at most once)."""
    duplicates = sorted(
        material_id
        for material_id, n in Counter(line.material_id for line in lines).items()
        if n > 1
    )
    if duplicates:
        raise BusinessValidationError(
            "DUPLICATE_MATERIAL",
            "Each material may appear only once in a BOM version.",
            [{"material_id": material_id} for material_id in duplicates],
        )
    for line in lines:
        if line.qty_per_unit <= 0:
            raise BusinessValidationError(
                "INVALID_QTY_PER_UNIT",
                "qty_per_unit must be greater than 0.",
                [{"material_id": line.material_id}],
            )
        ensure_scale(line.qty_per_unit, MAX_DECIMAL_PLACES, field="qty_per_unit")
        if not Decimal(0) <= line.scrap_rate < Decimal(1):
            raise BusinessValidationError(
                "INVALID_SCRAP_RATE",
                "scrap_rate must be at least 0 and below 1.",
                [{"material_id": line.material_id}],
            )
        ensure_scale(line.scrap_rate, MAX_DECIMAL_PLACES, field="scrap_rate")
