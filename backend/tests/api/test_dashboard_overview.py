"""GET /dashboard/bottlenecks, /material-alerts and /production (B9, D-09, D-25)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.master_data import Product
from app.models.production import ProductionOrder
from app.models.work_center import WorkCenter

DASHBOARD = "/api/v1/dashboard"


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


@pytest.fixture
def stations(work_center_factory) -> dict[str, WorkCenter]:
    return {code: work_center_factory(code) for code in ("WC-CUT", "WC-WELD", "WC-QC")}


def behind_schedule_order(
    session: Session,
    clock: FixedClock,
    order_factory,
    operation_factory,
    frame: Product,
    stations: dict[str, WorkCenter],
    number: str,
    due_in: timedelta,
) -> ProductionOrder:
    """Planned 100: cutting done (100), welding 60/100 -> current operation WC-WELD,
    workflow 0.53, started 95 h ago (AT_RISK while due in 5 h, OVERDUE once past due)."""
    order: ProductionOrder = order_factory(
        frame, status="IN_PROGRESS", planned_quantity=100, number=number
    )
    operation_factory(order, 10, "CUTTING", stations["WC-CUT"], status="COMPLETED", good=100)
    operation_factory(order, 20, "WELDING", stations["WC-WELD"], status="IN_PROGRESS", good=60)
    operation_factory(order, 30, "QC", stations["WC-QC"])
    if session.in_transaction():
        session.commit()
    with session.begin():
        order.started_at = clock.now() - timedelta(hours=95)
        order.due_date = clock.now() + due_in
    return order


# --- Bottlenecks --------------------------------------------------------------------------------


def test_b9_two_at_risk_orders_at_welding_make_it_the_bottleneck(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    clock: FixedClock,
    order_factory,
    operation_factory,
    frame: Product,
    stations: dict[str, WorkCenter],
) -> None:
    # One AT_RISK and one OVERDUE order: both count as at risk at their current station.
    for number, due_in in (
        ("PO-2026-00001", timedelta(hours=5)),
        ("PO-2026-00002", -timedelta(hours=1)),
    ):
        behind_schedule_order(
            db_session, clock, order_factory, operation_factory, frame, stations, number, due_in
        )
    page = db_client.get(f"{DASHBOARD}/bottlenecks", headers=pm).json()
    rows = [
        (i["work_center"], i["queue_units"], i["at_risk_orders"], i["bottleneck"])
        for i in page["items"]
    ]
    assert rows == [
        # 40 good units still to weld per order (limit 100, processed 60).
        ("WC-WELD", 80, 2, True),
        # QC has the largest queue (60 + 60 waiting) but no at-risk order sits there.
        ("WC-QC", 120, 0, False),
        ("WC-CUT", 0, 0, False),
    ]


# --- Material alerts ----------------------------------------------------------------------------


def test_d25_and_d09_material_alerts(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    material_factory,
    order_factory,
    order_line_factory,
) -> None:
    bolt = material_factory("BOLT-M8", unit="pcs", decimal_places=0, minimum_stock=Decimal(200))
    steel = material_factory("STEEL-001", unit="kg", decimal_places=3, minimum_stock=Decimal(50))
    ready = order_factory(frame, status="MATERIAL_SHORTAGE", number="PO-2026-00010")
    short = order_factory(frame, status="MATERIAL_SHORTAGE", number="PO-2026-00011")
    order_line_factory(ready, steel, required="40", on_hand="60")  # 60 available >= 40
    order_line_factory(short, bolt, required="840", on_hand="150")  # 150 < 840
    paint = material_factory("PAINT-01", unit="l", decimal_places=2)
    exact = order_factory(frame, status="MATERIAL_SHORTAGE", number="PO-2026-00012")
    order_line_factory(exact, paint, required="25.00", on_hand="25.00")  # exactly enough
    # An order without material lines has nothing to re-check; it is not suggested.
    order_factory(frame, status="MATERIAL_SHORTAGE", number="PO-2026-00013")

    body = db_client.get(f"{DASHBOARD}/material-alerts", headers=pm).json()
    # D-25: BOLT 150 < 200 is low; STEEL 60 >= 50 is not.
    assert [(m["material_code"], m["below_minimum_by"]) for m in body["low_stock"]] == [
        ("BOLT-M8", "50")
    ]
    # D-09: suggested only; the order is still MATERIAL_SHORTAGE.
    assert [o["production_order"] for o in body["recheck_candidates"]] == [
        "PO-2026-00010",
        "PO-2026-00012",
    ]
    db_session.expire_all()
    assert db_session.get(ProductionOrder, ready.id).status == "MATERIAL_SHORTAGE"  # type: ignore[union-attr]


# --- Production overview -------------------------------------------------------------------------


def test_production_overview_counts_and_due_soon(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    order_factory,
    clock: FixedClock,
) -> None:
    order_factory(frame, status="DRAFT", number="PO-2026-00020")  # due in 7 days exactly
    late = order_factory(frame, status="IN_PROGRESS", number="PO-2026-00021")
    later = order_factory(frame, status="READY_TO_PRODUCE", number="PO-2026-00022")
    order_factory(frame, status="COMPLETED", number="PO-2026-00023")
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        late.due_date = clock.now() - timedelta(days=1)
        later.due_date = clock.now() + timedelta(days=8)

    body = db_client.get(f"{DASHBOARD}/production", headers=pm).json()
    assert body["orders_by_status"] == {
        "DRAFT": 1,
        "MATERIAL_SHORTAGE": 0,
        "READY_TO_PRODUCE": 1,
        "IN_PROGRESS": 1,
        "COMPLETED": 1,
        "CANCELLED": 0,
    }
    assert [o["production_order"] for o in body["due_within_7_days"]] == [
        "PO-2026-00021",  # overdue first
        "PO-2026-00020",
    ]


@pytest.mark.parametrize("page", ["production", "bottlenecks", "material-alerts"])
def test_b4_workers_have_no_dashboard(db_client: TestClient, login_as, page: str) -> None:
    assert db_client.get(f"{DASHBOARD}/{page}", headers=login_as(Role.WORKER)).status_code == 403
