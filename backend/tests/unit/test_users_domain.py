"""D-18, B16 and BR-AUTH-03 rules as pure functions."""

import pytest

from app.core.permissions import Role
from app.domain.errors import BusinessValidationError, NotFoundError
from app.domain.scope import ensure_in_scope, work_center_scope
from app.domain.users import (
    validate_password,
    validate_username,
    validate_work_center_assignment,
)


def test_d18_worker_requires_a_work_center() -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_work_center_assignment(Role.WORKER, None)
    assert exc_info.value.code == "WORK_CENTER_REQUIRED"


@pytest.mark.parametrize("role", [Role.ADMIN, Role.PRODUCTION_MANAGER, Role.WAREHOUSE])
def test_d18_only_workers_have_a_work_center(role: Role) -> None:
    validate_work_center_assignment(role, None)
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_work_center_assignment(role, 3)
    assert exc_info.value.code == "WORK_CENTER_NOT_ALLOWED"


@pytest.mark.parametrize("password", ["a" * 9, "a" * 129])
def test_b16_password_length_enforced(password: str) -> None:
    with pytest.raises(BusinessValidationError):
        validate_password(password)


def test_b16_ten_character_password_accepted() -> None:
    validate_password("a" * 10)


@pytest.mark.parametrize("username", ["ab", "has space", "é-user", "a" * 65])
def test_username_format_rejected(username: str) -> None:
    with pytest.raises(BusinessValidationError):
        validate_username(username)


# --- BR-AUTH-03: WORKER data scope -----------------------------------------------------


@pytest.mark.parametrize("role", [Role.ADMIN, Role.PRODUCTION_MANAGER, Role.WAREHOUSE])
def test_br_auth_03_non_workers_are_not_scoped(role: Role) -> None:
    assert work_center_scope(role, None) is None
    ensure_in_scope(role, None, 99, code="OPERATION_NOT_FOUND", message="x")


def test_br_auth_03_worker_is_scoped_to_own_work_center() -> None:
    assert work_center_scope(Role.WORKER, 7) == 7
    ensure_in_scope(Role.WORKER, 7, 7, code="OPERATION_NOT_FOUND", message="x")


def test_br_auth_03_other_work_center_is_reported_as_not_found() -> None:
    with pytest.raises(NotFoundError) as exc_info:
        ensure_in_scope(
            Role.WORKER, 7, 8, code="OPERATION_NOT_FOUND", message="Operation not found."
        )
    assert exc_info.value.code == "OPERATION_NOT_FOUND"


def test_br_auth_03_worker_without_work_center_fails_closed() -> None:
    with pytest.raises(NotFoundError):
        work_center_scope(Role.WORKER, None)
