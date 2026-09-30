"""Request ID propagation (BR-AUD-04).

The ID comes from the ``X-Request-ID`` header when it is well formed, otherwise a new
UUID4 is generated. It is stored in ``request.state.request_id`` and in a context
variable (for log records), and echoed on every response.
"""

import re
import uuid
from contextvars import ContextVar, Token

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def bind_request_id(request_id: str | None) -> Token[str | None]:
    """Set the request ID for the current context; pass the token to ``reset_request_id``."""
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


def resolve_request_id(incoming: str | None) -> str:
    if incoming is not None and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Pure ASGI middleware, so the ID is available inside sync endpoints' threadpool."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        token = bind_request_id(request_id)
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            reset_request_id(token)
