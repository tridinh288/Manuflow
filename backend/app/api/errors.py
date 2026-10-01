"""The single mapping from exceptions to the error body of B13.

``{"error": {"code", "message", "details", "request_id"}}``; stack traces, SQL and
rejected input values never reach the client.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import (
    REQUEST_ID_HEADER,
    bind_request_id,
    get_request_id,
    reset_request_id,
)
from app.domain.errors import DomainError, ErrorCategory

logger = logging.getLogger(__name__)

STATUS_BY_CATEGORY: dict[ErrorCategory, int] = {
    ErrorCategory.UNAUTHENTICATED: 401,
    ErrorCategory.FORBIDDEN: 403,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.CONCURRENCY: 503,
    ErrorCategory.UNAVAILABLE: 503,
}

_CODE_BY_HTTP_STATUS: dict[int, str] = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or get_request_id()


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Sequence[Mapping[str, Any]] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    if request_id is not None:
        response_headers[REQUEST_ID_HEADER] = request_id
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": [dict(detail) for detail in details],
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=response_headers)


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):
        raise exc
    headers = (
        {"WWW-Authenticate": "Bearer"} if exc.category is ErrorCategory.UNAUTHENTICATED else None
    )
    return error_response(
        request,
        STATUS_BY_CATEGORY[exc.category],
        exc.code,
        exc.message,
        exc.details,
        headers=headers,
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Deliberately drop pydantic's "input"/"ctx": they may echo passwords or tokens.
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed.", details)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _CODE_BY_HTTP_STATUS.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else code
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Runs outside RequestIdMiddleware (Starlette's ServerErrorMiddleware is outermost),
    # so re-bind the ID for the log line.
    token = bind_request_id(_request_id(request))
    try:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    finally:
        reset_request_id(token)
    return error_response(request, 500, "INTERNAL_ERROR", "Internal server error.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
