"""B18 Phase 7 DoD: the seed builds a demo with every status, a shortage order, an
AT_RISK order and a bottleneck, all through the API."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.models.inventory_transaction import InventoryTransaction
from app.services.context import Actor, RequestContext
from app.services.user_service import NewUser, UserService
from seed.__main__ import business_data_present
from seed.demo import Shop, issue_all, report, seed_demo

PASSWORD = "demo-password-for-tests"


@pytest.fixture
def seeded(
    db_client: TestClient, db_session: Session, clock: FixedClock
) -> Iterator[dict[str, int]]:
    def create_admin(username: str, password: str) -> None:
        UserService(db_session, PasswordHasher()).create_user(
            NewUser(
                username=username,
                password=password,
                full_name="Demo Admin",
                role=Role.ADMIN,
                work_center_id=None,
            ),
            Actor(user_id=None, username="seed"),
            RequestContext(),
        )

    now = clock.now()
    orders = seed_demo(db_client, clock, PASSWORD, create_admin)
    assert clock.now() == now  # the story ends at "now"
    yield orders


def get(client: TestClient, path: str, username: str = "demo.manager") -> dict:  # type: ignore[type-arg]
    login = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get(f"/api/v1{path}", headers=headers)
    assert response.status_code == 200, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def test_seed_has_an_order_in_every_status(db_client: TestClient, seeded: dict[str, int]) -> None:
    counts = get(db_client, "/dashboard/production")["orders_by_status"]
    assert counts == {
        "DRAFT": 1,
        "MATERIAL_SHORTAGE": 1,
        "READY_TO_PRODUCE": 1,
        "IN_PROGRESS": 3,
        "COMPLETED": 1,
        "CANCELLED": 1,
    }
    completed = get(db_client, f"/production-orders/{seeded['completed']}")
    assert completed["completed_quantity"] == 19  # one frame scrapped at QC


def test_seed_risks_bottleneck_and_alerts(db_client: TestClient, seeded: dict[str, int]) -> None:
    risks = {r["order_id"]: r["risk"] for r in get(db_client, "/dashboard/risks")["items"]}
    assert risks[seeded["overdue"]] == "OVERDUE"
    assert risks[seeded["at_risk"]] == "AT_RISK"
    assert seeded["on_track"] not in risks  # ON_TRACK is hidden by default

    bottlenecks = get(db_client, "/dashboard/bottlenecks")["items"]
    flagged = [(b["work_center"], b["at_risk_orders"]) for b in bottlenecks if b["bottleneck"]]
    assert flagged == [("WC-WELD", 2)]

    alerts = get(db_client, "/dashboard/material-alerts")
    assert sorted(m["material_code"] for m in alerts["low_stock"]) == ["BOLT-M8", "STEEL-001"]
    assert alerts["recheck_candidates"] == []  # PO 7 is still short of steel


def test_seed_shortage_order_is_short_of_steel_only(
    db_client: TestClient, seeded: dict[str, int]
) -> None:
    lines = get(db_client, f"/production-orders/{seeded['shortage']}/materials")
    items = lines["items"] if isinstance(lines, dict) else lines
    short = {
        line["material_code"]: line["shortage_quantity"]
        for line in items
        if line["shortage_quantity"] not in ("0", "0.000", "0.00")
    }
    assert list(short) == ["STEEL-001"]


def test_seed_ledger_reconciles_and_workers_see_their_own_work(
    db_client: TestClient, db_session: Session, seeded: dict[str, int]
) -> None:
    assert get(db_client, "/admin/inventory-reconciliation", "demo.admin")["mismatches"] == []
    assert db_session.scalar(select(func.count()).select_from(InventoryTransaction)) > 0
    # BR-AUTH-03: the welder sees FRAME-A orders (their routing welds), never the brackets.
    welder = {o["id"] for o in get(db_client, "/production-orders", "demo.weld")["items"]}
    frames = {
        seeded[k] for k in ("completed", "cancelled", "overdue", "at_risk", "ready", "shortage")
    }
    assert welder == frames


def test_seed_refuses_a_database_with_business_data(
    db_session: Session, seeded: dict[str, int]
) -> None:
    assert business_data_present(db_session) == [
        "products",
        "materials",
        "production orders",
        "demo users",
    ]


def test_five_minute_demo_runs_on_the_seed(
    db_client: TestClient, clock: FixedClock, seeded: dict[str, int]
) -> None:
    """README demo (B19): shortage -> receive -> check-materials -> issue -> start ->
    progress with scrap -> risk -> completed."""
    shop = Shop(db_client, clock, PASSWORD)
    po7 = seeded["shortage"]
    steel = next(
        m["id"] for m in get(db_client, "/materials")["items"] if m["material_code"] == "STEEL-001"
    )

    shop.call(
        "demo.warehouse",
        "POST",
        "/inventory/receipts",
        {"material_id": steel, "quantity": "200", "reference": "GRN-DEMO"},
    )
    check = shop.call("demo.manager", "POST", f"/production-orders/{po7}/check-materials")
    assert check["reserved"] is True and check["status"] == "READY_TO_PRODUCE"

    issue_all(shop, po7)
    shop.call("demo.manager", "POST", f"/production-orders/{po7}/start")
    for sequence, good, rejected in [(10, 400, 0), (20, 400, 0), (30, 398, 2), (40, 396, 2)]:
        clock.advance(timedelta(hours=6))
        report(shop, po7, sequence, good, rejected)

    order = get(db_client, f"/production-orders/{po7}")
    assert (order["status"], order["completed_quantity"]) == ("COMPLETED", 396)
    assert po7 not in {r["order_id"] for r in get(db_client, "/dashboard/risks")["items"]}
