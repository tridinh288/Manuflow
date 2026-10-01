"""Dashboard figures (B9): bottlenecks, material alerts and the production overview.

Risk comes from RiskService only, so the dashboard and /dashboard/risks always agree.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import transaction
from app.domain import progress
from app.domain.bottleneck import WorkCenterLoad, flag_bottlenecks
from app.domain.operations import OperationStatus
from app.domain.order_state import OPEN_STATUSES, OrderStatus
from app.domain.risk import RiskLevel
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOrder
from app.models.work_center import WorkCenter
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.production_repository import ProductionOrderRepository
from app.services.risk_service import RiskService, operation_states

DUE_SOON_WINDOW = timedelta(days=7)
ALL_BALANCES = 10_000


@dataclass(frozen=True)
class MaterialAlerts:
    low_stock: list[tuple[Inventory, Material]]
    # D-09: MATERIAL_SHORTAGE orders whose every line could now be reserved. A suggestion
    # to run check-materials; nothing changes status by itself.
    recheck: list[tuple[ProductionOrder, Product]]


@dataclass(frozen=True)
class ProductionOverview:
    by_status: dict[OrderStatus, int]
    due_soon: list[tuple[ProductionOrder, Product]]


class DashboardService:
    def __init__(self, session: Session, clock: Clock, risks: RiskService) -> None:
        self._session = session
        self._clock = clock
        self._risks = risks

    def bottlenecks(self) -> list[WorkCenterLoad]:
        at_risk = Counter(
            item.current_operation.work_center_code
            for item in self._risks.order_risks(include_on_track=True)
            if item.assessment.risk in (RiskLevel.AT_RISK, RiskLevel.OVERDUE)
            and item.current_operation is not None
        )
        with transaction(self._session):
            centers = self._session.scalars(
                select(WorkCenter).where(WorkCenter.active.is_(True)).order_by(WorkCenter.code)
            ).all()
            orders = self._session.scalars(
                select(ProductionOrder).where(
                    ProductionOrder.status == OrderStatus.IN_PROGRESS.value
                )
            ).all()
            queue: dict[int, int] = defaultdict(int)
            for order in orders:
                rows = sorted(order.operations, key=lambda op: op.sequence)
                states = operation_states(order)
                limits = progress.limits(order.planned_quantity, states)
                for row, state, limit in zip(rows, states, limits, strict=True):
                    if state.status is not OperationStatus.COMPLETED:
                        queue[row.work_center_id] += limit - state.processed
            loads = [
                WorkCenterLoad(center.id, center.code, queue[center.id], at_risk[center.code])
                for center in centers
            ]
        return flag_bottlenecks(loads)

    def material_alerts(self) -> MaterialAlerts:
        stock = InventoryRepository(self._session)
        orders = ProductionOrderRepository(self._session)
        with transaction(self._session):
            low, _ = stock.list_balances(ALL_BALANCES, 0, low_stock=True)  # D-25
            shortage, _ = orders.list_orders(
                ALL_BALANCES, 0, OrderStatus.MATERIAL_SHORTAGE.value, None, None
            )
            recheck = []
            for order, product in shortage:
                lines = orders.lines_for_order(order.id)
                available = {
                    material_id: row.on_hand_quantity - row.reserved_quantity
                    for material_id, row in self._balances([line.material_id for line in lines])
                }
                if lines and all(
                    available.get(line.material_id, Decimal(0)) >= line.required_quantity
                    for line in lines
                ):
                    recheck.append((order, product))
        return MaterialAlerts(low_stock=list(low), recheck=recheck)

    def production_overview(self) -> ProductionOverview:
        horizon = self._clock.now() + DUE_SOON_WINDOW
        with transaction(self._session):
            counts = Counter(
                OrderStatus(status)
                for status in self._session.scalars(select(ProductionOrder.status))
            )
            due_soon = self._session.execute(
                select(ProductionOrder, Product)
                .join(Product, Product.id == ProductionOrder.product_id)
                .where(
                    ProductionOrder.status.in_([s.value for s in OPEN_STATUSES]),
                    ProductionOrder.due_date <= horizon,
                )
                .order_by(ProductionOrder.due_date, ProductionOrder.id)
            ).all()
        return ProductionOverview(
            by_status={status: counts.get(status, 0) for status in OrderStatus},
            due_soon=[(order, product) for order, product in due_soon],
        )

    def _balances(self, material_ids: list[int]) -> list[tuple[int, Inventory]]:
        if not material_ids:
            return []
        rows = self._session.scalars(
            select(Inventory).where(Inventory.material_id.in_(material_ids))
        ).all()
        return [(row.material_id, row) for row in rows]
