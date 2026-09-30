from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.quantities import format_quantity
from app.models.master_data import Material, MaterialUnit, Product
from app.models.work_center import WorkCenter

# BR-MD-01
Code = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{3,32}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
# B13: quantities travel as strings so no client parses them as floats. A JSON number is
# rejected; the per-material scale is checked by the service (B6).
QuantityString = Annotated[str, StringConstraints(pattern=r"^\d{1,14}(\.\d{1,4})?$", strict=True)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Products -------------------------------------------------------------------------


class ProductCreateRequest(_Request):
    product_code: Code
    name: Name
    description: str | None = Field(default=None, max_length=1000)


class ProductUpdateRequest(_Request):
    """PUT: every editable field; product_code is immutable (BR-MD-01)."""

    name: Name
    description: str | None = Field(default=None, max_length=1000)


class ProductResponse(BaseModel):
    id: int
    product_code: str
    name: str
    unit: str
    description: str | None
    active: bool

    @classmethod
    def of(cls, product: Product) -> "ProductResponse":
        return cls(
            id=product.id,
            product_code=product.product_code,
            name=product.name,
            unit=product.unit,
            description=product.description,
            active=product.active,
        )


# --- Materials ------------------------------------------------------------------------


class MaterialCreateRequest(_Request):
    material_code: Code
    name: Name
    unit: MaterialUnit
    decimal_places: int = Field(ge=0, le=4)
    minimum_stock: QuantityString = "0"


class MaterialUpdateRequest(_Request):
    """PUT: code, unit and decimal places are immutable (BR-MD-01, C-14)."""

    name: Name
    minimum_stock: QuantityString


class MaterialResponse(BaseModel):
    id: int
    material_code: str
    name: str
    unit: MaterialUnit
    decimal_places: int
    minimum_stock: str
    active: bool

    @classmethod
    def of(cls, material: Material) -> "MaterialResponse":
        return cls(
            id=material.id,
            material_code=material.material_code,
            name=material.name,
            unit=MaterialUnit(material.unit),
            decimal_places=material.decimal_places,
            minimum_stock=format_quantity(material.minimum_stock, material.decimal_places),
            active=material.active,
        )


def to_decimal(quantity: str) -> Decimal:
    return Decimal(quantity)


# --- Work centers ---------------------------------------------------------------------


class WorkCenterCreateRequest(_Request):
    code: Code
    name: Name


class WorkCenterUpdateRequest(_Request):
    name: Name


class WorkCenterResponse(BaseModel):
    id: int
    code: str
    name: str
    active: bool

    @classmethod
    def of(cls, work_center: WorkCenter) -> "WorkCenterResponse":
        return cls(
            id=work_center.id,
            code=work_center.code,
            name=work_center.name,
            active=work_center.active,
        )
