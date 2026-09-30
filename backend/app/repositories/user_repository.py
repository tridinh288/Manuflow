from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Queries only; never commits (B12)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> User | None:
        # populate_existing: always the current row, never a stale identity-map copy.
        return self._session.get(User, user_id, populate_existing=True)

    def get_for_update(self, user_id: int) -> User | None:
        return self._session.get(User, user_id, with_for_update=True, populate_existing=True)

    def get_by_username_for_update(self, username: str) -> User | None:
        # Row lock so concurrent failed logins cannot lose a failure count.
        return self._session.scalars(
            select(User)
            .where(User.username == username)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()

    def username_exists(self, username: str) -> bool:
        # Compared with the column collation (case-insensitive), like the unique index.
        count = self._session.scalar(select(func.count()).where(User.username == username))
        return (count or 0) > 0

    def list_page(self, limit: int, offset: int) -> tuple[Sequence[User], int]:
        total = self._session.scalar(select(func.count()).select_from(User)) or 0
        users = self._session.scalars(
            select(User).order_by(User.id).limit(limit).offset(offset)
        ).all()
        return users, total

    def add(self, user: User) -> User:
        self._session.add(user)
        self._session.flush()
        return user
