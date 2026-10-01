from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.audit_log import AuditLog


class AuditLogResponse(BaseModel):
    """BR-AUD-03 fields; payloads were masked before storage (BR-AUD-05)."""

    id: int
    actor_user_id: int | None
    actor_username: str | None
    action: str
    entity_type: str
    entity_id: int | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    reason: str | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime

    @classmethod
    def of(cls, row: AuditLog) -> "AuditLogResponse":
        return cls.model_validate(row, from_attributes=True)
