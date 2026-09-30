from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_request_context, get_routing_service
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.domain.routing import RoutingStepSpec
from app.schemas.common import Page
from app.schemas.routing import RoutingResponse, RoutingStepsRequest
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.routing_service import RoutingService

router = APIRouter(tags=["routing"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_READ))]
Writer = Annotated[AuthenticatedUser, Depends(require(Permission.ROUTING_WRITE))]
Service = Annotated[RoutingService, Depends(get_routing_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("/products/{product_id}/routings")
def list_routing_versions(product_id: int, _: Reader, service: Service) -> Page[RoutingResponse]:
    views = service.list_versions(product_id)
    return Page(items=[RoutingResponse.of(view) for view in views], total=len(views))


@router.post(
    "/products/{product_id}/routings",
    status_code=status.HTTP_201_CREATED,
    response_model=RoutingResponse,
)
def create_routing_draft(
    product_id: int,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.create_draft(product_id, user.actor, context),
        to_response=RoutingResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/routings/{routing_id}/steps", response_model=RoutingResponse)
def replace_routing_steps(
    routing_id: int,
    body: RoutingStepsRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    steps = [
        RoutingStepSpec(step.sequence, step.operation_type, step.work_center_id)
        for step in body.steps
    ]
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.replace_steps(routing_id, steps, user.actor, context),
        to_response=RoutingResponse.of,
    )


@router.post("/routings/{routing_id}/activate", response_model=RoutingResponse)
def activate_routing(
    routing_id: int,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.activate(routing_id, user.actor, context),
        to_response=RoutingResponse.of,
    )
