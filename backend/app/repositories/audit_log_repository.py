from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


@dataclass(frozen=True)
class AuditFilter:
    """BR-AUD-06: by entity, actor, action and time range (``created_to`` exclusive)."""

    entity_type: str | None = None
    entity_id: int | None = None
    actor_username: str | None = None
    action: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditLogRepository:
    """Insert and read only: there is deliberately no update or delete (BR-AUD-06)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: AuditLog) -> AuditLog:
        self._session.add(entry)
        self._session.flush()
        return entry

    def list(self, filters: AuditFilter, limit: int, offset: int) -> tuple[Sequence[AuditLog], int]:
        conditions = []
        if filters.entity_type is not None:
            conditions.append(AuditLog.entity_type == filters.entity_type)
        if filters.entity_id is not None:
            conditions.append(AuditLog.entity_id == filters.entity_id)
        if filters.actor_username is not None:
            conditions.append(AuditLog.actor_username == filters.actor_username)
        if filters.action is not None:
            conditions.append(AuditLog.action == filters.action)
        if filters.created_from is not None:
            conditions.append(AuditLog.created_at >= filters.created_from)
        if filters.created_to is not None:
            conditions.append(AuditLog.created_at < filters.created_to)
        total = (
            self._session.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
        )
        rows = self._session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total
