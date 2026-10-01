from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.access import require
from app.api.deps import get_inventory_service
from app.core.permissions import Permission
from app.schemas.inventory import ReconciliationResponse
from app.services.auth_service import AuthenticatedUser
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/admin", tags=["admin"])

Auditor = Annotated[AuthenticatedUser, Depends(require(Permission.AUDIT_READ))]


@router.get("/inventory-reconciliation")
def inventory_reconciliation(
    _: Auditor, service: Annotated[InventoryService, Depends(get_inventory_service)]
) -> ReconciliationResponse:
    """BR-INV-04: every balance equals the sum of its ledger deltas."""
    return ReconciliationResponse.of(service.reconcile())
