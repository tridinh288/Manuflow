"""Order risk for the dashboard (B9, D-24): every open order assessed at one ``now``."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain import progress
from app.domain.operations import OperationStatus
from app.domain.order_state import OPEN_STATUSES, OrderStatus
from app.domain.risk import Assessment, OrderFacts, RiskLevel, RiskThresholds, assess, message
from app.models.master_data import Product
from app.models.production import ProductionOrder
from app.models.work_center import WorkCenter

_SEVERITY = {RiskLevel.OVERDUE: 0, RiskLevel.AT_RISK: 1, RiskLevel.ON_TRACK: 2}


@dataclass(frozen=True)
class CurrentOperation:
    sequence: int
    operation_type: str
    work_center_code: str
    progress: Decimal


@dataclass(frozen=True)
class OrderRisk:
    order: ProductionOrder
    product_code: str
    assessment: Assessment
    workflow_progress: Decimal
    finished_progress: Decimal
    current_operation: CurrentOperation | None
    message: str


def operation_states(order: ProductionOrder) -> list[progress.OperationState]:
    return [
        progress.OperationState(
            op.sequence, OperationStatus(op.status), op.good_quantity, op.rejected_quantity
        )
        for op in sorted(order.operations, key=lambda op: op.sequence)
    ]


class RiskService:
    def __init__(self, session: Session, clock: Clock, thresholds: RiskThresholds) -> None:
        self._session = session
        self._clock = clock
        self._thresholds = thresholds

    def order_risks(self, include_on_track: bool = False) -> list[OrderRisk]:
        """Open orders, most severe first, then by due date."""
        now = self._clock.now()
        with transaction(self._session):
            rows = self._session.execute(
                select(ProductionOrder, Product.product_code)
                .join(Product, Product.id == ProductionOrder.product_id)
                .where(ProductionOrder.status.in_([s.value for s in OPEN_STATUSES]))
                .order_by(ProductionOrder.due_date, ProductionOrder.id)
            ).all()
            codes: dict[int, str] = {
                center_id: code
                for center_id, code in self._session.execute(select(WorkCenter.id, WorkCenter.code))
            }
            risks = [self._assess(order, code, codes, now) for order, code in rows]
        risks = [
            r for r in risks if include_on_track or r.assessment.risk is not RiskLevel.ON_TRACK
        ]
        return sorted(risks, key=lambda r: _SEVERITY[r.assessment.risk])  # stable: keeps due order

    def _assess(
        self, order: ProductionOrder, product_code: str, codes: dict[int, str], now: datetime
    ) -> OrderRisk:
        states = operation_states(order)
        workflow = progress.workflow_progress(states, order.planned_quantity)
        facts = OrderFacts(OrderStatus(order.status), order.due_date, order.started_at, workflow)
        assessment = assess(facts, now, self._thresholds)
        if assessment is None:  # only open orders are queried
            raise RuntimeError(f"order {order.id} is not open")
        current = progress.current_operation(states)
        current_view = None
        if current is not None and order.status == OrderStatus.IN_PROGRESS.value:
            row = next(op for op in order.operations if op.sequence == current.sequence)
            current_view = CurrentOperation(
                current.sequence,
                row.operation_type,
                codes[row.work_center_id],
                progress.operation_progress(current, order.planned_quantity),
            )
        return OrderRisk(
            order=order,
            product_code=product_code,
            assessment=assessment,
            workflow_progress=workflow,
            finished_progress=progress.finished_progress(states, order.planned_quantity),
            current_operation=current_view,
            message=message(assessment, facts),
        )
