"""User account rules (D-18, B16): pure validation, no I/O."""

import re
from collections.abc import Collection, Mapping
from typing import Any

from app.core.permissions import Role
from app.domain.errors import BusinessValidationError, ConflictError

MIN_PASSWORD_LENGTH = 10  # B16
MAX_PASSWORD_LENGTH = 128
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


def validate_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise BusinessValidationError(
            "INVALID_PASSWORD",
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters long.",
        )


def validate_username(username: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise BusinessValidationError(
            "INVALID_USERNAME",
            "Username must be 3-64 characters: letters, digits, '.', '_' or '-'.",
        )


def validate_work_center_assignment(role: Role, work_center_id: int | None) -> None:
    """D-18: a WORKER belongs to exactly one work center; other roles to none."""
    if role is Role.WORKER and work_center_id is None:
        raise BusinessValidationError(
            "WORK_CENTER_REQUIRED", "A WORKER must be assigned to a work center."
        )
    if role is not Role.WORKER and work_center_id is not None:
        raise BusinessValidationError(
            "WORK_CENTER_NOT_ALLOWED", "Only a WORKER can be assigned to a work center."
        )


def _is_active_admin(state: Mapping[str, Any]) -> bool:
    return state["role"] is Role.ADMIN and bool(state["active"])


def ensure_admin_remains(
    user_id: int,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    active_admin_ids: Collection[int],
) -> None:
    """C-12: the last active ADMIN cannot be deactivated or moved to another role.

    ``before``/``after`` hold the target's ``role`` and ``active``; ``active_admin_ids``
    are the active ADMINs read under lock, the target included.
    """
    if not (_is_active_admin(before) and not _is_active_admin(after)):
        return
    others = [admin_id for admin_id in active_admin_ids if admin_id != user_id]
    if not others:
        raise ConflictError(
            "LAST_ADMIN", "The last active ADMIN cannot be deactivated or change role."
        )
