"""Receipts under concurrency: no lost update (B12) and test 12 of B15 (same key).

Ledger lines are append-only, so the committed rows these tests create stay; every row
uses a unique material and concurrency tests run last.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.core.permissions import Role
from app.db.session import build_session_factory
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material
from app.models.user import User
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.services.context import Actor, RequestContext
from app.services.idempotency_service import (
    IdempotencyRequest,
    IdempotencyService,
    StoredResponse,
)
from app.services.inventory_service import InventoryService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def material_id(factory: sessionmaker[Session]) -> int:
    marker = uuid.uuid4().hex[:8].upper()
    with factory() as session, session.begin():
        material = Material(
            material_code=f"CONC-{marker}", name="Conc", unit="kg", decimal_places=3
        )
        session.add(material)
        session.flush()
        warehouse_id = session.scalars(
            select(Warehouse.id).where(Warehouse.code == DEFAULT_WAREHOUSE_CODE)
        ).one()
        session.add(Inventory(warehouse_id=warehouse_id, material_id=material.id))
        return material.id


@pytest.fixture
def user_id(factory: sessionmaker[Session]) -> int:
    with factory() as session, session.begin():
        user = User(
            username=f"conc-wh-{uuid.uuid4().hex[:8]}",
            password_hash="not-used",
            full_name="Concurrency",
            role=Role.WAREHOUSE,
            active=True,
        )
        session.add(user)
        session.flush()
        return user.id


def on_hand(factory: sessionmaker[Session], material_id: int) -> Decimal:
    with factory() as session:
        value: Decimal = session.scalars(
            select(Inventory.on_hand_quantity).where(Inventory.material_id == material_id)
        ).one()
        return value


def ledger_lines(factory: sessionmaker[Session], material_id: int) -> list[InventoryTransaction]:
    with factory() as session:
        return list(
            session.scalars(
                select(InventoryTransaction)
                .where(InventoryTransaction.material_id == material_id)
                .order_by(InventoryTransaction.id)
            )
        )


def test_b12_concurrent_receipt_waits_and_never_loses_an_update(
    factory: sessionmaker[Session], material_id: int
) -> None:
    """Another transaction has added 10 but not committed; our receipt of 5 must end at
    15. Reading the balance without the row lock would compute 0 + 5 and overwrite."""

    def receive_five() -> None:
        with factory() as session:
            InventoryService(session).receive(
                material_id, Decimal(5), None, Actor(None, "conc"), RequestContext()
            )

    with factory() as holder, holder.begin():
        holder.execute(
            text(
                "UPDATE inventory SET on_hand_quantity = on_hand_quantity + 10 "
                "WHERE material_id = :id"
            ),
            {"id": material_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(receive_five)
            time.sleep(0.5)
            assert not pending.done(), "the receipt must wait for the balance row lock"
            holder.commit()
            pending.result(WAIT_SECONDS)

    assert on_hand(factory, material_id) == Decimal(15)
    [line] = ledger_lines(factory, material_id)
    assert (line.on_hand_delta, line.on_hand_after) == (Decimal(5), Decimal(15))


def test_d22_concurrent_duplicate_receipt_moves_stock_once(
    factory: sessionmaker[Session], material_id: int, user_id: int
) -> None:
    key = f"conc-receipt-{uuid.uuid4().hex[:8]}"
    start = threading.Barrier(2)

    def submit() -> StoredResponse:
        start.wait(WAIT_SECONDS)
        with factory() as session:
            service = IdempotencyService(session, SystemClock(), timedelta(hours=24))
            inventory = InventoryService(session)
            return service.run(
                IdempotencyRequest(user_id, key, "POST", "/api/v1/inventory/receipts", "same"),
                lambda: inventory.receive(
                    material_id, Decimal(40), None, Actor(user_id, "conc"), RequestContext()
                ),
                lambda result: (201, {"transaction_id": result.line.id}),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit), pool.submit(submit)]
        results = [future.result(WAIT_SECONDS) for future in futures]

    assert sorted(r.replayed for r in results) == [False, True]
    assert results[0].body == results[1].body
    assert on_hand(factory, material_id) == Decimal(40)
    assert len(ledger_lines(factory, material_id)) == 1
    with factory() as session:
        keys = session.scalar(
            text("SELECT COUNT(*) FROM idempotency_keys WHERE idem_key = :k"), {"k": key}
        )
    assert keys == 1
