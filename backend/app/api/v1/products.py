from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.access import require
from app.api.deps import get_product_service, get_request_context
from app.api.idempotency import OptionalIdempotency
from app.core.permissions import Permission
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.master_data import ProductCreateRequest, ProductResponse, ProductUpdateRequest
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.master_data_service import NewProduct, ProductChanges, ProductService

router = APIRouter(prefix="/products", tags=["products"])

Reader = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_READ))]
Writer = Annotated[AuthenticatedUser, Depends(require(Permission.MASTER_WRITE))]
Service = Annotated[ProductService, Depends(get_product_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("")
def list_products(
    _: Reader,
    service: Service,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
    active: bool | None = None,
) -> Page[ProductResponse]:
    products, total = service.list(limit, offset, active)
    return Page(items=[ProductResponse.of(p) for p in products], total=total)


@router.get("/{product_id}")
def get_product(product_id: int, _: Reader, service: Service) -> ProductResponse:
    return ProductResponse.of(service.get(product_id))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProductResponse)
def create_product(
    body: ProductCreateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    data = NewProduct(body.product_code, body.name, body.description)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.create(data, user.actor, context),
        to_response=ProductResponse.of,
        status_code=status.HTTP_201_CREATED,
    )


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    body: ProductUpdateRequest,
    user: Writer,
    service: Service,
    context: Context,
    idempotent: OptionalIdempotency,
) -> JSONResponse:
    changes = ProductChanges(body.name, body.description)
    return idempotent.respond(
        user=user,
        payload=body,
        operation=lambda: service.update(product_id, changes, user.actor, context),
        to_response=ProductResponse.of,
    )


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_product(
    product_id: int, user: Writer, service: Service, context: Context
) -> Response:
    """D-19: deactivates; never deletes. Repeating it is a no-op."""
    service.deactivate(product_id, user.actor, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
