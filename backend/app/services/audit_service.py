"""Audit rows are written inside the caller's business transaction (BR-AUD-02)."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity, to_audit_payload
from app.domain.errors import BusinessValidationError
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditFilter, AuditLogRepository
from app.services.context import Actor, RequestContext

_MAX_USERNAME = 64
_MAX_REASON = 500


class AuditOutsideTransactionError(RuntimeError):
    """``record`` was called without an open transaction: the row could outlive a rollback."""


class AuditService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = AuditLogRepository(session)

    def record(
        self,
        *,
        action: AuditAction,
        entity_type: AuditEntity,
        entity_id: int | None,
        actor: Actor | None,
        context: RequestContext,
        old_value: Mapping[str, Any] | None = None,
        new_value: Mapping[str, Any] | None = None,
        reason: str | None = None,
    ) -> AuditLog:
        if not self._session.in_transaction():
            raise AuditOutsideTransactionError(
                "AuditService.record must run inside the business transaction"
            )
        entry = AuditLog(
            actor_user_id=actor.user_id if actor else None,
            actor_username=actor.username[:_MAX_USERNAME] if actor and actor.username else None,
            action=action.value,
            entity_type=entity_type.value,
            entity_id=entity_id,
            old_value=to_audit_payload(old_value) if old_value is not None else None,
            new_value=to_audit_payload(new_value) if new_value is not None else None,
            reason=reason[:_MAX_REASON] if reason else None,
            request_id=context.request_id,
            ip_address=context.ip_address,
        )
        return self._repository.add(entry)

    def list_logs(
        self, filters: AuditFilter, limit: int, offset: int
    ) -> tuple[Sequence[AuditLog], int]:
        """BR-AUD-06: newest first, filtered by entity, actor, action and time range."""
        if (
            filters.created_from is not None
            and filters.created_to is not None
            and filters.created_from >= filters.created_to
        ):
            raise BusinessValidationError(
                "INVALID_DATE_RANGE", "created_from must be earlier than created_to."
            )
        with transaction(self._session):
            return self._repository.list(filters, limit, offset)
