"""Operation progress (B8, BR-OP-01..05, D-14..D-16): pure rules, no I/O.

For operation n: ``processed(n) = good(n) + rejected(n)`` and ``limit(n)``, the most it may
process: the planned quantity for the first operation, ``good(n-1)`` for the others.
Rejected units are scrapped (D-16); there is no rework.
"""

from dataclasses import dataclass, replace

from app.domain.errors import BusinessValidationError, ConflictError
from app.domain.operations import OperationStatus


@dataclass(frozen=True)
class OperationState:
    sequence: int
    status: OperationStatus
    good: int
    rejected: int

    @property
    def processed(self) -> int:
        return self.good + self.rejected


def limits(planned: int, operations: list[OperationState]) -> list[int]:
    """D-14: limit(1) = planned, limit(n) = good(n-1). Operations sorted by sequence."""
    return [planned] + [operation.good for operation in operations[:-1]]


def is_correction(good_delta: int, rejected_delta: int) -> bool:
    return good_delta < 0 or rejected_delta < 0


def validate_report(good_delta: int, rejected_delta: int, reason: str | None) -> None:
    """BR-OP-02 / BR-OP-03 shape: whole numbers, something to report, a reason when
    anything is taken back."""
    if good_delta == 0 and rejected_delta == 0:
        raise BusinessValidationError(
            "EMPTY_REPORT", "At least one of good_delta and rejected_delta must be non-zero."
        )
    if is_correction(good_delta, rejected_delta) and not (reason and reason.strip()):
        raise BusinessValidationError(
            "REASON_REQUIRED", "A correction with a negative delta needs a reason (D-15)."
        )


def apply_report(
    planned: int,
    operations: list[OperationState],
    index: int,
    good_delta: int,
    rejected_delta: int,
) -> list[OperationState]:
    """Apply one report to operation ``index`` and return every operation's new state,
    including the cascade of completions (BR-OP-02..05). Raises on any rule violation."""
    current = operations[index]
    if current.status is OperationStatus.COMPLETED:  # BR-OP-01, C-10
        raise ConflictError(
            "OPERATION_COMPLETED",
            "A completed operation can no longer be reported or corrected.",
            [{"sequence": current.sequence}],
        )
    good, rejected = current.good + good_delta, current.rejected + rejected_delta
    if good < 0 or rejected < 0:  # BR-OP-03: totals never go negative
        raise ConflictError(
            "NEGATIVE_TOTAL",
            "The correction would make a total negative.",
            [{"sequence": current.sequence, "good": good, "rejected": rejected}],
        )
    limit = limits(planned, operations)[index]
    if good + rejected > limit:  # BR-OP-02, D-14
        raise ConflictError(
            "EXCEEDS_AVAILABLE_INPUT",
            "The operation cannot process more units than it has received.",
            [
                {
                    "sequence": current.sequence,
                    "limit": limit,
                    "processed": current.processed,
                    "requested": good + rejected,
                }
            ],
        )
    if index + 1 < len(operations) and good < operations[index + 1].processed:
        # BR-OP-03: the next operation already consumed these good units.
        raise ConflictError(
            "CORRECTION_BELOW_DOWNSTREAM",
            "Good units already processed by the next operation cannot be taken back.",
            [
                {
                    "sequence": current.sequence,
                    "good": good,
                    "next_processed": operations[index + 1].processed,
                }
            ],
        )
    status = current.status
    if status is OperationStatus.PENDING:  # BR-OP-04: the first report starts it
        status = OperationStatus.IN_PROGRESS
    updated = list(operations)
    updated[index] = replace(current, good=good, rejected=rejected, status=status)
    return cascade_completions(planned, updated)


def cascade_completions(planned: int, operations: list[OperationState]) -> list[OperationState]:
    """BR-OP-04: an operation completes once its predecessor has (or it is the first) and
    it processed its whole limit. Completing one re-evaluates the next, so a chain can
    complete at once, e.g. with 0 units when everything upstream was rejected."""
    result = list(operations)
    for index, operation in enumerate(result):
        if operation.status is OperationStatus.COMPLETED:
            continue
        # Reaching here means every earlier operation is COMPLETED: the loop stops at the
        # first one that is not, so nothing after an unfinished operation can complete.
        limit = planned if index == 0 else result[index - 1].good
        if operation.processed != limit:
            break
        result[index] = replace(operation, status=OperationStatus.COMPLETED)
    return result
