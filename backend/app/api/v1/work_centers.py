from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_request_context, get_work_center_service
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.master_data import (
    WorkCenterCreateRequest,
    WorkCenterResponse,
    WorkCenterUpdateRequest,
)
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.master_data_service import NewWorkCenter, WorkCenterChanges, WorkCenterService

router = APIRouter(prefix="/work-centers", tags=["work centers"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_READ))]
Writer = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_WRITE))]
Service = Annotated[WorkCenterService, Depends(get_work_center_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("")
def list_work_centers(
    _: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    active: bool | None = None,
) -> Page[WorkCenterResponse]:
    work_centers, total = service.list(limit, offset, active)
    return Page(items=[WorkCenterResponse.of(w) for w in work_centers], total=total)


@router.get("/{work_center_id}")
def get_work_center(work_center_id: int, _: Reader, service: Service) -> WorkCenterResponse:
    return WorkCenterResponse.of(service.get(work_center_id))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkCenterResponse)
def create_work_center(
    body: WorkCenterCreateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    data = NewWorkCenter(code=body.code, name=body.name)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.create(data, user.actor, context),
        to_response=WorkCenterResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/{work_center_id}", response_model=WorkCenterResponse)
def update_work_center(
    work_center_id: int,
    body: WorkCenterUpdateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    changes = WorkCenterChanges(name=body.name)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.update(work_center_id, changes, user.actor, context),
        to_response=WorkCenterResponse.of,
    )


@router.delete("/{work_center_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_work_center(
    work_center_id: int, user: Writer, service: Service, context: Context
) -> Response:
    """D-19 + C-07: deactivates unless still in use; never deletes."""
    service.deactivate(work_center_id, user.actor, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
