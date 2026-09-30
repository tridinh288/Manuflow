"""User account rules (D-18, B16): pure validation, no I/O."""

import re

from app.core.permissions import Role
from app.domain.errors import BusinessValidationError

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
