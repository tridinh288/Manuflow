"""BR-OP-07 under concurrency: reports of one order are serialized by the order lock.

Another report has added 8 good units to CUTTING (limit 10) and not committed. Our report
of 5 must wait, then see 8 and be refused: 13 > 10. Reading the totals without the locks
would see 0, accept 5 and overwrite the other report.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.core.permissions import Role, permissions_for
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Product
from app.models.production import ProductionOperation, ProductionOrder
from app.models.work_center import WorkCenter
from app.services.context import Actor, RequestContext
from app.services.progress_service import ProgressService, Reporter

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 15


@dataclass(frozen=True)
class Setup:
    order_id: int
    operation_id: int


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> Setup:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-P{marker}", name="Frame", unit="pcs")
        center = WorkCenter(code=f"WC-P{marker}", name="Cut", active=True)
        session.add_all([product, center])
        session.flush()
        order = ProductionOrder(
            order_number=f"PO-P{marker}",
            product_id=product.id,
            planned_quantity=10,
            due_date=datetime.now(UTC) + timedelta(days=7),
            status="IN_PROGRESS",
        )
        session.add(order)
        session.flush()
        operation = ProductionOperation(
            production_order_id=order.id,
            sequence=10,
            operation_type="CUTTING",
            work_center_id=center.id,
            status="IN_PROGRESS",
        )
        session.add(operation)
        session.flush()
        return Setup(order.id, operation.id)


def report(factory: sessionmaker[Session], operation_id: int, good: int) -> str:
    reporter = Reporter(
        Actor(None, "conc"),
        Role.PRODUCTION_MANAGER,
        None,
        permissions_for(Role.PRODUCTION_MANAGER),
    )
    with factory() as session:
        try:
            ProgressService(session, SystemClock()).report(
                operation_id, good, 0, None, reporter, RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_br_op_07_concurrent_reports_of_one_order_are_serialized(
    factory: sessionmaker[Session], setup: Setup
) -> None:
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM production_orders WHERE id = :id FOR UPDATE"),
            {"id": setup.order_id},
        )
        holder.execute(
            text("UPDATE production_operations SET good_quantity = 8 WHERE id = :id"),
            {"id": setup.operation_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(report, factory, setup.operation_id, 5)
            time.sleep(0.5)
            assert not pending.done(), "the report must wait for the order row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "EXCEEDS_AVAILABLE_INPUT"
