"""B12: an idempotent request that hits a deadlock is re-run as a whole transaction."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.domain.errors import ConcurrencyConflictError
from app.models.idempotency_key import IdempotencyKey
from app.services.idempotency_service import IdempotencyRequest, IdempotencyService


def deadlock() -> OperationalError:
    return OperationalError("UPDATE inventory ...", {}, Exception(1213, "Deadlock found"))


def run(session: Session, clock: FixedClock, user_id: int, failures: int) -> tuple[int, object]:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= failures:
            raise deadlock()
        return "done"

    service = IdempotencyService(session, clock, timedelta(hours=24))
    request = IdempotencyRequest(user_id, "retry-key-0001", "POST", "/x", "hash")
    stored = service.run(request, operation, lambda result: (201, {"result": result}))
    return attempts, stored.body


def test_b12_deadlocked_request_is_retried_and_stored_once(
    db_session: Session, clock: FixedClock, user_factory
) -> None:
    user = user_factory()
    attempts, body = run(db_session, clock, user.id, failures=2)
    assert (attempts, body) == (3, {"result": "done"})
    keys = db_session.scalar(select(func.count()).select_from(IdempotencyKey))
    assert keys == 1  # the rolled-back attempts left nothing behind


def test_b12_persistent_deadlock_is_503_and_leaves_no_key(
    db_session: Session, clock: FixedClock, user_factory
) -> None:
    user = user_factory()
    with pytest.raises(ConcurrencyConflictError):
        run(db_session, clock, user.id, failures=3)
    assert db_session.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
