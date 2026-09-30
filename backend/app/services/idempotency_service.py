"""Idempotent mutations (D-22, B12, C-03, C-08).

``run`` executes one use case so that the key row, the business change and the stored
response share a single transaction:

1. INSERT the key row first - ahead of every other lock (C-03). A concurrent duplicate
   blocks on the unique index until the first request finishes.
2. Run the business operation; the service method joins this transaction.
3. Store the response and commit.

Any error rolls back the key together with the change, so only successful responses are
stored and a failed request can be retried with the same key. When the INSERT hits an
existing key, the stored response is returned instead (same request) or the request is
rejected (same key, different request). An expired key is deleted and the request runs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.transaction import joinable_transaction, transaction
from app.domain.errors import BusinessValidationError, ConcurrencyConflictError
from app.domain.idempotency import is_expired
from app.models.idempotency_key import IdempotencyKey
from app.repositories.idempotency_repository import IdempotencyRepository

_MYSQL_DUPLICATE_ENTRY = 1062
_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class IdempotencyRequest:
    user_id: int
    key: str
    method: str
    path: str
    request_hash: str


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: Any
    replayed: bool


class _KeyAlreadyUsedError(Exception):
    pass


def _is_duplicate_entry(exc: IntegrityError) -> bool:
    args: tuple[object, ...] = getattr(exc.orig, "args", ())
    return bool(args) and args[0] == _MYSQL_DUPLICATE_ENTRY


class IdempotencyService:
    def __init__(self, session: Session, clock: Clock, ttl: timedelta) -> None:
        self._session = session
        self._clock = clock
        self._ttl = ttl
        self._keys = IdempotencyRepository(session)

    def run[T](
        self,
        request: IdempotencyRequest,
        operation: Callable[[], T],
        serialize: Callable[[T], tuple[int, Any]],
    ) -> StoredResponse:
        for _ in range(_MAX_ATTEMPTS):
            try:
                return self._execute(request, operation, serialize)
            except _KeyAlreadyUsedError:
                stored = self._stored_response(request)
                if stored is not None:
                    return stored
                # The key vanished (first request rolled back) or had expired: retry.
        raise ConcurrencyConflictError(
            "CONCURRENCY_CONFLICT", "The request could not be completed; please retry."
        )

    def purge_expired(self) -> int:
        """Delete keys past their TTL (C-08); run from the CLI."""
        with transaction(self._session):
            return self._keys.delete_created_before(self._clock.now() - self._ttl)

    def _execute[T](
        self,
        request: IdempotencyRequest,
        operation: Callable[[], T],
        serialize: Callable[[T], tuple[int, Any]],
    ) -> StoredResponse:
        with joinable_transaction(self._session):
            try:
                row = self._keys.add(
                    IdempotencyKey(
                        user_id=request.user_id,
                        idem_key=request.key,
                        method=request.method,
                        path=request.path,
                        request_hash=request.request_hash,
                        created_at=self._clock.now(),
                    )
                )
            except IntegrityError as exc:
                if _is_duplicate_entry(exc):
                    raise _KeyAlreadyUsedError from exc
                raise
            status_code, body = serialize(operation())
            row.response_status = status_code
            row.response_body = body
            self._session.flush()
        return StoredResponse(status_code=status_code, body=body, replayed=False)

    def _stored_response(self, request: IdempotencyRequest) -> StoredResponse | None:
        with transaction(self._session):
            row = self._keys.get_for_update(request.user_id, request.key)
            if row is None:
                return None
            if self._expired(row.created_at):
                self._keys.delete(row)
                return None
            if row.request_hash != request.request_hash:
                raise BusinessValidationError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was already used for a different request.",
                )
            if row.response_status is None:  # cannot be committed so; fail closed
                raise ConcurrencyConflictError(
                    "CONCURRENCY_CONFLICT", "The request could not be completed; please retry."
                )
            return StoredResponse(
                status_code=row.response_status, body=row.response_body, replayed=True
            )

    def _expired(self, created_at: datetime) -> bool:
        return is_expired(created_at, self._clock.now(), self._ttl)
