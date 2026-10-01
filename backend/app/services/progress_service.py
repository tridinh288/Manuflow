"""Operation progress reports and corrections (B8, BR-OP-01..07, D-12, D-14..D-16, D-18).

Lock order (BR-OP-07, B12): order row -> every operation of the order by sequence. All
reports of one order are serialized; contention is negligible at workshop scale.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.permissions import Permission, Role
from app.db.transaction import transaction
from app.domain import progress
from app.domain.audit import AuditAction, AuditEntity
from app.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.domain.operations import OperationStatus
from app.domain.order_state import OrderStatus
from app.domain.scope import work_center_scope
from app.models.production import OperationProgressLog, ProductionOperation, ProductionOrder
from app.repositories.production_repository import ProductionOrderRepository
from app.services.audit_service import AuditService
from app.services.context import Actor, RequestContext
from app.services.production_service import ProductionOrderService


@dataclass(frozen=True)
class Reporter:
    """Who reports: the scope and correction right come from the server (BR-AUTH-01)."""

    actor: Actor
    role: Role
    work_center_id: int | None
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class ProgressResult:
    order: ProductionOrder
    operation: ProductionOperation
    limit: int


def _not_found() -> NotFoundError:
    return NotFoundError("OPERATION_NOT_FOUND", "Production operation not found.")


class ProgressService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._orders = ProductionOrderRepository(session)
        self._audit = AuditService(session)

    def report(
        self,
        operation_id: int,
        good_delta: int,
        rejected_delta: int,
        reason: str | None,
        reporter: Reporter,
        context: RequestContext,
        idempotency_key: str | None = None,
    ) -> ProgressResult:
        progress.validate_report(good_delta, rejected_delta, reason)
        correction = progress.is_correction(good_delta, rejected_delta)
        # C-02: the route requires operation:report; taking units back also needs
        # operation:correct (PRODUCTION_MANAGER only, D-15).
        if correction and Permission.OPERATION_CORRECT not in reporter.permissions:
            raise PermissionDeniedError(
                "FORBIDDEN", "Only a production manager can correct reported progress."
            )
        scope = work_center_scope(reporter.role, reporter.work_center_id)
        with transaction(self._session):
            peek = self._orders.get_operation(operation_id)
            if peek is None or (scope is not None and peek.work_center_id != scope):
                raise _not_found()  # BR-AUTH-03: 404, never 403, outside the scope
            order = self._orders.get_for_update(peek.production_order_id)
            if order is None:  # operations always belong to an order (FK)
                raise _not_found()
            if order.status != OrderStatus.IN_PROGRESS.value:  # BR-OP-01
                raise ConflictError(
                    "ORDER_NOT_IN_PROGRESS",
                    "Progress can only be reported while the order is IN_PROGRESS.",
                    [{"current_status": order.status}],
                )
            operations = self._orders.lock_operations(order.id)
            index = next(i for i, op in enumerate(operations) if op.id == operation_id)
            states = [
                progress.OperationState(
                    op.sequence, OperationStatus(op.status), op.good_quantity, op.rejected_quantity
                )
                for op in operations
            ]
            limit = progress.limits(order.planned_quantity, states)[index]
            updated = progress.apply_report(
                order.planned_quantity, states, index, good_delta, rejected_delta
            )
            self._apply(operations, updated, index)
            self._orders.add_progress_log(
                OperationProgressLog(
                    operation_id=operation_id,
                    good_delta=good_delta,
                    rejected_delta=rejected_delta,
                    reason=reason,
                    reported_by=reporter.actor.user_id,
                    idem_key=idempotency_key,
                    request_id=context.request_id,
                )
            )
            target = operations[index]
            self._audit.record(
                action=AuditAction.OPERATION_PROGRESS_CORRECTED
                if correction
                else AuditAction.OPERATION_PROGRESS_REPORTED,
                entity_type=AuditEntity.PRODUCTION_OPERATION,
                entity_id=target.id,
                actor=reporter.actor,
                context=context,
                old_value={
                    "good": states[index].good,
                    "rejected": states[index].rejected,
                    "status": states[index].status.value,
                },
                new_value={
                    "order_number": order.order_number,
                    "sequence": target.sequence,
                    "good_delta": good_delta,
                    "rejected_delta": rejected_delta,
                    "good": target.good_quantity,
                    "rejected": target.rejected_quantity,
                    "status": target.status,
                },
                reason=reason,
            )
            last = operations[-1]
            if last.status == OperationStatus.COMPLETED.value:  # D-12, BR-OP-05
                ProductionOrderService(self._session, self._clock).complete_from_operations(
                    order, last.good_quantity, reporter.actor, context
                )
        return ProgressResult(order=order, operation=target, limit=limit)

    def _apply(
        self,
        operations: list[ProductionOperation],
        updated: list[progress.OperationState],
        reported_index: int,
    ) -> None:
        now = self._clock.now()
        for index, (row, state) in enumerate(zip(operations, updated, strict=True)):
            if index == reported_index and row.started_at is None:
                row.started_at = now  # BR-OP-04: the first report starts the operation
            if state.status is OperationStatus.COMPLETED and row.status != state.status.value:
                row.completed_at = now
            row.good_quantity, row.rejected_quantity = state.good, state.rejected
            row.status = state.status.value
        self._session.flush()
