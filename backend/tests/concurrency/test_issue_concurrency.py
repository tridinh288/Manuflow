"""D-10 under concurrency: two issues against one order line never exceed its reservation.

Another transaction has issued 500 of the 840 reserved bolts and not committed. Our
issue of 500 must wait for the line's row lock, then see only 340 still reserved and be
refused. Reading the line without the lock would see 840 and issue twice.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOrder, ProductionOrderMaterial
from app.models.warehouse import DEFAULT_WAREHOUSE_CODE, Warehouse
from app.services.context import Actor, RequestContext
from app.services.inventory_service import InventoryService

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 15


@dataclass(frozen=True)
class Line:
    line_id: int
    material_id: int


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def line(factory: sessionmaker[Session]) -> Iterator[Line]:
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-I{marker}", name="Frame", unit="pcs")
        bolt = Material(material_code=f"CONC-J{marker}", name="Bolt", unit="pcs", decimal_places=0)
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
            order_number=f"PO-I{marker}",
            product_id=product.id,
            planned_quantity=100,
            due_date=datetime.now(UTC) + timedelta(days=7),
            status="READY_TO_PRODUCE",
        )
        session.add(order)
        session.flush()
        order_line = ProductionOrderMaterial(
            production_order_id=order.id,
            material_id=bolt.id,
            required_quantity=Decimal(840),
            reserved_quantity=Decimal(840),
        )
        session.add(order_line)
        session.flush()
        ids = (order_line.id, bolt.id, order.id, product.id)
    yield Line(ids[0], ids[1])
    line_id, material_id, order_id, product_id = ids
    with factory() as session, session.begin():
        session.execute(delete(ProductionOrderMaterial).where(ProductionOrderMaterial.id == line_id))
        session.execute(delete(ProductionOrder).where(ProductionOrder.id == order_id))
        session.execute(delete(Inventory).where(Inventory.material_id == material_id))
        session.execute(delete(Material).where(Material.id == material_id))
        session.execute(delete(Product).where(Product.id == product_id))


def issue(factory: sessionmaker[Session], line_id: int, quantity: int) -> str:
    with factory() as session:
        try:
            InventoryService(session).issue(
                line_id, Decimal(quantity), Actor(None, "conc"), RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_d10_concurrent_issue_sees_what_the_other_issue_consumed(
    factory: sessionmaker[Session], line: Line
) -> None:
    with factory() as holder, holder.begin():
        # The uncommitted twin issue: 500 moved from reserved to issued, stock reduced.
        holder.execute(
            text(
                "UPDATE production_order_materials SET reserved_quantity = 340, "
                "issued_quantity = 500 WHERE id = :id"
            ),
            {"id": line.line_id},
        )
        holder.execute(
            text(
                "UPDATE inventory SET on_hand_quantity = 500, reserved_quantity = 340 "
                "WHERE material_id = :id"
            ),
            {"id": line.material_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(issue, factory, line.line_id, 500)
            time.sleep(0.5)
            assert not pending.done(), "the issue must wait for the order line's row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "EXCEEDS_RESERVED"
