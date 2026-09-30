from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_inventory_service, get_request_context
from app.api.idempotency import RequiredIdempotency
from app.core.permissions import Permission
from app.schemas.inventory import MovementResponse, ReceiptRequest, to_decimal
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])

Receiver = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_RECEIVE))]
Service = Annotated[InventoryService, Depends(get_inventory_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.post("/receipts", status_code=status.HTTP_201_CREATED, response_model=MovementResponse)
def receive_stock(
    body: ReceiptRequest,
    user: Receiver,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """RECEIVE (B6). Idempotency-Key is mandatory (D-22): a retry never adds stock twice."""
    quantity = to_decimal(body.quantity)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.receive(
            body.material_id, quantity, body.reference, user.actor, context
        ),
        to_response=MovementResponse.of,
        status_code=status.HTTP_201_CREATED,
    )
