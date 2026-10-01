"""Reading orders, their materials and operations; BR-AUTH-03 / D-18 scope for WORKER."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.master_data import Product
from app.models.production import ProductionOperation, ProductionOrder
from app.models.work_center import WorkCenter

ORDERS = "/api/v1/production-orders"


def add_operations(
    session: Session, order: ProductionOrder, steps: list[tuple[int, str, WorkCenter]]
) -> None:
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.add_all(
            ProductionOperation(
                production_order_id=order.id,
                sequence=sequence,
                operation_type=operation_type,
                work_center_id=center.id,
                status="PENDING",
            )
            for sequence, operation_type, center in steps
        )


class Shop:
    """Two orders: X has a WELDING step at WC-WELD, Y only runs at WC-CUT and WC-QC."""

    def __init__(self, session: Session, product: Product, factory, centers) -> None:
        self.weld, self.cut, self.qc = centers
        self.x: ProductionOrder = factory(product, status="IN_PROGRESS", number="PO-2026-00001")
        self.y: ProductionOrder = factory(
            product, status="READY_TO_PRODUCE", number="PO-2026-00002"
        )
        add_operations(
            session,
            self.x,
            [(10, "CUTTING", self.cut), (20, "WELDING", self.weld), (30, "QC", self.qc)],
        )
        add_operations(session, self.y, [(10, "CUTTING", self.cut), (20, "QC", self.qc)])


@pytest.fixture
def shop(db_session: Session, product_factory, order_factory, work_center_factory) -> Shop:
    centers = [work_center_factory(code) for code in ("WC-WELD", "WC-CUT", "WC-QC")]
    return Shop(db_session, product_factory("FRAME-A"), order_factory, centers)


@pytest.fixture
def welder(login_as, shop: Shop) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WORKER, work_center_id=shop.weld.id)
    return headers


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


# --- Managers see everything ----------------------------------------------------------------


def test_orders_are_listed_by_due_date_with_filters_and_actions(
    db_client: TestClient, db_session: Session, pm: dict[str, str], shop: Shop
) -> None:
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        shop.y.due_date = shop.x.due_date - timedelta(days=1)  # Y is due first
    page = db_client.get(ORDERS, headers=pm).json()
    assert page["total"] == 2
    assert [(o["order_number"], o["allowed_actions"]) for o in page["items"]] == [
        ("PO-2026-00002", ["start", "cancel"]),
        ("PO-2026-00001", []),
    ]
    in_progress = db_client.get(ORDERS, params={"status": "IN_PROGRESS"}, headers=pm).json()
    assert [o["order_number"] for o in in_progress["items"]] == ["PO-2026-00001"]
    assert db_client.get(ORDERS, params={"status": "PLANNED"}, headers=pm).status_code == 422


def test_order_detail_materials_and_operations(
    db_client: TestClient, pm: dict[str, str], shop: Shop, material_factory, order_line_factory
) -> None:
    bolt = material_factory("BOLT-M8", unit="pcs", decimal_places=0)
    order_line_factory(shop.y, bolt, required="840", reserved="840", on_hand="1000")

    detail = db_client.get(f"{ORDERS}/{shop.y.id}", headers=pm).json()
    assert (detail["order_number"], detail["product_code"], detail["status"]) == (
        "PO-2026-00002",
        "FRAME-A",
        "READY_TO_PRODUCE",
    )
    [line] = db_client.get(f"{ORDERS}/{shop.y.id}/materials", headers=pm).json()["items"]
    assert (line["material_code"], line["required_quantity"], line["reserved_quantity"]) == (
        "BOLT-M8",
        "840",
        "840",
    )
    assert (line["issued_quantity"], line["shortage_quantity"]) == ("0", "0")
    operations = db_client.get(f"{ORDERS}/{shop.y.id}/operations", headers=pm).json()["items"]
    assert [
        (op["sequence"], op["operation_type"], op["work_center_code"]) for op in operations
    ] == [
        (10, "CUTTING", "WC-CUT"),
        (20, "QC", "WC-QC"),
    ]


def test_unknown_order_is_404(db_client: TestClient, pm: dict[str, str]) -> None:
    for suffix in ("", "/materials", "/operations"):
        response = db_client.get(f"{ORDERS}/999999{suffix}", headers=pm)
        assert (response.status_code, response.json()["error"]["code"]) == (404, "ORDER_NOT_FOUND")


# --- BR-AUTH-03: a WORKER sees only their work center -----------------------------------------


def test_br_auth_03_worker_lists_only_orders_with_work_at_their_center(
    db_client: TestClient, welder: dict[str, str], shop: Shop
) -> None:
    page = db_client.get(ORDERS, headers=welder).json()
    assert [o["order_number"] for o in page["items"]] == ["PO-2026-00001"]
    assert page["total"] == 1
    assert page["items"][0]["allowed_actions"] == []


@pytest.mark.parametrize("suffix", ["", "/materials", "/operations"])
def test_br_auth_03_order_outside_the_workers_scope_is_404_not_403(
    db_client: TestClient, welder: dict[str, str], shop: Shop, suffix: str
) -> None:
    response = db_client.get(f"{ORDERS}/{shop.y.id}{suffix}", headers=welder)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "ORDER_NOT_FOUND")


def test_br_auth_03_worker_sees_only_the_operations_at_their_center(
    db_client: TestClient, welder: dict[str, str], pm: dict[str, str], shop: Shop
) -> None:
    mine = db_client.get(f"{ORDERS}/{shop.x.id}/operations", headers=welder).json()["items"]
    assert [(op["sequence"], op["work_center_code"]) for op in mine] == [(20, "WC-WELD")]
    everything = db_client.get(f"{ORDERS}/{shop.x.id}/operations", headers=pm).json()
    assert everything["total"] == 3


def test_br_auth_03_scope_follows_the_workers_current_assignment(
    db_client: TestClient, db_session: Session, shop: Shop, user_factory
) -> None:
    """C-01: the work center comes from the database on every request, not the token."""
    worker = user_factory("weld01", role=Role.WORKER, work_center_id=shop.weld.id)
    token = db_client.post(
        "/api/v1/auth/login",
        json={"username": "weld01", "password": "correct-horse-battery-staple"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert db_client.get(f"{ORDERS}/{shop.y.id}", headers=headers).status_code == 404

    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():
        worker.work_center_id = shop.cut.id  # moved to cutting: now both orders are visible
    assert db_client.get(f"{ORDERS}/{shop.y.id}", headers=headers).status_code == 200
    assert db_client.get(ORDERS, headers=headers).json()["total"] == 2
