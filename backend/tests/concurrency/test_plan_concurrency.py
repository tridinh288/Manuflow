"""Test 11 of B15: two orders plan at once on BOLT-M8 with 100 on hand (B12 scenario).

Order A needs 80, order B needs 50. Whatever the interleaving, exactly one order ends
READY_TO_PRODUCE, the other MATERIAL_SHORTAGE, and available stock never goes negative.
Committed ledger and audit rows stay (append-only); codes are unique per test.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.db.session import build_session_factory
from app.models.bom import BomHeader, BomItem
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOrder
from app.models.routing import Routing, RoutingStep
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.models.work_center import WorkCenter
from app.services.context import Actor, RequestContext
from app.services.production_service import ProductionOrderService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 15


@dataclass(frozen=True)
class Setup:
    material_id: int
    order_a: int  # needs 80
    order_b: int  # needs 50


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> Setup:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-F{marker}", name="Frame", unit="pcs")
        bolt = Material(material_code=f"CONC-B{marker}", name="Bolt", unit="pcs", decimal_places=0)
        station = WorkCenter(code=f"WC-Q{marker}", name="QC", active=True)
        session.add_all([product, bolt, station])
        session.flush()
        warehouse_id = session.scalars(
            select(Warehouse.id).where(Warehouse.code == DEFAULT_WAREHOUSE_CODE)
        ).one()
        session.add(Inventory(warehouse_id=warehouse_id, material_id=bolt.id, on_hand_quantity=100))
        session.add(
            BomHeader(
                product_id=product.id,
                version=1,
                status="ACTIVE",
                items=[BomItem(material_id=bolt.id, qty_per_unit=Decimal(1))],
            )
        )
        session.add(
            Routing(
                product_id=product.id,
                version=1,
                status="ACTIVE",
                steps=[RoutingStep(sequence=10, operation_type="QC", work_center_id=station.id)],
            )
        )
        due = datetime.now(UTC) + timedelta(days=7)
        orders = [
            ProductionOrder(
                order_number=f"PO-C{marker}-{qty}",
                product_id=product.id,
                planned_quantity=qty,
                due_date=due,
                status="DRAFT",
            )
            for qty in (80, 50)
        ]
        session.add_all(orders)
        session.flush()
        return Setup(bolt.id, orders[0].id, orders[1].id)


def plan(factory: sessionmaker[Session], order_id: int) -> str:
    with factory() as session:
        result = ProductionOrderService(session, SystemClock()).plan(
            order_id, Actor(None, "conc"), RequestContext()
        )
    return result.view.order.status


def stock(factory: sessionmaker[Session], material_id: int) -> tuple[Decimal, Decimal]:
    with factory() as session:
        row = session.scalars(select(Inventory).where(Inventory.material_id == material_id)).one()
        return row.on_hand_quantity, row.reserved_quantity


def reserve_lines(factory: sessionmaker[Session], material_id: int) -> int:
    with factory() as session:
        return len(
            session.scalars(
                select(InventoryTransaction).where(
                    InventoryTransaction.material_id == material_id,
                    InventoryTransaction.type == "RESERVE",
                )
            ).all()
        )


def test_b12_two_concurrent_plans_reserve_for_exactly_one_order(
    factory: sessionmaker[Session], setup: Setup
) -> None:
    start = threading.Barrier(2)

    def race(order_id: int) -> tuple[int, str]:
        start.wait(WAIT_SECONDS)
        return order_id, plan(factory, order_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(race, setup.order_a), pool.submit(race, setup.order_b)]
        outcome = dict(f.result(WAIT_SECONDS) for f in futures)

    assert sorted(outcome.values()) == ["MATERIAL_SHORTAGE", "READY_TO_PRODUCE"]
    winner = next(order for order, status in outcome.items() if status == "READY_TO_PRODUCE")
    reserved_for_winner = Decimal(80 if winner == setup.order_a else 50)
    on_hand, reserved = stock(factory, setup.material_id)
    assert (on_hand, reserved) == (Decimal(100), reserved_for_winner)
    assert on_hand - reserved >= 0  # available never negative
    assert reserve_lines(factory, setup.material_id) == 1


def test_b12_second_plan_waits_for_the_first_and_sees_its_reservation(
    factory: sessionmaker[Session], setup: Setup
) -> None:
    """The B12 walkthrough made deterministic: A holds the BOLT row with 80 reserved and
    has not committed. B must wait, then see available 20 and end in shortage. Reading
    the balance without the row lock would see 100 available and overwrite A's 80."""
    with factory() as holder, holder.begin():
        holder.execute(
            text(
                "UPDATE inventory SET reserved_quantity = reserved_quantity + 80 "
                "WHERE material_id = :id"
            ),
            {"id": setup.material_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(plan, factory, setup.order_b)
            time.sleep(0.5)
            assert not pending.done(), "the second plan must wait for the inventory row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "MATERIAL_SHORTAGE"

    assert stock(factory, setup.material_id) == (Decimal(100), Decimal(80))  # available 20
