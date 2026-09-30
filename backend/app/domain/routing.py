"""Routing version rules (BR-RT-01..03): pure validation, no I/O."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import BusinessValidationError, ConflictError


class OperationType(StrEnum):
    CUTTING = "CUTTING"
    CNC = "CNC"
    WELDING = "WELDING"
    PAINTING = "PAINTING"
    ASSEMBLY = "ASSEMBLY"
    QC = "QC"


@dataclass(frozen=True)
class RoutingStepSpec:
    sequence: int
    operation_type: OperationType
    work_center_id: int


def validate_steps(steps: list[RoutingStepSpec]) -> None:
    """BR-RT-01: each sequence value at most once within a version."""
    duplicates = sorted(seq for seq, n in Counter(s.sequence for s in steps).items() if n > 1)
    if duplicates:
        raise BusinessValidationError(
            "DUPLICATE_SEQUENCE",
            "Each sequence value may appear only once in a routing version.",
            [{"sequence": sequence} for sequence in duplicates],
        )


def ensure_activatable(steps: list[RoutingStepSpec]) -> None:
    """BR-RT-01: at least one step. BR-RT-03: the last step (highest sequence) is QC."""
    if not steps:
        raise ConflictError("ROUTING_EMPTY", "A routing version needs at least one step.")
    last = max(steps, key=lambda step: step.sequence)
    if last.operation_type is not OperationType.QC:
        raise ConflictError(
            "ROUTING_MUST_END_WITH_QC",
            "The last step of a routing must be QC.",
            [{"sequence": last.sequence, "operation_type": last.operation_type.value}],
        )
