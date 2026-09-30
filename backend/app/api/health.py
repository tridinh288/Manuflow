"""Liveness/readiness probe. Public by design: it exposes no data, only up/down."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.schemas.health import ComponentStatus, HealthResponse
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", responses={503: {"model": HealthResponse}})
def health(session: Annotated[Session, Depends(get_session)], response: Response) -> HealthResponse:
    database_ok = HealthService(session).database_is_available()
    status: ComponentStatus = "ok" if database_ok else "unavailable"
    response.status_code = 200 if database_ok else 503
    return HealthResponse(status=status, database=status)
