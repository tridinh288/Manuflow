from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_production_order_service, get_request_context
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.schemas.production import OrderCreateRequest, OrderResponse, OrderUpdateRequest
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.production_service import (
    NewOrder,
    OrderUpdate,
    OrderView,
    ProductionOrderService,
)

router = APIRouter(prefix="/production-orders", tags=["production orders"])

Creator = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CREATE))]
Service = Annotated[ProductionOrderService, Depends(get_production_order_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def create_order(
    body: OrderCreateRequest,
    user: Creator,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    data = NewOrder(body.product_id, body.planned_quantity, body.due_date, body.notes)

    def to_response(view: OrderView) -> OrderResponse:
        return OrderResponse.of(view, user.permissions)

    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.create(data, user.actor, context),
        to_response=to_response,
        status_code=status.HTTP_201_CREATED,
    )


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    body: OrderUpdateRequest,
    user: Creator,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    update = OrderUpdate(
        provided=frozenset(body.model_fields_set),
        planned_quantity=body.planned_quantity,
        due_date=body.due_date,
        notes=body.notes,
    )

    def to_response(view: OrderView) -> OrderResponse:
        return OrderResponse.of(view, user.permissions)

    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.update(order_id, update, user.actor, context),
        to_response=to_response,
    )
