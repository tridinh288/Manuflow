"""``Idempotency-Key`` handling for mutating routes (D-22).

A route takes ``OptionalIdempotency`` or ``RequiredIdempotency`` and returns
``idempotent.respond(...)``. Without a key the operation simply runs; with a key it runs
through ``IdempotencyService`` and a retry gets the stored response back, marked with
``Idempotent-Replayed: true``.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_session
from app.core.clock import Clock
from app.core.config import Settings
from app.domain.errors import BusinessValidationError
from app.domain.idempotency import request_fingerprint, validate_idempotency_key
from app.services.auth_service import AuthenticatedUser
from app.services.idempotency_service import IdempotencyRequest, IdempotencyService

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"


class Idempotent:
    def __init__(
        self, request: Request, service: IdempotencyService, key: str | None, secret: bytes
    ) -> None:
        self._request = request
        self._service = service
        self._secret = secret
        self.key = key

    def respond[T](
        self,
        *,
        user: AuthenticatedUser,
        payload: BaseModel | None,
        operation: Callable[[], T],
        to_response: Callable[[T], BaseModel],
        status_code: int = 200,
    ) -> JSONResponse:
        def serialize(result: T) -> tuple[int, Any]:
            return status_code, to_response(result).model_dump(mode="json")

        if self.key is None:
            status, body = serialize(operation())
            return JSONResponse(status_code=status, content=body)

        body_payload = payload.model_dump(mode="json", exclude_unset=True) if payload else None
        stored = self._service.run(
            IdempotencyRequest(
                user_id=user.id,
                key=self.key,
                method=self._request.method,
                path=self._request.url.path,
                request_hash=request_fingerprint(
                    self._request.method, self._request.url.path, body_payload, self._secret
                ),
            ),
            operation,
            serialize,
        )
        headers = {REPLAYED_HEADER: "true"} if stored.replayed else None
        return JSONResponse(status_code=stored.status_code, content=stored.body, headers=headers)


def _idempotency_service(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> IdempotencyService:
    settings: Settings = request.app.state.settings
    return IdempotencyService(session, clock, timedelta(hours=settings.idempotency_ttl_hours))


def _optional(
    request: Request,
    service: Annotated[IdempotencyService, Depends(_idempotency_service)],
    key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> Idempotent:
    if key is not None:
        validate_idempotency_key(key)
    secret: bytes = request.app.state.fingerprint_secret
    return Idempotent(request, service, key, secret)


def _required(idempotent: Annotated[Idempotent, Depends(_optional)]) -> Idempotent:
    if idempotent.key is None:
        raise BusinessValidationError(
            "IDEMPOTENCY_KEY_REQUIRED", f"The {IDEMPOTENCY_HEADER} header is required."
        )
    return idempotent


OptionalIdempotency = Annotated[Idempotent, Depends(_optional)]
RequiredIdempotency = Annotated[Idempotent, Depends(_required)]
