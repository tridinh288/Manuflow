from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.permissions import Permission
from app.domain.order_state import OrderStatus, allowed_actions
from app.domain.quantities import format_quantity
from app.models.master_data import Material
from app.models.production import ProductionOrderMaterial
from app.schemas.common import MAX_ID
from app.schemas.dashboard import ratio
from app.services.production_service import (
    MaterialCheck,
    OperationMetrics,
    OperationsView,
    OrderView,
    ReservationResult,
)


class OrderCreateRequest(BaseModel):
    # BR-AUTH-01: status, order_number, created_by... are rejected, never trusted.
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0, le=MAX_ID)
    # D-06 is checked by the domain so 0, -1, 1.5, "10" and true all get INVALID_QUANTITY.
    planned_quantity: Any
    due_date: AwareDatetime  # D-23: stored in UTC
    notes: str | None = Field(default=None, max_length=1000)


class OrderUpdateRequest(BaseModel):
    """PATCH (DRAFT only): planned_quantity, due_date and notes."""

    model_config = ConfigDict(extra="forbid")

    planned_quantity: Any = None
    due_date: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> Self:
        nulls = [
            name
            for name in ("planned_quantity", "due_date")
            if name in self.model_fields_set and getattr(self, name) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class OrderResponse(BaseModel):
    id: int
    order_number: str
    product_id: int
    product_code: str
    planned_quantity: int
    completed_quantity: int | None
    due_date: datetime
    status: OrderStatus
    notes: str | None
    cancel_reason: str | None
    bom_header_id: int | None
    routing_id: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    # BR-PO-05: what the current user may do now, decided by the backend.
    allowed_actions: list[str]

    @classmethod
    def of(cls, view: OrderView, permissions: Iterable[Permission]) -> "OrderResponse":
        order, product = view.order, view.product
        status = OrderStatus(order.status)
        return cls(
            id=order.id,
            order_number=order.order_number,
            product_id=product.id,
            product_code=product.product_code,
            planned_quantity=order.planned_quantity,
            completed_quantity=order.completed_quantity,
            due_date=order.due_date,
            status=status,
            notes=order.notes,
            cancel_reason=order.cancel_reason,
            bom_header_id=order.bom_header_id,
            routing_id=order.routing_id,
            started_at=order.started_at,
            completed_at=order.completed_at,
            created_at=order.created_at,
            allowed_actions=allowed_actions(status, permissions),
        )


class MaterialCheckResponse(BaseModel):
    """BR-INV-05: every material with required, available (before reserving), shortage."""

    material_id: int
    material_code: str
    unit: str
    required: str
    available: str
    shortage: str

    @classmethod
    def of(cls, check: MaterialCheck) -> "MaterialCheckResponse":
        places = check.decimal_places
        return cls(
            material_id=check.material_id,
            material_code=check.material_code,
            unit=check.unit,
            required=format_quantity(check.required, places),
            available=format_quantity(check.available, places),
            shortage=format_quantity(check.shortage, places),
        )


class ReservationResponse(OrderResponse):
    """plan / check-materials: the order after the action plus the material check.

    Shortage is a successful outcome, not an error: the order is saved in
    MATERIAL_SHORTAGE (B7), so the response is 200 with ``reserved: false``.
    """

    reserved: bool
    material_check: list[MaterialCheckResponse]

    @classmethod
    def of_result(
        cls, result: ReservationResult, permissions: Iterable[Permission]
    ) -> "ReservationResponse":
        order = OrderResponse.of(result.view, permissions)
        return cls(
            **order.model_dump(),
            reserved=all(check.shortage == 0 for check in result.checks),
            material_check=[MaterialCheckResponse.of(check) for check in result.checks],
        )


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class OrderMaterialResponse(BaseModel):
    id: int
    material_id: int
    material_code: str
    unit: str
    required_quantity: str
    reserved_quantity: str
    issued_quantity: str
    returned_quantity: str
    shortage_quantity: str

    @classmethod
    def of(cls, line: ProductionOrderMaterial, material: Material) -> "OrderMaterialResponse":
        places = material.decimal_places
        return cls(
            id=line.id,
            material_id=material.id,
            material_code=material.material_code,
            unit=material.unit,
            required_quantity=format_quantity(line.required_quantity, places),
            reserved_quantity=format_quantity(line.reserved_quantity, places),
            issued_quantity=format_quantity(line.issued_quantity, places),
            returned_quantity=format_quantity(line.returned_quantity, places),
            shortage_quantity=format_quantity(line.shortage_quantity, places),
        )


class OperationResponse(BaseModel):
    id: int
    sequence: int
    operation_type: str
    work_center_id: int
    work_center_code: str
    status: str
    good_quantity: int
    rejected_quantity: int
    started_at: datetime | None
    completed_at: datetime | None
    progress: float  # B8: 1 when COMPLETED, otherwise processed / planned
    yield_rate: float | None  # good / processed

    @classmethod
    def of(cls, metrics: OperationMetrics) -> "OperationResponse":
        operation, center = metrics.operation, metrics.work_center
        return cls(
            id=operation.id,
            sequence=operation.sequence,
            operation_type=operation.operation_type,
            work_center_id=center.id,
            work_center_code=center.code,
            status=operation.status,
            good_quantity=operation.good_quantity,
            rejected_quantity=operation.rejected_quantity,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
            progress=ratio(metrics.progress),
            yield_rate=ratio(metrics.yield_rate) if metrics.yield_rate is not None else None,
        )


class OperationsResponse(BaseModel):
    items: list[OperationResponse]
    total: int
    workflow_progress: float  # mean of operation progresses (used by risk, B9)
    finished_progress: float  # good(last) / planned

    @classmethod
    def of(cls, view: OperationsView) -> "OperationsResponse":
        return cls(
            items=[OperationResponse.of(row) for row in view.rows],
            total=len(view.rows),
            workflow_progress=ratio(view.workflow_progress),
            finished_progress=ratio(view.finished_progress),
        )
