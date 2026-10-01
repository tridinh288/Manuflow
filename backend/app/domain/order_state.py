"""The production order state machine (B7, D-07, D-12, D-13).

This table is the single place that decides which action is valid in which status
(BR-PO-02). Services ask it before every change; nothing else writes ``status``.
"""

from collections.abc import Iterable
from enum import StrEnum

from app.core.permissions import Permission
from app.domain.errors import ConflictError


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    MATERIAL_SHORTAGE = "MATERIAL_SHORTAGE"
    READY_TO_PRODUCE = "READY_TO_PRODUCE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderAction(StrEnum):
    UPDATE = "update"
    PLAN = "plan"
    CHECK_MATERIALS = "check-materials"
    START = "start"
    CANCEL = "cancel"
    COMPLETE = "complete"  # system action: the last operation completed (D-12)


S, A = OrderStatus, OrderAction

TERMINAL_STATUSES = frozenset({S.COMPLETED, S.CANCELLED})
OPEN_STATUSES = frozenset(set(S) - TERMINAL_STATUSES)

# (from status, action) -> statuses the action may end in. Anything absent is refused.
TRANSITIONS: dict[tuple[OrderStatus, OrderAction], frozenset[OrderStatus]] = {
    (S.DRAFT, A.UPDATE): frozenset({S.DRAFT}),
    # D-07: plan is atomic and never rests in an intermediate PLANNED status.
    (S.DRAFT, A.PLAN): frozenset({S.READY_TO_PRODUCE, S.MATERIAL_SHORTAGE}),
    # D-09: leaving MATERIAL_SHORTAGE always takes an explicit check-materials.
    (S.MATERIAL_SHORTAGE, A.CHECK_MATERIALS): frozenset({S.READY_TO_PRODUCE, S.MATERIAL_SHORTAGE}),
    (S.READY_TO_PRODUCE, A.START): frozenset({S.IN_PROGRESS}),
    (S.IN_PROGRESS, A.COMPLETE): frozenset({S.COMPLETED}),
    # D-13: cancellable until production starts; IN_PROGRESS cannot be cancelled.
    (S.DRAFT, A.CANCEL): frozenset({S.CANCELLED}),
    (S.MATERIAL_SHORTAGE, A.CANCEL): frozenset({S.CANCELLED}),
    (S.READY_TO_PRODUCE, A.CANCEL): frozenset({S.CANCELLED}),
}

# The permission a user needs to trigger each user-facing action (B4).
ACTION_PERMISSIONS: dict[OrderAction, Permission] = {
    A.UPDATE: Permission.ORDER_CREATE,
    A.PLAN: Permission.ORDER_PLAN,
    A.CHECK_MATERIALS: Permission.ORDER_CHECK_MATERIALS,
    A.START: Permission.ORDER_START,
    A.CANCEL: Permission.ORDER_CANCEL,
}


def valid_actions(status: OrderStatus) -> list[OrderAction]:
    """Every action, user or system, that the table allows from ``status``."""
    return [action for action in A if (status, action) in TRANSITIONS]


def allowed_actions(status: OrderStatus, permissions: Iterable[Permission]) -> list[str]:
    """BR-PO-05: the user-facing actions this user may perform now, computed server-side."""
    held = set(permissions)
    return [
        action.value
        for action in valid_actions(status)
        if action in ACTION_PERMISSIONS and ACTION_PERMISSIONS[action] in held
    ]


def ensure_allowed(status: OrderStatus, action: OrderAction) -> None:
    """BR-PO-01: refuse any action the table does not list, naming what is allowed."""
    if (status, action) not in TRANSITIONS:
        raise ConflictError(
            "INVALID_STATE_TRANSITION",
            f"Action '{action.value}' is not allowed while the order is {status.value}.",
            [
                {
                    "current_status": status.value,
                    "action": action.value,
                    "allowed_actions": [
                        a.value for a in valid_actions(status) if a is not A.COMPLETE
                    ],
                }
            ],
        )


def transition(status: OrderStatus, action: OrderAction, target: OrderStatus) -> OrderStatus:
    """Validate ``action`` from ``status`` landing in ``target``; return ``target``."""
    ensure_allowed(status, action)
    if target not in TRANSITIONS[(status, action)]:
        raise ValueError(f"{action.value} cannot lead from {status.value} to {target.value}")
    return target
