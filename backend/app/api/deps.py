"""Shared FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock
from app.domain.errors import AuthenticationError
from app.services.auth_service import AuthenticatedUser, AuthService
from app.services.bom_service import BomService
from app.services.context import RequestContext
from app.services.inventory_service import InventoryService
from app.services.master_data_service import MaterialService, ProductService, WorkCenterService
from app.services.production_service import ProductionOrderService
from app.services.progress_service import ProgressService
from app.services.routing_service import RoutingService
from app.services.user_service import UserService

_MAX_IP_LENGTH = 45

bearer_scheme = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; the service method called by the route owns the transaction."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_request_context(request: Request) -> RequestContext:
    # The direct peer address; X-Forwarded-For is not trusted without a known proxy.
    ip_address = request.client.host[:_MAX_IP_LENGTH] if request.client else None
    return RequestContext(
        request_id=getattr(request.state, "request_id", None), ip_address=ip_address
    )


def get_auth_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AuthService:
    return AuthService(
        session, clock, request.app.state.token_service, request.app.state.password_hasher
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    """BR-AUTH-01/04: identity from a verified token, user reloaded on every request."""
    if credentials is None:
        raise AuthenticationError("NOT_AUTHENTICATED", "Authentication required.")
    return auth_service.authenticate(credentials.credentials)


def get_user_service(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> UserService:
    return UserService(session, request.app.state.password_hasher)


def get_product_service(session: Annotated[Session, Depends(get_session)]) -> ProductService:
    return ProductService(session)


def get_material_service(session: Annotated[Session, Depends(get_session)]) -> MaterialService:
    return MaterialService(session)


def get_work_center_service(
    session: Annotated[Session, Depends(get_session)],
) -> WorkCenterService:
    return WorkCenterService(session)


def get_bom_service(
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> BomService:
    return BomService(session, clock)


def get_routing_service(
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RoutingService:
    return RoutingService(session, clock)


def get_inventory_service(session: Annotated[Session, Depends(get_session)]) -> InventoryService:
    return InventoryService(session)


def get_production_order_service(
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ProductionOrderService:
    return ProductionOrderService(session, clock)


def get_progress_service(
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ProgressService:
    return ProgressService(session, clock)
