"""B8 progress figures and test 18 of B15: the B9 risk rules with a fixed clock."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.operations import OperationStatus
from app.domain.order_state import OrderStatus
from app.domain.progress import (
    OperationState,
    current_operation,
    finished_progress,
    operation_progress,
    workflow_progress,
    yield_rate,
)
from app.domain.risk import (
    OrderFacts,
    RiskLevel,
    RiskReason,
    RiskThresholds,
    assess,
    message,
    time_ratio,
)

P, IP, C = OperationStatus.PENDING, OperationStatus.IN_PROGRESS, OperationStatus.COMPLETED
S = OrderStatus
THRESHOLDS = RiskThresholds()  # D-24 defaults: 0.20, 48 h, 3 days

# --- B8: progress figures --------------------------------------------------------------------

B8 = [
    OperationState(10, C, 100, 0),
    OperationState(20, C, 97, 3),
    OperationState(30, IP, 80, 0),
    OperationState(40, IP, 50, 0),
    OperationState(50, P, 0, 0),
]


def test_b8_workflow_progress_of_the_worked_example_is_66_percent() -> None:
    assert [operation_progress(op, 100) for op in B8] == [
        Decimal(1),
        Decimal(1),
        Decimal("0.8"),
        Decimal("0.5"),
        Decimal(0),
    ]
    assert workflow_progress(B8, 100) == Decimal("0.66")
    assert finished_progress(B8, 100) == 0
    assert current_operation(B8) == B8[2]  # WELDING, the smallest sequence not COMPLETED


def test_b8_completed_operation_counts_as_done_even_after_upstream_scrap() -> None:
    """Welding received 97 good units of 100 and finished them: its progress is 1, not 0.97."""
    welded = OperationState(30, C, 95, 2)
    assert welded.processed == 97
    assert operation_progress(welded, 100) == 1


def test_b8_v1_example_80_good_3_rejected() -> None:
    operation = OperationState(10, IP, 80, 3)
    assert operation.processed == 83
    assert operation_progress(operation, 100) == Decimal("0.83")
    assert round(yield_rate(operation) or 0, 3) == Decimal("0.964")


def test_b8_yield_rate_is_undefined_before_anything_is_processed() -> None:
    assert yield_rate(OperationState(10, P, 0, 0)) is None


# --- B9: risk rules (test 18) ------------------------------------------------------------------

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)


def facts(
    status: OrderStatus,
    due_in: timedelta,
    started_ago: timedelta | None = None,
    progress: str = "0",
) -> OrderFacts:
    return OrderFacts(
        status=status,
        due_date=NOW + due_in,
        started_at=NOW - started_ago if started_ago is not None else None,
        workflow_progress=Decimal(progress),
    )


def test_b9_worked_example_is_behind_schedule() -> None:
    """Started 08:00 28/9, due 08:00 2/10 (96 h); at 14:00 1/10, 78 h used = 0.8125."""
    example = OrderFacts(
        status=S.IN_PROGRESS,
        due_date=datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        started_at=datetime(2026, 9, 28, 8, 0, tzinfo=UTC),
        workflow_progress=Decimal("0.45"),
    )
    result = assess(example, NOW, THRESHOLDS)
    assert result is not None
    assert (result.risk, result.reason) == (RiskLevel.AT_RISK, RiskReason.BEHIND_SCHEDULE)
    assert result.time_ratio == Decimal("0.8125")
    assert message(result, example) == (
        "Đã dùng 81% thời gian nhưng lệnh mới đi được 45% quy trình."
    )


@pytest.mark.parametrize(
    ("order", "risk", "reason"),
    [
        # OVERDUE wins over everything, for any open status.
        (facts(S.MATERIAL_SHORTAGE, timedelta(minutes=-1)), RiskLevel.OVERDUE, RiskReason.PAST_DUE),
        (
            facts(S.IN_PROGRESS, timedelta(hours=-1), timedelta(days=2), "0.99"),
            RiskLevel.OVERDUE,
            RiskReason.PAST_DUE,
        ),
        # MATERIAL_SHORTAGE within 3 days, boundary included.
        (
            facts(S.MATERIAL_SHORTAGE, timedelta(days=3)),
            RiskLevel.AT_RISK,
            RiskReason.MATERIAL_SHORTAGE,
        ),
        (facts(S.MATERIAL_SHORTAGE, timedelta(days=3, seconds=1)), RiskLevel.ON_TRACK, None),
        # Not started within 48 hours, boundary included (C-09: shadowed for SHORTAGE).
        (facts(S.DRAFT, timedelta(hours=48)), RiskLevel.AT_RISK, RiskReason.NOT_STARTED_DUE_SOON),
        (
            facts(S.READY_TO_PRODUCE, timedelta(hours=1)),
            RiskLevel.AT_RISK,
            RiskReason.NOT_STARTED_DUE_SOON,
        ),
        (facts(S.READY_TO_PRODUCE, timedelta(hours=48, seconds=1)), RiskLevel.ON_TRACK, None),
        # IN_PROGRESS: time used minus progress strictly above 0.20.
        (
            facts(S.IN_PROGRESS, timedelta(hours=50), timedelta(hours=50), "0.30"),
            RiskLevel.ON_TRACK,
            None,
        ),  # 0.50 - 0.30 = 0.20, not above
        (
            facts(S.IN_PROGRESS, timedelta(hours=50), timedelta(hours=50), "0.29"),
            RiskLevel.AT_RISK,
            RiskReason.BEHIND_SCHEDULE,
        ),
        # A started order close to its due date but on pace is fine.
        (
            facts(S.IN_PROGRESS, timedelta(hours=1), timedelta(hours=99), "0.95"),
            RiskLevel.ON_TRACK,
            None,
        ),
    ],
    ids=[
        "overdue-shortage",
        "overdue-in-progress",
        "shortage-3-days",
        "shortage-later",
        "draft-48-hours",
        "ready-soon",
        "ready-later",
        "gap-exactly-0.20",
        "gap-0.21",
        "on-pace",
    ],
)
def test_b9_first_matching_rule_decides(
    order: OrderFacts, risk: RiskLevel, reason: RiskReason | None
) -> None:
    result = assess(order, NOW, THRESHOLDS)
    assert result is not None
    assert (result.risk, result.reason) == (risk, reason)


@pytest.mark.parametrize("status", [S.COMPLETED, S.CANCELLED])
def test_b9_terminal_orders_carry_no_risk(status: OrderStatus) -> None:
    assert assess(facts(status, timedelta(days=-10)), NOW, THRESHOLDS) is None


def test_d24_thresholds_are_configuration() -> None:
    order = facts(S.READY_TO_PRODUCE, timedelta(hours=60))
    assert assess(order, NOW, THRESHOLDS).risk is RiskLevel.ON_TRACK  # type: ignore[union-attr]
    wider = RiskThresholds(due_soon=timedelta(hours=72))
    assert assess(order, NOW, wider).risk is RiskLevel.AT_RISK  # type: ignore[union-attr]


def test_b9_time_ratio_is_clamped_to_zero_and_one() -> None:
    start, due = NOW, NOW + timedelta(hours=10)
    assert time_ratio(NOW - timedelta(hours=1), start, due) == 0
    assert time_ratio(NOW + timedelta(hours=5), start, due) == Decimal("0.5")
    assert time_ratio(NOW + timedelta(hours=20), start, due) == 1


@pytest.mark.parametrize("window", [timedelta(0), timedelta(hours=-3)])
def test_c09_non_positive_window_counts_as_all_time_used(window: timedelta) -> None:
    assert time_ratio(NOW, NOW, NOW + window) == 1
