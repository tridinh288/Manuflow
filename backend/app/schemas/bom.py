from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.bom import VersionStatus
from app.domain.explode import MaterialRequirement
from app.domain.quantities import MAX_DECIMAL_PLACES, format_quantity
from app.services.bom_service import BomView

# Decimals as strings (B13); BR-BOM-01 ranges are checked by the domain.
DecimalString = Annotated[str, StringConstraints(pattern=r"^\d{1,14}(\.\d{1,4})?$", strict=True)]


class BomItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: int = Field(gt=0)
    qty_per_unit: DecimalString
    scrap_rate: DecimalString = "0"


class BomItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BomItemRequest] = Field(max_length=500)


class BomItemResponse(BaseModel):
    material_id: int
    material_code: str
    unit: str
    qty_per_unit: str
    scrap_rate: str


class BomResponse(BaseModel):
    id: int
    product_id: int
    version: int
    status: VersionStatus
    activated_at: datetime | None
    items: list[BomItemResponse]

    @classmethod
    def of(cls, view: "BomView") -> "BomResponse":
        header, materials = view.header, view.materials
        return cls(
            id=header.id,
            product_id=header.product_id,
            version=header.version,
            status=VersionStatus(header.status),
            activated_at=header.activated_at,
            items=[
                BomItemResponse(
                    material_id=item.material_id,
                    material_code=materials[item.material_id].material_code,
                    unit=materials[item.material_id].unit,
                    qty_per_unit=format_quantity(item.qty_per_unit, MAX_DECIMAL_PLACES),
                    scrap_rate=format_quantity(item.scrap_rate, MAX_DECIMAL_PLACES),
                )
                for item in header.items
            ],
        )


def to_decimal(value: str) -> Decimal:
    return Decimal(value)


class ExplodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Validated by the domain so every wrong value gets 422 INVALID_QUANTITY (B5):
    # 0, -1, 1.5, "100" and true are all rejected, not coerced.
    quantity: Any
    bom_header_id: int | None = Field(default=None, gt=0)


class MaterialRequirementResponse(BaseModel):
    material_id: int
    material_code: str
    unit: str
    qty_per_unit: str
    scrap_rate: str
    required_quantity: str

    @classmethod
    def of(cls, requirement: MaterialRequirement) -> "MaterialRequirementResponse":
        return cls(
            material_id=requirement.material_id,
            material_code=requirement.material_code,
            unit=requirement.unit,
            qty_per_unit=format_quantity(requirement.qty_per_unit, MAX_DECIMAL_PLACES),
            scrap_rate=format_quantity(requirement.scrap_rate, MAX_DECIMAL_PLACES),
            required_quantity=format_quantity(
                requirement.required_quantity, requirement.decimal_places
            ),
        )


class ExplodeResponse(BaseModel):
    product_id: int
    quantity: int
    items: list[MaterialRequirementResponse]
