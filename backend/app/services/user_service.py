"""User administration (users:manage) with audit (BR-AUD-01)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.db.transaction import transaction
from app.domain.audit import AuditAction, AuditEntity, changed_fields
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.users import (
    validate_password,
    validate_username,
    validate_work_center_assignment,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.work_center_repository import WorkCenterRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext

_AUDITED_FIELDS = ("username", "full_name", "role", "work_center_id", "active")


@dataclass(frozen=True)
class NewUser:
    username: str
    password: str
    full_name: str
    role: Role
    work_center_id: int | None = None


@dataclass(frozen=True)
class UserUpdate:
    """Only the fields named in ``provided`` are changed (PATCH semantics)."""

    provided: frozenset[str] = field(default_factory=frozenset)
    full_name: str | None = None
    role: Role | None = None
    work_center_id: int | None = None
    active: bool | None = None
    password: str | None = None


def _snapshot(user: User) -> dict[str, Any]:
    return {name: getattr(user, name) for name in _AUDITED_FIELDS}


class UserService:
    def __init__(self, session: Session, passwords: PasswordHasher) -> None:
        self._session = session
        self._passwords = passwords
        self._users = UserRepository(session)
        self._work_centers = WorkCenterRepository(session)
        self._audit = AuditService(session)

    def list_users(self, limit: int, offset: int) -> tuple[Sequence[User], int]:
        with transaction(self._session):
            return self._users.list_page(limit, offset)

    def create_user(self, data: NewUser, actor: Actor, context: RequestContext) -> User:
        validate_username(data.username)
        validate_password(data.password)
        validate_work_center_assignment(data.role, data.work_center_id)
        password_hash = self._passwords.hash(data.password)  # slow: outside the transaction

        try:
            with transaction(self._session):
                self._ensure_assignable_work_center(data.work_center_id)
                if self._users.username_exists(data.username):
                    raise _username_taken()
                user = self._users.add(
                    User(
                        username=data.username,
                        password_hash=password_hash,
                        full_name=data.full_name,
                        role=data.role,
                        work_center_id=data.work_center_id,
                        active=True,
                    )
                )
                self._audit.record(
                    action=AuditAction.USER_CREATED,
                    entity_type=AuditEntity.USER,
                    entity_id=user.id,
                    actor=actor,
                    context=context,
                    new_value=_snapshot(user),
                )
        except IntegrityError as exc:
            # A concurrent request created the same username after our check.
            raise _username_taken() from exc
        return user

    def update_user(
        self, user_id: int, update: UserUpdate, actor: Actor, context: RequestContext
    ) -> User:
        if "password" in update.provided and update.password is not None:
            validate_password(update.password)
            password_hash: str | None = self._passwords.hash(update.password)
        else:
            password_hash = None

        with transaction(self._session):
            user = self._users.get_for_update(user_id)
            if user is None:
                raise NotFoundError("USER_NOT_FOUND", "User not found.")
            before = _snapshot(user)

            role = update.role if "role" in update.provided else user.role
            if role is None:
                raise BusinessValidationError("INVALID_ROLE", "Role cannot be empty.")
            work_center_id = (
                update.work_center_id
                if "work_center_id" in update.provided
                else user.work_center_id
            )
            validate_work_center_assignment(role, work_center_id)
            if work_center_id != user.work_center_id:
                self._ensure_assignable_work_center(work_center_id)

            user.role = role
            user.work_center_id = work_center_id
            if "full_name" in update.provided and update.full_name is not None:
                user.full_name = update.full_name
            if "active" in update.provided and update.active is not None:
                user.active = update.active
            if password_hash is not None:
                user.password_hash = password_hash
            self._session.flush()

            old_value, new_value = changed_fields(before, _snapshot(user))
            if password_hash is not None:
                new_value["credentials_reset"] = True  # never the password or its hash
            if new_value:
                self._audit.record(
                    action=_update_action(old_value, new_value),
                    entity_type=AuditEntity.USER,
                    entity_id=user.id,
                    actor=actor,
                    context=context,
                    old_value=old_value,
                    new_value=new_value,
                )
        return user

    def _ensure_assignable_work_center(self, work_center_id: int | None) -> None:
        if work_center_id is None:
            return
        work_center = self._work_centers.get(work_center_id)
        if work_center is None:
            raise BusinessValidationError("WORK_CENTER_NOT_FOUND", "Work center does not exist.")
        if not work_center.active:
            raise ConflictError("WORK_CENTER_INACTIVE", "Work center is inactive.")


def _username_taken() -> ConflictError:
    return ConflictError("USERNAME_TAKEN", "Username is already in use.")


def _update_action(old_value: dict[str, Any], new_value: dict[str, Any]) -> AuditAction:
    """One row per update; the most significant change names it, all changes are stored."""
    if new_value.get("active") is False:
        return AuditAction.USER_DEACTIVATED
    if "role" in new_value:
        return AuditAction.USER_ROLE_CHANGED
    if new_value.get("active") is True and old_value.get("active") is False:
        return AuditAction.USER_REACTIVATED
    return AuditAction.USER_UPDATED
