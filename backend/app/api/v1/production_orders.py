from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_production_order_service, get_request_context
from app.api.idempotency import OptionalIdempotency, RequiredIdempotency
from app.core.permissions import Permission
from app.schemas.production import (
    CancelRequest,
    OrderCreateRequest,
    OrderResponse,
    OrderUpdateRequest,
    ReservationResponse,
)
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.production_service import (
    NewOrder,
    OrderUpdate,
    OrderView,
    ProductionOrderService,
    ReservationResult,
)

router = APIRouter(prefix="/production-orders", tags=["production orders"])

Creator = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CREATE))]
Planner = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_PLAN))]
Checker = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CHECK_MATERIALS))]
Starter = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_START))]
Canceller = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CANCEL))]
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


@router.post("/{order_id}/plan", response_model=ReservationResponse)
def plan_order(
    order_id: int,
    user: Planner,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """B7 plan (D-22: Idempotency-Key required). Ends READY_TO_PRODUCE or MATERIAL_SHORTAGE."""

    def to_response(result: ReservationResult) -> ReservationResponse:
        return ReservationResponse.of_result(result, user.permissions)

    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.plan(order_id, user.actor, context),
        to_response=to_response,
    )


@router.post("/{order_id}/check-materials", response_model=ReservationResponse)
def check_materials(
    order_id: int,
    user: Checker,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """D-09: retry the reservation of a MATERIAL_SHORTAGE order (C-04: key required)."""

    def to_response(result: ReservationResult) -> ReservationResponse:
        return ReservationResponse.of_result(result, user.permissions)

    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.check_materials(order_id, user.actor, context),
        to_response=to_response,
    )


@router.post("/{order_id}/start", response_model=OrderResponse)
def start_order(
    order_id: int,
    user: Starter,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    """D-11: READY_TO_PRODUCE -> IN_PROGRESS once every material is issued in full."""

    def to_response(view: OrderView) -> OrderResponse:
        return OrderResponse.of(view, user.permissions)

    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.start(order_id, user.actor, context),
        to_response=to_response,
    )


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    body: CancelRequest,
    user: Canceller,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """D-13: cancel before production starts; releases reservations (C-04: key required)."""

    def to_response(view: OrderView) -> OrderResponse:
        return OrderResponse.of(view, user.permissions)

    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.cancel(order_id, body.reason, user.actor, context),
        to_response=to_response,
    )
