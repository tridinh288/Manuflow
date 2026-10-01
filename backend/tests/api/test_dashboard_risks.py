"""GET /dashboard/risks (B9, test 18 through the API) and the B8 figures on operations."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.master_data import Product
from app.models.production import ProductionOrder
from app.models.work_center import WorkCenter

RISKS = "/api/v1/dashboard/risks"


def set_dates(
    session: Session,
    order: ProductionOrder,
    clock: FixedClock,
    due_in: timedelta,
    started_ago: timedelta | None = None,
) -> None:
    if session.in_transaction():
        session.commit()
    with session.begin():
        order.due_date = clock.now() + due_in
        order.started_at = clock.now() - started_ago if started_ago is not None else None


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


@pytest.fixture
def stations(work_center_factory) -> dict[str, WorkCenter]:
    return {
        code: work_center_factory(code)
        for code in ("WC-CUT", "WC-CNC", "WC-WELD", "WC-PAINT", "WC-QC")
    }


@pytest.fixture
def b8_order(
    db_session: Session,
    frame: Product,
    stations: dict[str, WorkCenter],
    order_factory,
    operation_factory,
) -> ProductionOrder:
    """The B8 example: planned 100, CUTTING/CNC done, WELDING 80, PAINTING 50, QC 0."""
    order: ProductionOrder = order_factory(
        frame, status="IN_PROGRESS", planned_quantity=100, number="PO-2026-00001"
    )
    plan = [
        (10, "CUTTING", "WC-CUT", "COMPLETED", 100, 0),
        (20, "CNC", "WC-CNC", "COMPLETED", 97, 3),
        (30, "WELDING", "WC-WELD", "IN_PROGRESS", 80, 0),
        (40, "PAINTING", "WC-PAINT", "IN_PROGRESS", 50, 0),
        (50, "QC", "WC-QC", "PENDING", 0, 0),
    ]
    for sequence, kind, center, status, good, rejected in plan:
        operation_factory(
            order, sequence, kind, stations[center], status=status, good=good, rejected=rejected
        )
    return order


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


def test_b8_operations_endpoint_reports_the_worked_example(
    db_client: TestClient, pm: dict[str, str], b8_order: ProductionOrder
) -> None:
    body = db_client.get(f"/api/v1/production-orders/{b8_order.id}/operations", headers=pm).json()
    assert (body["workflow_progress"], body["finished_progress"]) == (0.66, 0.0)
    assert [(op["sequence"], op["progress"], op["yield_rate"]) for op in body["items"]] == [
        (10, 1.0, 1.0),
        (20, 1.0, 0.97),
        (30, 0.8, 1.0),
        (40, 0.5, 1.0),
        (50, 0.0, None),
    ]
    # D-14, shown on the worker page: limit(1) = planned, limit(n) = good(n-1).
    assert [(op["limit"], op["processed_quantity"]) for op in body["items"]] == [
        (100, 100),
        (100, 100),
        (97, 80),
        (80, 50),
        (50, 0),
    ]


def test_b9_behind_schedule_order_is_reported_with_its_current_operation(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    b8_order: ProductionOrder,
    clock: FixedClock,
) -> None:
    # 96-hour window with 90 hours used: time ratio 0.94 against workflow progress 0.66,
    # a gap of 0.28 > 0.20. (78 hours, the B9 ratio of 0.81, would only be 0.15 behind.)
    set_dates(
        db_session, b8_order, clock, due_in=timedelta(hours=6), started_ago=timedelta(hours=90)
    )
    [item] = db_client.get(RISKS, headers=pm).json()["items"]
    assert item == {
        "order_id": b8_order.id,
        "production_order": "PO-2026-00001",
        "product_code": "FRAME-A",
        "status": "IN_PROGRESS",
        "due_date": (clock.now() + timedelta(hours=6)).isoformat().replace("+00:00", "Z"),
        "risk": "AT_RISK",
        "reason_code": "BEHIND_SCHEDULE",
        "time_ratio": 0.94,
        "workflow_progress": 0.66,
        "finished_progress": 0.0,
        "current_operation": {
            "sequence": 30,
            "type": "WELDING",
            "work_center": "WC-WELD",
            "progress": 0.8,
        },
        "message": "Đã dùng 94% thời gian nhưng lệnh mới đi được 66% quy trình.",
    }


def test_b9_overdue_first_on_track_hidden_unless_asked(
    db_client: TestClient,
    db_session: Session,
    login_as,
    frame: Product,
    order_factory,
    clock: FixedClock,
) -> None:
    soon = order_factory(frame, status="READY_TO_PRODUCE", number="PO-2026-00010")
    late = order_factory(frame, status="DRAFT", number="PO-2026-00011")
    fine = order_factory(frame, status="DRAFT", number="PO-2026-00012")
    done = order_factory(frame, status="COMPLETED", number="PO-2026-00013")
    set_dates(db_session, soon, clock, due_in=timedelta(hours=10))
    set_dates(db_session, late, clock, due_in=timedelta(hours=20))  # due later than "soon"...
    set_dates(db_session, fine, clock, due_in=timedelta(days=10))
    set_dates(db_session, done, clock, due_in=timedelta(days=-10))
    clock.advance(timedelta(hours=21))  # ...but now both are past due: late was due at +20 h
    pm = login_as(Role.PRODUCTION_MANAGER)  # the earlier 30-minute token has expired

    items = db_client.get(RISKS, headers=pm).json()["items"]
    assert [(i["production_order"], i["risk"], i["reason_code"]) for i in items] == [
        ("PO-2026-00010", "OVERDUE", "PAST_DUE"),
        ("PO-2026-00011", "OVERDUE", "PAST_DUE"),
    ]
    everything = db_client.get(RISKS, params={"include_on_track": "true"}, headers=pm).json()[
        "items"
    ]
    assert [i["production_order"] for i in everything] == [
        "PO-2026-00010",
        "PO-2026-00011",
        "PO-2026-00012",
    ]  # COMPLETED orders carry no risk at all
    assert everything[-1]["risk"] == "ON_TRACK"


def test_b9_at_risk_comes_before_on_track_even_when_due_later(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    order_factory,
    b8_order: ProductionOrder,
    clock: FixedClock,
) -> None:
    on_track = order_factory(frame, status="READY_TO_PRODUCE", number="PO-2026-00020")
    set_dates(db_session, on_track, clock, due_in=timedelta(days=3))
    # B8 order: 66% done, 96 % of its window used -> AT_RISK, yet due a day after the other.
    set_dates(db_session, b8_order, clock, due_in=timedelta(days=4), started_ago=timedelta(days=96))
    items = db_client.get(RISKS, params={"include_on_track": "true"}, headers=pm).json()["items"]
    assert [(i["production_order"], i["risk"]) for i in items] == [
        ("PO-2026-00001", "AT_RISK"),
        ("PO-2026-00020", "ON_TRACK"),
    ]


def test_b4_workers_have_no_dashboard(db_client: TestClient, login_as) -> None:
    assert db_client.get(RISKS, headers=login_as(Role.WORKER)).status_code == 403


def test_d14_operations_of_an_order_without_operations_is_an_empty_list(
    db_client: TestClient, pm: dict[str, str], order_factory, frame: Product
) -> None:
    draft = order_factory(frame, status="DRAFT", number="PO-2026-00099")
    response = db_client.get(f"/api/v1/production-orders/{draft.id}/operations", headers=pm)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
