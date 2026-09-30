"""Application factory: ``uvicorn app.main:create_app --factory``."""

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from app.core.security import PasswordHasher, TokenService
from app.db.session import build_engine, build_session_factory


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = build_engine(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Manuflow API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = build_session_factory(engine)
    app.state.clock = clock or SystemClock()
    app.state.password_hasher = PasswordHasher()
    # Domain-separated from the JWT signing key (HMAC of "idempotency-fingerprint").
    app.state.fingerprint_secret = hmac.new(
        settings.jwt_secret.get_secret_value().encode(), b"idempotency-fingerprint", "sha256"
    ).digest()
    app.state.token_service = TokenService(
        settings.jwt_secret.get_secret_value(), settings.jwt_expire_minutes
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    # Added last so it wraps everything else, including CORS responses.
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")
    return app
