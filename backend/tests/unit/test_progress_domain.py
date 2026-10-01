"""B8 quantity rules as pure functions: test 16 (limits) and 17 (cascade) of B15."""

import pytest

from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.operations import OperationStatus
from app.domain.progress import (
    OperationState,
    apply_report,
    cascade_completions,
    limits,
    validate_report,
)

P, IP, C = OperationStatus.PENDING, OperationStatus.IN_PROGRESS, OperationStatus.COMPLETED


def op(sequence: int, status: OperationStatus, good: int = 0, rejected: int = 0) -> OperationState:
    return OperationState(sequence, status, good, rejected)


# The B8 example: planned 100, FRAME-A routing.
B8 = [
    op(10, C, 100, 0),
    op(20, C, 97, 3),
    op(30, IP, 80, 0),
    op(40, IP, 50, 0),
    op(50, P, 0, 0),
]


def test_d14_limits_of_the_b8_example() -> None:
    assert limits(100, B8) == [100, 100, 97, 80, 50]


def test_d14_an_order_without_operations_has_no_limits() -> None:
    # A DRAFT order has no operations yet; GET .../operations must still answer.
    assert limits(100, []) == []


def test_br_op_02_report_within_the_limit_is_applied() -> None:
    after = apply_report(100, B8, 3, 20, 0)  # PAINTING 50 -> 70 of 80
    assert (after[3].good, after[3].status) == (70, IP)


def test_br_op_02_report_beyond_the_limit_is_refused_with_the_limit() -> None:
    with pytest.raises(ConflictError) as exc_info:
        apply_report(100, B8, 3, 25, 6)  # 50 + 31 > 80
    assert exc_info.value.code == "EXCEEDS_AVAILABLE_INPUT"
    assert exc_info.value.details == [
        {"sequence": 40, "limit": 80, "processed": 50, "requested": 81}
    ]


def test_d14_operations_overlap_but_never_outrun_their_input() -> None:
    start = [op(10, IP, 50, 0), op(20, P)]
    assert apply_report(100, start, 1, 30, 0)[1].good == 30  # 30 of the 50 good so far
    with pytest.raises(ConflictError):
        apply_report(100, start, 1, 51, 0)


def test_br_op_04_first_report_starts_the_operation() -> None:
    after = apply_report(100, [op(10, P), op(20, P)], 0, 1, 0)
    assert after[0].status is IP


def test_br_op_04_completion_needs_the_whole_limit_and_a_completed_predecessor() -> None:
    # Operation 20 processed everything operation 10 delivered so far, but 10 is not done.
    states = [op(10, IP, 60, 0), op(20, IP, 60, 0)]
    assert [s.status for s in cascade_completions(100, states)] == [IP, IP]
    after = apply_report(100, states, 0, 40, 0)  # 10 finishes at 100
    assert [s.status for s in after] == [C, IP]  # 20 still has 40 to process


def test_br_op_04_completion_cascades_down_the_routing() -> None:
    states = [op(10, IP, 90, 0), op(20, IP, 95, 0), op(30, IP, 95, 0)]
    after = apply_report(100, states, 0, 5, 5)  # 10 completes with 95 good
    assert [s.status for s in after] == [C, C, C]


def test_br_op_04_everything_rejected_upstream_completes_the_rest_with_zero() -> None:
    after = apply_report(10, [op(10, P), op(20, P), op(30, P)], 0, 0, 10)
    assert [(s.status, s.good, s.rejected) for s in after] == [
        (C, 0, 10),
        (C, 0, 0),
        (C, 0, 0),
    ]


def test_br_op_01_completed_operation_cannot_be_reported() -> None:
    with pytest.raises(ConflictError) as exc_info:
        apply_report(100, B8, 0, 0, 1)
    assert exc_info.value.code == "OPERATION_COMPLETED"


def test_br_op_03_correction_cannot_go_below_what_the_next_operation_used() -> None:
    with pytest.raises(ConflictError) as exc_info:
        apply_report(100, B8, 2, -31, 0)  # WELDING 80 -> 49 but PAINTING processed 50
    assert exc_info.value.code == "CORRECTION_BELOW_DOWNSTREAM"
    assert apply_report(100, B8, 2, -30, 0)[2].good == 50  # down to exactly 50 is fine


def test_br_op_03_correction_never_makes_a_total_negative() -> None:
    with pytest.raises(ConflictError) as exc_info:
        apply_report(100, [op(10, IP, 5, 1)], 0, 0, -2)
    assert exc_info.value.code == "NEGATIVE_TOTAL"


@pytest.mark.parametrize(
    ("good", "rejected", "reason", "code"),
    [
        (0, 0, None, "EMPTY_REPORT"),
        (-1, 0, None, "REASON_REQUIRED"),
        (0, -1, "  ", "REASON_REQUIRED"),
    ],
)
def test_br_op_02_report_shape(good: int, rejected: int, reason: str | None, code: str) -> None:
    with pytest.raises(BusinessValidationError) as exc_info:
        validate_report(good, rejected, reason)
    assert exc_info.value.code == code


def test_d15_correction_with_a_reason_is_valid() -> None:
    validate_report(-2, 2, "Miscounted: 2 were scrap")
