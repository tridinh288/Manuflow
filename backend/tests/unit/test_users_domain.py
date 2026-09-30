"""D-18, B16 and BR-AUTH-03 rules as pure functions."""

import pytest

from app.core.permissions import Role
from app.domain.errors import BusinessValidationError, ConflictError, NotFoundError
from app.domain.scope import ensure_in_scope, work_center_scope
from app.domain.users import (
    ensure_admin_remains,
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


# --- C-12: the last active ADMIN is protected ------------------------------------------

ADMIN_ACTIVE = {"role": Role.ADMIN, "active": True}


@pytest.mark.parametrize(
    "after",
    [{"role": Role.ADMIN, "active": False}, {"role": Role.WAREHOUSE, "active": True}],
    ids=["deactivated", "demoted"],
)
def test_c12_last_active_admin_cannot_be_deactivated_or_demoted(after: dict[str, object]) -> None:
    with pytest.raises(ConflictError) as exc_info:
        ensure_admin_remains(1, ADMIN_ACTIVE, after, active_admin_ids=[1])
    assert exc_info.value.code == "LAST_ADMIN"


def test_c12_admin_can_be_demoted_while_another_admin_remains() -> None:
    ensure_admin_remains(1, ADMIN_ACTIVE, {"role": Role.ADMIN, "active": False}, [1, 2])


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (ADMIN_ACTIVE, ADMIN_ACTIVE),  # untouched admin
        ({"role": Role.WAREHOUSE, "active": True}, {"role": Role.WAREHOUSE, "active": False}),
        ({"role": Role.ADMIN, "active": False}, {"role": Role.WAREHOUSE, "active": False}),
    ],
    ids=["no-change", "non-admin", "already-inactive-admin"],
)
def test_c12_changes_that_do_not_remove_an_active_admin_are_allowed(
    before: dict[str, object], after: dict[str, object]
) -> None:
    ensure_admin_remains(1, before, after, active_admin_ids=[])
