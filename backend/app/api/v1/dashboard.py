from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.access import require
from app.api.deps import get_risk_service
from app.core.permissions import Permission
from app.schemas.common import Page
from app.schemas.dashboard import OrderRiskResponse
from app.services.auth_service import AuthenticatedUser
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
