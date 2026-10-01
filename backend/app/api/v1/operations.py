from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_progress_service, get_request_context
from app.api.idempotency import RequiredIdempotency
from app.core.permissions import Permission
from app.schemas.progress import ProgressRequest, ProgressResponse
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.progress_service import ProgressService, Reporter

router = APIRouter(prefix="/production-operations", tags=["production operations"])

# C-02: one permission on the route; a negative delta also needs operation:correct,
# checked by the service.
OperationReporter = Annotated[AuthenticatedUser, Depends(require(Permission.OPERATION_REPORT))]
Service = Annotated[ProgressService, Depends(get_progress_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.post("/{operation_id}/progress", response_model=ProgressResponse)
def report_progress(
    operation_id: int,
    body: ProgressRequest,
    user: OperationReporter,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """B8: add good/rejected deltas to one operation (D-22: Idempotency-Key required)."""
    reporter = Reporter(user.actor, user.role, user.work_center_id, user.permissions)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.report(
            operation_id,
            body.good_delta,
            body.rejected_delta,
            body.reason,
            reporter,
            context,
            idempotent.key,
        ),
        to_response=ProgressResponse.of,
    )
