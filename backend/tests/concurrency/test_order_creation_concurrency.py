"""D-21 and C-13 under concurrency.

Orders use a fixed clock in 2099 so their counter row never meets the API tests' rows.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import FixedClock
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Product
from app.models.production import DocumentSequence, ProductionOrder
from app.services.context import Actor, RequestContext
from app.services.production_service import NewOrder, ProductionOrderService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10
NOW = datetime(2099, 3, 1, 8, 0, tzinfo=UTC)


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def product_id(factory: sessionmaker[Session]) -> Iterator[int]:
    with factory() as session, session.begin():
        product = Product(
            product_code=f"CONC-O{uuid.uuid4().hex[:6].upper()}", name="Conc", unit="pcs"
        )
        session.add(product)
        session.flush()
        new_id = product.id
    yield new_id
    with factory() as session, session.begin():
        session.execute(delete(ProductionOrder).where(ProductionOrder.product_id == new_id))
        session.execute(delete(DocumentSequence).where(DocumentSequence.year == NOW.year))
        session.execute(delete(Product).where(Product.id == new_id))


def create_order(factory: sessionmaker[Session], product_id: int) -> str:
    with factory() as session:
        try:
            view = ProductionOrderService(session, FixedClock(NOW)).create(
                NewOrder(product_id, 10, NOW + timedelta(days=7)),
                Actor(None, "conc"),
                RequestContext(),
            )
        except DomainError as exc:
            return exc.code
    return view.order.order_number


def test_d21_concurrent_orders_get_consecutive_unique_numbers(
    factory: sessionmaker[Session], product_id: int
) -> None:
    start = threading.Barrier(5)

    def race() -> str:
        start.wait(WAIT_SECONDS)
        return create_order(factory, product_id)

    with ThreadPoolExecutor(max_workers=5) as pool:
        numbers = sorted(f.result(WAIT_SECONDS) for f in [pool.submit(race) for _ in range(5)])
    assert numbers == [f"PO-2099-{n:05d}" for n in range(1, 6)]
    with factory() as session:
        counter = session.scalars(
            select(DocumentSequence.next_value).where(DocumentSequence.year == NOW.year)
        ).one()
    assert counter == 6


def test_c13_order_creation_sees_a_concurrent_product_deactivation(
    factory: sessionmaker[Session], product_id: int
) -> None:
    """With a plain read the creation would see the committed snapshot (product active),
    and its INSERT would only wait on the FK check, then succeed: an open order for a
    product that has just been deactivated."""
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM products WHERE id = :id FOR UPDATE"), {"id": product_id}
        )
        holder.execute(text("UPDATE products SET active = 0 WHERE id = :id"), {"id": product_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(create_order, factory, product_id)
            time.sleep(0.5)
            assert not pending.done(), "creation must wait for the product row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "PRODUCT_INACTIVE"
