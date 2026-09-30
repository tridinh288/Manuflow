"""Test 12 of B15, concurrent part: two real connections, same idempotency key.

Data here is really committed (a rolled-back outer transaction cannot show locking
between connections), so every row is created with a unique marker and deleted after.
The operation writes to ``warehouses`` because that table is not append-only.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.core.permissions import Role
from app.db.session import build_session_factory
from app.db.transaction import transaction
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User
from app.models.warehouse import Warehouse
from app.services.idempotency_service import (
    IdempotencyRequest,
    IdempotencyService,
    StoredResponse,
)

pytestmark = pytest.mark.concurrency

KEY = "concurrent-key-0001"
WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def marker() -> str:
    return f"CC{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def user_id(factory: sessionmaker[Session], marker: str) -> Iterator[int]:
    with factory() as session, session.begin():
        user = User(
            username=f"conc-{marker.lower()}",
            password_hash="not-used",
            full_name="Concurrency",
            role=Role.ADMIN,
            active=True,
        )
        session.add(user)
        session.flush()
        new_id = user.id
    yield new_id
    with factory() as session, session.begin():
        session.execute(delete(IdempotencyKey).where(IdempotencyKey.user_id == new_id))
        session.execute(delete(Warehouse).where(Warehouse.code.like(f"{marker}%")))
        session.execute(delete(User).where(User.id == new_id))


def call(
    factory: sessionmaker[Session],
    user_id: int,
    code: str,
    *,
    inside: threading.Event | None = None,
    release: threading.Event | None = None,
    fail: bool = False,
) -> StoredResponse:
    """One request: insert a warehouse row inside the idempotent transaction."""
    with factory() as session:
        service = IdempotencyService(session, SystemClock(), timedelta(hours=24))

        def operation() -> int:
            with transaction(session):
                warehouse = Warehouse(code=code, name="concurrency test")
                session.add(warehouse)
                session.flush()
            if inside is not None:
                inside.set()
            if release is not None:
                release.wait(WAIT_SECONDS)
            if fail:
                raise RuntimeError("business failure after the key was claimed")
            return warehouse.id

        request = IdempotencyRequest(user_id, KEY, "POST", "/concurrency", "same-request-hash")
        return service.run(request, operation, lambda wid: (201, {"warehouse_id": wid}))


def warehouse_codes(factory: sessionmaker[Session], marker: str) -> list[str]:
    with factory() as session:
        return list(
            session.scalars(select(Warehouse.code).where(Warehouse.code.like(f"{marker}%")))
        )


def key_rows(factory: sessionmaker[Session], user_id: int) -> int:
    with factory() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyKey)
                .where(IdempotencyKey.user_id == user_id)
            )
            or 0
        )


def test_d22_concurrent_duplicate_waits_and_gets_the_stored_response(
    factory: sessionmaker[Session], user_id: int, marker: str
) -> None:
    a_inside, release_a = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            call, factory, user_id, f"{marker}A", inside=a_inside, release=release_a
        )
        assert a_inside.wait(WAIT_SECONDS), "first request never reached its operation"
        # A holds the key row lock; B blocks on the unique index until A commits.
        second = pool.submit(call, factory, user_id, f"{marker}B")
        time.sleep(0.3)
        assert not second.done(), "second request must wait for the first"
        release_a.set()
        result_a, result_b = first.result(WAIT_SECONDS), second.result(WAIT_SECONDS)

    assert (result_a.replayed, result_b.replayed) == (False, True)
    assert result_b.body == result_a.body
    assert warehouse_codes(factory, marker) == [f"{marker}A"]  # effect happened once
    assert key_rows(factory, user_id) == 1


def test_c03_concurrent_duplicate_runs_when_the_first_request_fails(
    factory: sessionmaker[Session], user_id: int, marker: str
) -> None:
    a_inside, release_a = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            call, factory, user_id, f"{marker}A", inside=a_inside, release=release_a, fail=True
        )
        assert a_inside.wait(WAIT_SECONDS)
        second = pool.submit(call, factory, user_id, f"{marker}B")
        time.sleep(0.3)
        release_a.set()
        with pytest.raises(RuntimeError, match="business failure"):
            first.result(WAIT_SECONDS)
        result_b = second.result(WAIT_SECONDS)

    assert result_b.replayed is False
    assert warehouse_codes(factory, marker) == [f"{marker}B"]  # A's change rolled back
    assert key_rows(factory, user_id) == 1
