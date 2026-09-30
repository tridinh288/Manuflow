from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_material_service, get_request_context
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.master_data import (
    MaterialCreateRequest,
    MaterialResponse,
    MaterialUpdateRequest,
    to_decimal,
)
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.master_data_service import MaterialChanges, MaterialService, NewMaterial

router = APIRouter(prefix="/materials", tags=["materials"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_READ))]
Writer = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_WRITE))]
Service = Annotated[MaterialService, Depends(get_material_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("")
def list_materials(
    _: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    active: bool | None = None,
) -> Page[MaterialResponse]:
    materials, total = service.list(limit, offset, active)
    return Page(items=[MaterialResponse.of(m) for m in materials], total=total)


@router.get("/{material_id}")
def get_material(material_id: int, _: Reader, service: Service) -> MaterialResponse:
    return MaterialResponse.of(service.get(material_id))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MaterialResponse)
def create_material(
    body: MaterialCreateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    data = NewMaterial(
        material_code=body.material_code,
        name=body.name,
        unit=body.unit,
        decimal_places=body.decimal_places,
        minimum_stock=to_decimal(body.minimum_stock),
    )
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.create(data, user.actor, context),
        to_response=MaterialResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/{material_id}", response_model=MaterialResponse)
def update_material(
    material_id: int,
    body: MaterialUpdateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    changes = MaterialChanges(name=body.name, minimum_stock=to_decimal(body.minimum_stock))
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.update(material_id, changes, user.actor, context),
        to_response=MaterialResponse.of,
    )


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_material(
    material_id: int, user: Writer, service: Service, context: Context
) -> Response:
    """D-19: deactivates; never deletes. Repeating it is a no-op."""
    service.deactivate(material_id, user.actor, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
