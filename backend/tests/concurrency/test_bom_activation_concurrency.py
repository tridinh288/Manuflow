"""D-19 under concurrency: BOM activation locks its materials (material_id ascending).

A material deactivation that is still uncommitted must make a concurrent activation of
a BOM that uses it fail with MATERIAL_INACTIVE. With plain reads the activation would
see the committed snapshot (material still active) and activate a BOM with a material
that is being deactivated.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import SystemClock
from app.db.session import build_session_factory
from app.domain.errors import DomainError
from app.models.bom import BomHeader, BomItem
from app.models.master_data import Inventory, Material, Product
from app.services.bom_service import BomService
from app.services.context import Actor, RequestContext

pytestmark = pytest.mark.concurrency

WAIT_SECONDS = 10


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(db_engine)


@pytest.fixture
def draft(factory: sessionmaker[Session]) -> Iterator[tuple[int, int]]:
    """(bom_id, material_id) of a committed DRAFT BOM with one line."""
    marker = uuid.uuid4().hex[:6].upper()
    with factory() as session, session.begin():
        product = Product(product_code=f"CONC-P{marker}", name="Concurrency", unit="pcs")
        material = Material(
            material_code=f"CONC-M{marker}", name="Concurrency", unit="kg", decimal_places=3
        )
        session.add_all([product, material])
        session.flush()
        header = BomHeader(
            product_id=product.id,
            version=1,
            status="DRAFT",
            items=[BomItem(material_id=material.id, qty_per_unit=Decimal(2))],
        )
        session.add(header)
        session.flush()
        ids = (header.id, material.id, product.id)
    yield ids[0], ids[1]
    bom_id, material_id, product_id = ids
    with factory() as session, session.begin():
        session.execute(delete(BomItem).where(BomItem.bom_header_id == bom_id))
        session.execute(delete(BomHeader).where(BomHeader.id == bom_id))
        session.execute(delete(Inventory).where(Inventory.material_id == material_id))
        session.execute(delete(Material).where(Material.id == material_id))
        session.execute(delete(Product).where(Product.id == product_id))


def activate(factory: sessionmaker[Session], bom_id: int) -> str:
    with factory() as session:
        try:
            BomService(session, SystemClock()).activate(
                bom_id, Actor(user_id=None, username="conc"), RequestContext()
            )
        except DomainError as exc:
            return exc.code
    return "OK"


def test_d19_activation_sees_a_concurrent_material_deactivation(
    factory: sessionmaker[Session], draft: tuple[int, int]
) -> None:
    bom_id, material_id = draft
    with factory() as holder, holder.begin():
        holder.execute(
            text("SELECT id FROM materials WHERE id = :id FOR UPDATE"), {"id": material_id}
        )
        holder.execute(text("UPDATE materials SET active = 0 WHERE id = :id"), {"id": material_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(activate, factory, bom_id)
            time.sleep(0.5)
            assert not pending.done(), "activation must wait for the material row lock"
            holder.commit()
            assert pending.result(WAIT_SECONDS) == "MATERIAL_INACTIVE"
