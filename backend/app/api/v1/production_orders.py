from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_production_order_service, get_request_context
from app.api.idempotency import OptionalIdempotency, RequiredIdempotency
from app.core.permissions import Permission
from app.domain.order_state import OrderStatus
from app.domain.scope import work_center_scope
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.production import (
    CancelRequest,
    OperationsResponse,
    OrderCreateRequest,
    OrderMaterialResponse,
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

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_READ))]
Creator = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CREATE))]
Planner = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_PLAN))]
Checker = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CHECK_MATERIALS))]
Starter = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_START))]
Canceller = Annotated[AuthenticatedUser, Depends(require(Permission.ORDER_CANCEL))]
Service = Annotated[ProductionOrderService, Depends(get_production_order_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


def _scope(user: AuthenticatedUser) -> int | None:
    """BR-AUTH-03: a WORKER only sees orders and operations at their work center."""
    return work_center_scope(user.role, user.work_center_id)


@router.get("")
def list_orders(
    user: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    status: OrderStatus | None = None,
    product_id: int | None = None,
) -> Page[OrderResponse]:
    """Orders by due date; ``allowed_actions`` per order for this user (BR-PO-05)."""
    views, total = service.list_orders(limit, offset, _scope(user), status, product_id)
    return Page(items=[OrderResponse.of(v, user.permissions) for v in views], total=total)


@router.get("/{order_id}")
def get_order(order_id: int, user: Reader, service: Service) -> OrderResponse:
    return OrderResponse.of(service.get_order(order_id, _scope(user)), user.permissions)


@router.get("/{order_id}/materials")
def list_order_materials(
    order_id: int, user: Reader, service: Service
) -> Page[OrderMaterialResponse]:
    rows = service.list_materials(order_id, _scope(user))
    return Page(items=[OrderMaterialResponse.of(line, m) for line, m in rows], total=len(rows))


@router.get("/{order_id}/operations")
def list_order_operations(order_id: int, user: Reader, service: Service) -> OperationsResponse:
    return OperationsResponse.of(service.list_operations(order_id, _scope(user)))


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
