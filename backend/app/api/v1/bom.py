from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_bom_service, get_request_context
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.domain.bom import BomLine
from app.schemas.bom import BomItemsRequest, BomResponse, to_decimal
from app.schemas.common import Page
from app.services.auth_service import AuthenticatedUser
from app.services.bom_service import BomService
from app.services.context import RequestContext

router = APIRouter(tags=["bom"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_READ))]
Writer = Annotated[AuthenticatedUser, Depends(require(Permission.BOM_WRITE))]
Service = Annotated[BomService, Depends(get_bom_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("/products/{product_id}/boms")
def list_bom_versions(product_id: int, _: Reader, service: Service) -> Page[BomResponse]:
    views = service.list_versions(product_id)
    return Page(items=[BomResponse.of(view) for view in views], total=len(views))


@router.post(
    "/products/{product_id}/boms",
    status_code=status.HTTP_201_CREATED,
    response_model=BomResponse,
)
def create_bom_draft(
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
        to_response=BomResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/boms/{bom_id}/items", response_model=BomResponse)
def replace_bom_items(
    bom_id: int,
    body: BomItemsRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    lines = [
        BomLine(
            material_id=item.material_id,
            qty_per_unit=to_decimal(item.qty_per_unit),
            scrap_rate=to_decimal(item.scrap_rate),
        )
        for item in body.items
    ]
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.replace_items(bom_id, lines, user.actor, context),
        to_response=BomResponse.of,
    )


@router.post("/boms/{bom_id}/activate", response_model=BomResponse)
def activate_bom(
    bom_id: int,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    return idempotent.respond(
        user=user,
        payload=None,
        operation=lambda: service.activate(bom_id, user.actor, context),
        to_response=BomResponse.of,
    )
