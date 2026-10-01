"""D-13 under concurrency: cancel releases only what is still reserved *after* a concurrent
issue commits.

Another transaction holds the order row and has issued 500 of 840 reserved bolts, not yet
committed. cancel must wait for the order lock, then release 340, leaving 0 reserved. If it
read the line without waiting it would release 840 and drive reserved stock negative.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOrder, ProductionOrderMaterial
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.services.context import Actor, RequestContext
from app.services.production_service import ProductionOrderService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 15


@dataclass(frozen=True)
class Setup:
    order_id: int
    line_id: int
    material_id: int


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> Iterator[Setup]:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-X{marker}", name="Frame", unit="pcs")
        bolt = Material(material_code=f"CONC-Y{marker}", name="Bolt", unit="pcs", decimal_places=0)
        session.add_all([product, bolt])
        session.flush()
        warehouse_id = session.scalars(
            select(Warehouse.id).where(Warehouse.code == DEFAULT_WAREHOUSE_CODE)
        ).one()
        session.add(
            Inventory(
                warehouse_id=warehouse_id,
                material_id=bolt.id,
                on_hand_quantity=1000,
                reserved_quantity=840,
            )
        )
        order = ProductionOrder(
            order_number=f"PO-X{marker}",
            product_id=product.id,
            planned_quantity=100,
            due_date=datetime.now(UTC) + timedelta(days=7),
            status="READY_TO_PRODUCE",
        )
        session.add(order)
        session.flush()
        line = ProductionOrderMaterial(
            production_order_id=order.id,
            material_id=bolt.id,
            required_quantity=Decimal(840),
            reserved_quantity=Decimal(840),
        )
        session.add(line)
        session.flush()
        ids = Setup(order.id, line.id, bolt.id)
    yield ids  # ledger and audit rows from cancel are append-only; codes are unique


def cancel(factory: sessionmaker[Session], order_id: int) -> str:
    with factory() as session:
        try:
            ProductionOrderService(session, SystemClock()).cancel(
                order_id, "Concurrency test", Actor(None, "conc"), RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_d13_cancel_waits_for_a_concurrent_issue_and_releases_only_the_rest(
    factory: sessionmaker[Session], setup: Setup
) -> None:
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM production_orders WHERE id = :id FOR UPDATE"),
            {"id": setup.order_id},
        )
        holder.execute(
            text(
                "UPDATE production_order_materials SET reserved_quantity = 340, "
                "issued_quantity = 500 WHERE id = :id"
            ),
            {"id": setup.line_id},
        )
        holder.execute(
            text(
                "UPDATE inventory SET on_hand_quantity = 500, reserved_quantity = 340 "
                "WHERE material_id = :id"
            ),
            {"id": setup.material_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(cancel, factory, setup.order_id)
            time.sleep(0.5)
            assert not pending.done(), "cancel must wait for the order row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "OK"

    with factory() as session:
        balance = session.scalars(
            select(Inventory).where(Inventory.material_id == setup.material_id)
        ).one()
        line = session.get(ProductionOrderMaterial, setup.line_id)
        assert line is not None
        assert (balance.on_hand_quantity, balance.reserved_quantity) == (Decimal(500), Decimal(0))
        assert (line.reserved_quantity, line.issued_quantity) == (Decimal(0), Decimal(500))
