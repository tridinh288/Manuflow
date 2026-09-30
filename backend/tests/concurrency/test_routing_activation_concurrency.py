"""C-07 under concurrency: routing activation locks its work centers (id ascending).

An uncommitted work center deactivation must make a concurrent activation of a routing
that uses it fail with WORK_CENTER_INACTIVE; a plain read would see the committed
snapshot (still active) and activate the routing on a closing work center.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Product
from app.models.routing import Routing, RoutingStep
from app.models.work_center import WorkCenter
from app.services.context import Actor, RequestContext
from app.services.routing_service import RoutingService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def draft(factory: sessionmaker[Session]) -> Iterator[tuple[int, int]]:
    """(routing_id, work_center_id) of a committed DRAFT routing with one QC step."""
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-R{marker}", name="Concurrency", unit="pcs")
        station = WorkCenter(code=f"WC-R{marker}", name="Concurrency", active=True)
        session.add_all([product, station])
        session.flush()
        routing = Routing(
            product_id=product.id,
            version=1,
            status="DRAFT",
            steps=[RoutingStep(sequence=10, operation_type="QC", work_center_id=station.id)],
        )
        session.add(routing)
        session.flush()
        ids = (routing.id, station.id, product.id)
    yield ids[0], ids[1]
    routing_id, station_id, product_id = ids
    with factory() as session, session.begin():
        session.execute(delete(RoutingStep).where(RoutingStep.routing_id == routing_id))
        session.execute(delete(Routing).where(Routing.id == routing_id))
        session.execute(delete(WorkCenter).where(WorkCenter.id == station_id))
        session.execute(delete(Product).where(Product.id == product_id))


def activate(factory: sessionmaker[Session], routing_id: int) -> str:
    with factory() as session:
        try:
            RoutingService(session, SystemClock()).activate(
                routing_id, Actor(user_id=None, username="conc"), RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_c07_activation_sees_a_concurrent_work_center_deactivation(
    factory: sessionmaker[Session], draft: tuple[int, int]
) -> None:
    routing_id, station_id = draft
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM work_centers WHERE id = :id FOR UPDATE"), {"id": station_id}
        )
        holder.execute(
            text("UPDATE work_centers SET active = 0 WHERE id = :id"), {"id": station_id}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(activate, factory, routing_id)
            time.sleep(0.5)
            assert not pending.done(), "activation must wait for the work center row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "WORK_CENTER_INACTIVE"
