from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.domain.bottleneck import WorkCenterLoad
from app.schemas.inventory import BalanceResponse
from app.services.dashboard_service import MaterialAlerts, ProductionOverview
from app.services.risk_service import OrderRisk


def ratio(value: Decimal) -> float:
    """Ratios (not quantities) as numbers rounded to 2 places, as in the B9 example."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class CurrentOperationResponse(BaseModel):
    sequence: int
    type: str
    work_center: str
    progress: float


class OrderRiskResponse(BaseModel):
    order_id: int
    production_order: str
    product_code: str
    status: str
    due_date: datetime
    risk: str
    reason_code: str | None
    time_ratio: float | None
    workflow_progress: float
    finished_progress: float
    current_operation: CurrentOperationResponse | None
    message: str

    @classmethod
    def of(cls, item: OrderRisk) -> "OrderRiskResponse":
        assessment, current = item.assessment, item.current_operation
        return cls(
            order_id=item.order.id,
            production_order=item.order.order_number,
            product_code=item.product_code,
            status=item.order.status,
            due_date=item.order.due_date,
            risk=assessment.risk.value,
            reason_code=assessment.reason.value if assessment.reason else None,
            time_ratio=ratio(assessment.time_ratio) if assessment.time_ratio is not None else None,
            workflow_progress=ratio(item.workflow_progress),
            finished_progress=ratio(item.finished_progress),
            current_operation=CurrentOperationResponse(
                sequence=current.sequence,
                type=current.operation_type,
                work_center=current.work_center_code,
                progress=ratio(current.progress),
            )
            if current
            else None,
            message=item.message,
        )


class BottleneckResponse(BaseModel):
    work_center_id: int
    work_center: str
    queue_units: int
    at_risk_orders: int
    bottleneck: bool

    @classmethod
    def of(cls, load: WorkCenterLoad) -> "BottleneckResponse":
        return cls(
            work_center_id=load.work_center_id,
            work_center=load.code,
            queue_units=load.queue_units,
            at_risk_orders=load.at_risk_orders,
            bottleneck=load.bottleneck,
        )


class OrderSummary(BaseModel):
    order_id: int
    production_order: str
    product_code: str
    status: str
    due_date: datetime


class MaterialAlertsResponse(BaseModel):
    low_stock: list[BalanceResponse]
    recheck_candidates: list[OrderSummary]

    @classmethod
    def of(cls, alerts: MaterialAlerts) -> "MaterialAlertsResponse":
        return cls(
            low_stock=[BalanceResponse.of(row, material) for row, material in alerts.low_stock],
            recheck_candidates=[
                OrderSummary(
                    order_id=order.id,
                    production_order=order.order_number,
                    product_code=product.product_code,
                    status=order.status,
                    due_date=order.due_date,
                )
                for order, product in alerts.recheck
            ],
        )


class ProductionOverviewResponse(BaseModel):
    orders_by_status: dict[str, int]
    due_within_7_days: list[OrderSummary]

    @classmethod
    def of(cls, overview: ProductionOverview) -> "ProductionOverviewResponse":
        return cls(
            orders_by_status={status.value: n for status, n in overview.by_status.items()},
            due_within_7_days=[
                OrderSummary(
                    order_id=order.id,
                    production_order=order.order_number,
                    product_code=product.product_code,
                    status=order.status,
                    due_date=order.due_date,
                )
                for order, product in overview.due_soon
            ],
        )
