from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.access import require
from app.api.deps import get_dashboard_service, get_risk_service
from app.core.permissions import Permission
from app.schemas.common import Page
from app.schemas.dashboard import (
    BottleneckResponse,
    MaterialAlertsResponse,
    OrderRiskResponse,
    ProductionOverviewResponse,
)
from app.services.auth_service import AuthenticatedUser
from app.services.dashboard_service import DashboardService
from app.services.risk_service import RiskService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Viewer = Annotated[AuthenticatedUser, Depends(require(Permission.DASHBOARD_READ))]


@router.get("/risks")
def order_risks(
    _: Viewer,
    service: Annotated[RiskService, Depends(get_risk_service)],
    include_on_track: bool = False,
) -> Page[OrderRiskResponse]:
    """B9: open orders at risk, OVERDUE first, then AT_RISK, each by due date."""
    items = [OrderRiskResponse.of(r) for r in service.order_risks(include_on_track)]
    return Page(items=items, total=len(items))


Dashboard = Annotated[DashboardService, Depends(get_dashboard_service)]


@router.get("/production")
def production_overview(_: Viewer, service: Dashboard) -> ProductionOverviewResponse:
    """Orders by status and the open orders due within 7 days (overdue included)."""
    return ProductionOverviewResponse.of(service.production_overview())


@router.get("/bottlenecks")
def bottlenecks(_: Viewer, service: Dashboard) -> Page[BottleneckResponse]:
    """B9: where work piles up; flagged when 2+ at-risk orders are there, or it has the
    largest queue and at least one at-risk order."""
    items = [BottleneckResponse.of(load) for load in service.bottlenecks()]
    return Page(items=items, total=len(items))


@router.get("/material-alerts")
def material_alerts(_: Viewer, service: Dashboard) -> MaterialAlertsResponse:
    """B9: low stock (available below minimum, D-25) and shortage orders worth a
    check-materials now (D-09: a suggestion; nothing changes by itself)."""
    return MaterialAlertsResponse.of(service.material_alerts())
