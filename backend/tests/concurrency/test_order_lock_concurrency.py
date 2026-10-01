"""BR-PO-03: every action locks the order row first, so concurrent actions on one order
run one after the other and the later one sees the new status.

Another transaction has moved the order to READY_TO_PRODUCE and not committed. plan must
wait for the order row, then see READY and be refused. Reading the order without the
lock would see DRAFT, plan it a second time and overwrite the other action's status.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Product
from app.models.production import ProductionOrder
from app.services.context import Actor, RequestContext
from app.services.production_service import ProductionOrderService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 15


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def order_id(factory: sessionmaker[Session]) -> int:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-L{marker}", name="Frame", unit="pcs")
        session.add(product)
        session.flush()
        order = ProductionOrder(
            order_number=f"PO-L{marker}",
            product_id=product.id,
            planned_quantity=10,
            due_date=datetime.now(UTC) + timedelta(days=7),
            status="DRAFT",
        )
        session.add(order)
        session.flush()
        return order.id


def plan(factory: sessionmaker[Session], order_id: int) -> str:
    with factory() as session:
        try:
            ProductionOrderService(session, SystemClock()).plan(
                order_id, Actor(None, "conc"), RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_br_po_03_second_action_waits_for_the_order_lock_and_sees_the_new_status(
    factory: sessionmaker[Session], order_id: int
) -> None:
    with factory() as holder, holder.begin():
        holder.execute(
            text("UPDATE production_orders SET status = 'READY_TO_PRODUCE' WHERE id = :id"),
            {"id": order_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(plan, factory, order_id)
            time.sleep(0.5)
            assert not pending.done(), "plan must wait for the order row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "INVALID_STATE_TRANSITION"
