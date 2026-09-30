from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Queries only; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> User | None:
        # populate_existing: always the current row, never a stale identity-map copy.
        return self._session.get(User, user_id, populate_existing=True)

    def get_by_username_for_update(self, username: str) -> User | None:
        # Row lock so concurrent failed logins cannot lose a failure count.
        return self._session.scalars(
            select(User)
            .where(User.username == username)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
