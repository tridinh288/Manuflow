from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime

from app.api.access import require
from app.api.deps import get_inventory_service, get_request_context
from app.api.idempotency import RequiredIdempotency
from app.core.permissions import Permission
from app.domain.inventory import TransactionType
from app.repositories.inventory_repository import TransactionFilter
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.inventory import (
    AdjustmentRequest,
    BalanceResponse,
    MovementResponse,
    OrderMovementRequest,
    OrderMovementResponse,
    ReceiptRequest,
    TransactionResponse,
    to_decimal,
)
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_READ))]
Receiver = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_RECEIVE))]
Adjuster = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_ADJUST))]
Issuer = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_ISSUE))]
Returner = Annotated[AuthenticatedUser, Depends(require(Permission.INVENTORY_RETURN))]
Service = Annotated[InventoryService, Depends(get_inventory_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("")
def list_balances(
    _: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    low_stock: bool = False,
) -> Page[BalanceResponse]:
    """Balances per material; ``low_stock=true`` keeps available < minimum_stock (D-25)."""
    rows, total = service.list_balances(limit, offset, low_stock)
    return Page(items=[BalanceResponse.of(row, material) for row, material in rows], total=total)


@router.get("/transactions")
def list_transactions(
    _: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    material_id: int | None = None,
    production_order_id: int | None = None,
    type: TransactionType | None = None,
    created_from: AwareDatetime | None = None,
    created_to: AwareDatetime | None = None,
) -> Page[TransactionResponse]:
    """The ledger, newest first; date filters must carry a timezone (D-23)."""
    filters = TransactionFilter(
        material_id=material_id,
        production_order_id=production_order_id,
        type=type.value if type else None,
        created_from=created_from,
        created_to=created_to,
    )
    rows, total = service.list_transactions(filters, limit, offset)
    return Page(
        items=[TransactionResponse.of(line, material) for line, material in rows], total=total
    )


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


@router.post("/adjustments", status_code=status.HTTP_201_CREATED, response_model=MovementResponse)
def adjust_stock(
    body: AdjustmentRequest,
    user: Adjuster,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """ADJUSTMENT (B6): signed correction with a reason; never below reserved (D-20)."""
    delta = to_decimal(body.quantity_delta)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.adjust(body.material_id, delta, body.reason, user.actor, context),
        to_response=MovementResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/issues", status_code=status.HTTP_201_CREATED, response_model=OrderMovementResponse)
def issue_stock(
    body: OrderMovementRequest,
    user: Issuer,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """ISSUE (D-10): consume what is reserved for an order line; key required (D-22)."""
    quantity = to_decimal(body.quantity)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.issue(body.order_material_id, quantity, user.actor, context),
        to_response=OrderMovementResponse.of_order,
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/returns", status_code=status.HTTP_201_CREATED, response_model=OrderMovementResponse)
def return_stock(
    body: OrderMovementRequest,
    user: Returner,
    service: Service,
    context: Context,
    idempotent: RequiredIdempotency,
) -> JSONResponse:
    """RETURN (C-05): issued material back to stock after cancel or completion."""
    quantity = to_decimal(body.quantity)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.return_stock(
            body.order_material_id, quantity, user.actor, context
        ),
        to_response=OrderMovementResponse.of_order,
        status_code=status.HTTP_201_CREATED,
    )
