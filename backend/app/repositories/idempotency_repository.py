from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.idempotency_key import IdempotencyKey


class IdempotencyRepository:
    """Queries only; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, row: IdempotencyKey) -> IdempotencyKey:
        """Insert and flush at once, so a duplicate key fails here and nowhere else."""
        self._session.add(row)
        self._session.flush()
        return row

    def get_for_update(self, user_id: int, key: str) -> IdempotencyKey | None:
        return self._session.scalars(
            select(IdempotencyKey)
            .where(IdempotencyKey.user_id == user_id, IdempotencyKey.idem_key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()

    def delete(self, row: IdempotencyKey) -> None:
        self._session.delete(row)
        self._session.flush()

    def delete_created_before(self, cutoff: datetime) -> int:
        result = self._session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff)
        )
        return int(getattr(result, "rowcount", 0) or 0)
