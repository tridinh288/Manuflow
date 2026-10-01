"""Test 13 of B15 (unit part): the state machine of B7, every pair (BR-PO-01, BR-PO-05)."""

import itertools

import pytest

from app.core.permissions import Role, permissions_for
from app.domain.errors import ConflictError
from app.domain.order_state import (
    TRANSITIONS,
    OrderAction,
    OrderStatus,
    allowed_actions,
    ensure_allowed,
    transition,
)

S, A = OrderStatus, OrderAction

# B7 transcribed: (from, action) -> possible targets.
SPEC_TABLE = {
    (S.DRAFT, A.UPDATE): {S.DRAFT},
    (S.DRAFT, A.PLAN): {S.READY_TO_PRODUCE, S.MATERIAL_SHORTAGE},
    (S.MATERIAL_SHORTAGE, A.CHECK_MATERIALS): {S.READY_TO_PRODUCE, S.MATERIAL_SHORTAGE},
    (S.READY_TO_PRODUCE, A.START): {S.IN_PROGRESS},
    (S.IN_PROGRESS, A.COMPLETE): {S.COMPLETED},
    (S.DRAFT, A.CANCEL): {S.CANCELLED},
    (S.MATERIAL_SHORTAGE, A.CANCEL): {S.CANCELLED},
    (S.READY_TO_PRODUCE, A.CANCEL): {S.CANCELLED},
}


def test_br_po_02_code_table_equals_the_spec_table() -> None:
    assert {key: set(targets) for key, targets in TRANSITIONS.items()} == SPEC_TABLE


@pytest.mark.parametrize(("status", "action"), sorted(SPEC_TABLE))
def test_br_po_01_every_listed_transition_is_allowed(status: S, action: A) -> None:
    for target in SPEC_TABLE[(status, action)]:
        assert transition(status, action, target) is target


UNLISTED = sorted(set(itertools.product(S, A)) - set(SPEC_TABLE))


@pytest.mark.parametrize(("status", "action"), UNLISTED)
def test_br_po_01_every_other_pair_is_refused(status: S, action: A) -> None:
    with pytest.raises(ConflictError) as exc_info:
        ensure_allowed(status, action)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    [detail] = exc_info.value.details
    assert detail["current_status"] == status.value
    assert detail["action"] == action.value


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (S.CANCELLED, A.START),
        (S.COMPLETED, A.START),
        (S.IN_PROGRESS, A.CANCEL),
        (S.READY_TO_PRODUCE, A.PLAN),
    ],
)
def test_br_po_01_examples_required_by_the_spec_are_refused(status: S, action: A) -> None:
    with pytest.raises(ConflictError):
        ensure_allowed(status, action)


def test_br_po_01_refusal_lists_the_allowed_actions() -> None:
    with pytest.raises(ConflictError) as exc_info:
        ensure_allowed(S.READY_TO_PRODUCE, A.PLAN)
    assert exc_info.value.details[0]["allowed_actions"] == ["start", "cancel"]


def test_d07_d13_terminal_statuses_allow_nothing() -> None:
    for status in (S.COMPLETED, S.CANCELLED):
        assert [a for a in A if (status, a) in TRANSITIONS] == []


def test_transition_rejects_a_target_outside_the_table() -> None:
    with pytest.raises(ValueError, match="cannot lead"):
        transition(S.DRAFT, A.PLAN, S.IN_PROGRESS)


@pytest.mark.parametrize(
    ("role", "status", "expected"),
    [
        (Role.PRODUCTION_MANAGER, S.DRAFT, ["update", "plan", "cancel"]),
        (Role.PRODUCTION_MANAGER, S.MATERIAL_SHORTAGE, ["check-materials", "cancel"]),
        (Role.PRODUCTION_MANAGER, S.READY_TO_PRODUCE, ["start", "cancel"]),
        (Role.PRODUCTION_MANAGER, S.IN_PROGRESS, []),  # completion is the system's
        (Role.WAREHOUSE, S.MATERIAL_SHORTAGE, ["check-materials"]),
        (Role.WAREHOUSE, S.DRAFT, []),
        (Role.ADMIN, S.DRAFT, []),
        (Role.WORKER, S.READY_TO_PRODUCE, []),
        (Role.PRODUCTION_MANAGER, S.COMPLETED, []),
    ],
)
def test_br_po_05_allowed_actions_depend_on_status_and_the_user(
    role: Role, status: S, expected: list[str]
) -> None:
    assert allowed_actions(status, permissions_for(role)) == expected
