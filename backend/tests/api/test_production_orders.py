"""Create and update production orders: B7, D-06, D-21, D-23, BR-PO-01/02/05, C-13."""

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.master_data import Product

ORDERS = "/api/v1/production-orders"
APP_DIR = Path(__file__).resolve().parents[2] / "app"


@pytest.fixture
def pm(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.PRODUCTION_MANAGER)
    return headers


@pytest.fixture
def frame(product_factory) -> Product:
    product: Product = product_factory("FRAME-A")
    return product


def due(clock: FixedClock, days: int = 7) -> str:
    return (clock.now() + timedelta(days=days)).isoformat()


def create(client: TestClient, headers: dict[str, str], **body: Any) -> Any:
    return client.post(ORDERS, json=body, headers=headers)


def set_status(session: Session, order_id: int, status: str) -> None:
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(
            text("UPDATE production_orders SET status = :s WHERE id = :id"),
            {"s": status, "id": order_id},
        )


# --- Create ---------------------------------------------------------------------------


def test_b7_create_gives_a_numbered_draft_with_allowed_actions(
    db_client: TestClient, pm: dict[str, str], frame: Product, clock: FixedClock
) -> None:
    response = create(
        db_client, pm, product_id=frame.id, planned_quantity=100, due_date=due(clock), notes="Rush"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["order_number"] == "PO-2026-00001"
    assert (body["status"], body["product_code"], body["planned_quantity"]) == (
        "DRAFT",
        "FRAME-A",
        100,
    )
    assert body["allowed_actions"] == ["update", "plan", "cancel"]
    assert body["bom_header_id"] is None and body["completed_quantity"] is None


def test_d21_numbers_are_consecutive_per_year_and_never_skip_on_failure(
    db_client: TestClient,
    login_as,
    pm: dict[str, str],
    frame: Product,
    product_factory,
    clock: FixedClock,
) -> None:
    retired = product_factory("OLD-FRAME", active=False)
    numbers = [
        create(db_client, pm, product_id=frame.id, planned_quantity=1, due_date=due(clock)).json()[
            "order_number"
        ]
    ]
    failed = create(db_client, pm, product_id=retired.id, planned_quantity=1, due_date=due(clock))
    assert failed.status_code == 409  # took a number, then rolled back with it
    numbers.append(
        create(db_client, pm, product_id=frame.id, planned_quantity=1, due_date=due(clock)).json()[
            "order_number"
        ]
    )
    clock.advance(timedelta(days=100))  # 2027; the 30-minute token has expired
    fresh = login_as(Role.PRODUCTION_MANAGER)
    numbers.append(
        create(
            db_client, fresh, product_id=frame.id, planned_quantity=1, due_date=due(clock)
        ).json()["order_number"]
    )
    assert numbers == ["PO-2026-00001", "PO-2026-00002", "PO-2027-00001"]


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "10", True, None], ids=repr)
def test_d06_planned_quantity_must_be_a_positive_whole_number(
    db_client: TestClient, pm: dict[str, str], frame: Product, clock: FixedClock, quantity: Any
) -> None:
    response = create(
        db_client, pm, product_id=frame.id, planned_quantity=quantity, due_date=due(clock)
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "INVALID_QUANTITY")


@pytest.mark.parametrize(
    ("due_date", "code"),
    [
        ("2026-09-30T07:59:59Z", "INVALID_DUE_DATE"),  # one second before the fixed clock
        ("2026-09-30T08:00:00Z", "INVALID_DUE_DATE"),  # now is not in the future
        ("2026-12-01T00:00:00", "VALIDATION_ERROR"),  # naive: no timezone (D-23)
    ],
)
def test_b7_due_date_must_be_in_the_future_and_timezone_aware(
    db_client: TestClient, pm: dict[str, str], frame: Product, due_date: str, code: str
) -> None:
    response = create(db_client, pm, product_id=frame.id, planned_quantity=5, due_date=due_date)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


def test_d23_due_date_is_stored_in_utc(
    db_client: TestClient, pm: dict[str, str], frame: Product
) -> None:
    body = create(
        db_client, pm, product_id=frame.id, planned_quantity=5, due_date="2026-10-02T15:00:00+07:00"
    ).json()
    assert body["due_date"] == "2026-10-02T08:00:00Z"


def test_br_md_04_inactive_or_unknown_product_cannot_be_ordered(
    db_client: TestClient, pm: dict[str, str], product_factory, clock: FixedClock
) -> None:
    retired = product_factory("OLD-FRAME", active=False)
    inactive = create(db_client, pm, product_id=retired.id, planned_quantity=1, due_date=due(clock))
    assert (inactive.status_code, inactive.json()["error"]["code"]) == (409, "PRODUCT_INACTIVE")
    unknown = create(db_client, pm, product_id=999999, planned_quantity=1, due_date=due(clock))
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "PRODUCT_NOT_FOUND")


def test_br_auth_01_client_cannot_set_status_or_number(
    db_client: TestClient, pm: dict[str, str], frame: Product, clock: FixedClock
) -> None:
    for extra in ({"status": "IN_PROGRESS"}, {"order_number": "PO-1999-99999"}):
        response = create(
            db_client, pm, product_id=frame.id, planned_quantity=1, due_date=due(clock), **extra
        )
        assert response.status_code == 422


def test_br_aud_01_creation_is_audited(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    clock: FixedClock,
) -> None:
    order_id = create(
        db_client, pm, product_id=frame.id, planned_quantity=100, due_date="2026-10-10T00:00:00Z"
    ).json()["id"]
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_CREATED"))
    assert (row.entity_type, row.entity_id) == ("production_order", order_id)
    assert row.new_value == {
        "order_number": "PO-2026-00001",
        "product_code": "FRAME-A",
        "planned_quantity": 100,
        "due_date": "2026-10-10T00:00:00+00:00",
        "status": "DRAFT",
    }


# --- Update (DRAFT only) ----------------------------------------------------------------


def test_b7_draft_can_be_updated_and_only_changes_are_audited(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    clock: FixedClock,
) -> None:
    order_id = create(
        db_client, pm, product_id=frame.id, planned_quantity=100, due_date=due(clock)
    ).json()["id"]
    response = db_client.patch(
        f"{ORDERS}/{order_id}", json={"planned_quantity": 120, "notes": "Customer +20"}, headers=pm
    )
    assert response.status_code == 200
    assert (response.json()["planned_quantity"], response.json()["notes"]) == (120, "Customer +20")
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "ORDER_UPDATED"))
    assert (row.old_value, row.new_value) == (
        {"planned_quantity": 100, "notes": None},
        {"planned_quantity": 120, "notes": "Customer +20"},
    )


@pytest.mark.parametrize(
    "status", ["MATERIAL_SHORTAGE", "READY_TO_PRODUCE", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
)
def test_br_po_01_only_a_draft_can_be_updated(
    db_client: TestClient,
    db_session: Session,
    pm: dict[str, str],
    frame: Product,
    order_factory,
    status: str,
) -> None:
    order = order_factory(frame, status=status)
    response = db_client.patch(f"{ORDERS}/{order.id}", json={"notes": "late"}, headers=pm)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INVALID_STATE_TRANSITION"
    assert (error["details"][0]["current_status"], error["details"][0]["action"]) == (
        status,
        "update",
    )


@pytest.mark.parametrize(
    "body",
    [{"planned_quantity": None}, {"due_date": None}, {"planned_quantity": 0}, {"status": "DRAFT"}],
    ids=["null-quantity", "null-due", "zero", "status"],
)
def test_b7_invalid_update_is_422(
    db_client: TestClient, pm: dict[str, str], frame: Product, order_factory, body: dict[str, Any]
) -> None:
    order = order_factory(frame)
    assert db_client.patch(f"{ORDERS}/{order.id}", json=body, headers=pm).status_code == 422


def test_unknown_order_is_404(db_client: TestClient, pm: dict[str, str]) -> None:
    response = db_client.patch(f"{ORDERS}/999999", json={"notes": "x"}, headers=pm)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "ORDER_NOT_FOUND")


# --- C-13: a product with open orders cannot be deactivated --------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [("DRAFT", 409), ("IN_PROGRESS", 409), ("COMPLETED", 204), ("CANCELLED", 204)],
)
def test_c13_product_with_open_orders_cannot_be_deactivated(
    db_client: TestClient,
    pm: dict[str, str],
    frame: Product,
    order_factory,
    status: str,
    expected: int,
) -> None:
    order_factory(frame, status=status, number="PO-2026-00042")
    response = db_client.delete(f"/api/v1/products/{frame.id}", headers=pm)
    assert response.status_code == expected
    if expected == 409:
        error = response.json()["error"]
        assert (error["code"], error["details"]) == (
            "PRODUCT_IN_USE",
            [{"order_numbers": ["PO-2026-00042"]}],
        )


# --- BR-PO-02: one writer of the status column -------------------------------------------


def test_br_po_02_only_the_production_service_writes_order_status() -> None:
    writes = re.compile(r"\border\w*\.status\s*=(?!=)")
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path.name != "production_service.py" and writes.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
