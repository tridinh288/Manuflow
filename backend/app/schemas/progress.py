from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.services.progress_service import ProgressResult

# BR-OP-02: whole units; true, 1.5 and "3" are rejected rather than coerced.
Delta = Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]


class ProgressRequest(BaseModel):
    """D-15: a report adds deltas; negative deltas are corrections (needs a reason)."""

    model_config = ConfigDict(extra="forbid")

    good_delta: Delta = 0
    rejected_delta: Delta = 0
    reason: str | None = Field(default=None, max_length=500)


class ProgressResponse(BaseModel):
    operation_id: int
    sequence: int
    operation_type: str
    status: str
    good_quantity: int
    rejected_quantity: int
    processed_quantity: int
    limit: int
    order_id: int
    order_number: str
    order_status: str
    completed_quantity: int | None

    @classmethod
    def of(cls, result: ProgressResult) -> "ProgressResponse":
        operation, order = result.operation, result.order
        return cls(
            operation_id=operation.id,
            sequence=operation.sequence,
            operation_type=operation.operation_type,
            status=operation.status,
            good_quantity=operation.good_quantity,
            rejected_quantity=operation.rejected_quantity,
            processed_quantity=operation.good_quantity + operation.rejected_quantity,
            limit=result.limit,
            order_id=order.id,
            order_number=order.order_number,
            order_status=order.status,
            completed_quantity=order.completed_quantity,
        )
