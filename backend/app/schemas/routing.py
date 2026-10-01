from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.bom import VersionStatus
from app.domain.routing import OperationType
from app.schemas.common import MAX_ID
from app.services.routing_service import RoutingView


class RoutingStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(gt=0, le=9999)
    operation_type: OperationType
    work_center_id: int = Field(gt=0, le=MAX_ID)


class RoutingStepsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[RoutingStepRequest] = Field(max_length=100)


class RoutingStepResponse(BaseModel):
    sequence: int
    operation_type: OperationType
    work_center_id: int
    work_center_code: str


class RoutingResponse(BaseModel):
    id: int
    product_id: int
    version: int
    status: VersionStatus
    activated_at: datetime | None
    steps: list[RoutingStepResponse]

    @classmethod
    def of(cls, view: RoutingView) -> "RoutingResponse":
        routing, work_centers = view.routing, view.work_centers
        return cls(
            id=routing.id,
            product_id=routing.product_id,
            version=routing.version,
            status=VersionStatus(routing.status),
            activated_at=routing.activated_at,
            steps=[
                RoutingStepResponse(
                    sequence=step.sequence,
                    operation_type=OperationType(step.operation_type),
                    work_center_id=step.work_center_id,
                    work_center_code=work_centers[step.work_center_id].code,
                )
                for step in routing.steps
            ],
        )
