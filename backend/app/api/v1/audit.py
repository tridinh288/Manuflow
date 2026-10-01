from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.api.access import require
from app.api.deps import get_audit_service
from app.core.permissions import Permission
from app.domain.audit import AuditAction, AuditEntity
from app.repositories.audit_log_repository import AuditFilter
from app.schemas.audit import AuditLogResponse
from app.schemas.common import DEFAULT_LIMIT, MAX_ID, Limit, Offset, Page
from app.services.audit_service import AuditService
from app.services.auth_service import AuthenticatedUser

router = APIRouter(prefix="/audit-logs", tags=["audit"])

Auditor = Annotated[AuthenticatedUser, Depends(require(Permission.AUDIT_READ))]


@router.get("")
def list_audit_logs(
    _: Auditor,
    service: Annotated[AuditService, Depends(get_audit_service)],
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    entity_type: AuditEntity | None = None,
    entity_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    actor_username: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    action: AuditAction | None = None,
    created_from: AwareDatetime | None = None,
    created_to: AwareDatetime | None = None,
) -> Page[AuditLogResponse]:
    """BR-AUD-06 (ADMIN): who did what and when, newest first; dates need a timezone."""
    filters = AuditFilter(
        entity_type=entity_type.value if entity_type else None,
        entity_id=entity_id,
        actor_username=actor_username,
        action=action.value if action else None,
        created_from=created_from,
        created_to=created_to,
    )
    rows, total = service.list_logs(filters, limit, offset)
    return Page(items=[AuditLogResponse.of(row) for row in rows], total=total)
