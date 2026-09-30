"""Adjustments: B6, D-20 and test 9 of B15 (never below what is reserved), C-15."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material

ADJUSTMENTS = "/api/v1/inventory/adjustments"


@pytest.fixture
def warehouse(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WAREHOUSE)
    return headers


@pytest.fixture
def bolt(material_factory) -> Material:
    material: Material = material_factory("BOLT-M8", unit="pcs", decimal_places=0)
    return material


def set_balance(session: Session, material: Material, on_hand: str, reserved: str) -> None:
    """Reservations only arrive with production orders (Phase 5); seed them directly."""
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(
            text(
                "UPDATE inventory SET on_hand_quantity = :on_hand, reserved_quantity = :reserved "
                "WHERE material_id = :id"
            ),
            {"on_hand": on_hand, "reserved": reserved, "id": material.id},
        )


def adjust(
    client: TestClient,
    headers: dict[str, str],
    material: Material,
    delta: Any,
    reason: str = "Cycle count correction",
    key: str = "adjust-key-0001",
) -> Any:
    return client.post(
        ADJUSTMENTS,
        json={"material_id": material.id, "quantity_delta": delta, "reason": reason},
        headers={**headers, "Idempotency-Key": key},
    )


def state(session: Session, material: Material) -> tuple[Decimal, Decimal, int]:
    row = session.scalars(
        select(Inventory)
        .where(Inventory.material_id == material.id)
        .execution_options(populate_existing=True)
    ).one()
    lines = session.scalars(
        select(InventoryTransaction).where(InventoryTransaction.material_id == material.id)
    ).all()
    return row.on_hand_quantity, row.reserved_quantity, len(lines)


def test_b6_adjustment_moves_on_hand_by_a_signed_delta(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    set_balance(db_session, bolt, "600", "100")
    response = adjust(db_client, warehouse, bolt, "-15", reason="Damaged in storage")
    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["on_hand_delta"], body["reason"]) == (
        "ADJUSTMENT",
        "-15",
        "Damaged in storage",
    )
    assert (body["on_hand_quantity"], body["reserved_quantity"], body["available_quantity"]) == (
        "585",
        "100",
        "485",
    )
    assert state(db_session, bolt) == (Decimal(585), Decimal(100), 1)


def test_br_inv_02_adjustment_below_reserved_is_409_and_nothing_changes(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    """Test 9 of B15: 100 on hand, 80 reserved; removing 30 would leave 70 < 80."""
    set_balance(db_session, bolt, "100", "80")
    response = adjust(db_client, warehouse, bolt, "-30")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "ADJUSTMENT_BELOW_RESERVED"
    assert error["details"] == [{"on_hand": "100", "reserved": "80", "quantity_delta": "-30"}]
    assert state(db_session, bolt) == (Decimal(100), Decimal(80), 0)


def test_d20_adjustment_down_to_exactly_the_reserved_quantity_is_allowed(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    set_balance(db_session, bolt, "100", "80")
    assert adjust(db_client, warehouse, bolt, "-20").json()["available_quantity"] == "0"
    assert state(db_session, bolt) == (Decimal(80), Decimal(80), 1)


def test_d20_adjustment_can_never_make_stock_negative(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    set_balance(db_session, bolt, "5", "0")
    response = adjust(db_client, warehouse, bolt, "-6")
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "ADJUSTMENT_BELOW_RESERVED",
    )
    assert state(db_session, bolt) == (Decimal(5), Decimal(0), 0)


@pytest.mark.parametrize(
    ("delta", "reason", "code"),
    [
        ("0", "Recount", "INVALID_QUANTITY"),
        ("1.5", "Recount", "INVALID_QUANTITY_SCALE"),
        ("-1.5", "Recount", "INVALID_QUANTITY_SCALE"),
        (-1, "Recount", "VALIDATION_ERROR"),
        ("+1", "Recount", "VALIDATION_ERROR"),
        ("5", "  ", "VALIDATION_ERROR"),
        ("5", "ok", "VALIDATION_ERROR"),
    ],
    ids=["zero", "scale", "negative-scale", "number", "plus-sign", "blank-reason", "short"],
)
def test_b6_invalid_adjustment_is_422(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    bolt: Material,
    delta: Any,
    reason: str,
    code: str,
) -> None:
    response = adjust(db_client, warehouse, bolt, delta, reason=reason)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    assert state(db_session, bolt)[2] == 0


def test_b6_missing_reason_is_422(
    db_client: TestClient, warehouse: dict[str, str], bolt: Material
) -> None:
    response = db_client.post(
        ADJUSTMENTS,
        json={"material_id": bolt.id, "quantity_delta": "5"},
        headers={**warehouse, "Idempotency-Key": "adjust-key-0002"},
    )
    assert response.status_code == 422


def test_c15_inactive_material_can_still_be_adjusted(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], material_factory
) -> None:
    retired = material_factory("OLD-PART", unit="pcs", decimal_places=0, active=False)
    set_balance(db_session, retired, "12", "0")
    response = adjust(db_client, warehouse, retired, "-12", reason="Written off, obsolete")
    assert response.status_code == 201
    assert state(db_session, retired) == (Decimal(0), Decimal(0), 1)


def test_d22_adjustment_requires_and_honours_the_idempotency_key(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    set_balance(db_session, bolt, "10", "0")
    missing = db_client.post(
        ADJUSTMENTS,
        json={"material_id": bolt.id, "quantity_delta": "5", "reason": "Recount"},
        headers=warehouse,
    )
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    first = adjust(db_client, warehouse, bolt, "5")
    second = adjust(db_client, warehouse, bolt, "5")
    assert second.json() == first.json()
    assert state(db_session, bolt) == (Decimal(15), Decimal(0), 1)


def test_br_aud_01_adjustment_is_audited_with_its_reason(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    set_balance(db_session, bolt, "600", "0")
    adjust(db_client, warehouse, bolt, "-4", reason="Found damaged")
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "INVENTORY_ADJUSTMENT"))
    assert row.reason == "Found damaged"
    assert (row.old_value, row.new_value) == (
        {"on_hand": "600"},
        {"material_code": "BOLT-M8", "quantity_delta": "-4", "unit": "pcs", "on_hand": "596"},
    )


def test_br_inv_04_ledger_matches_balance_after_receipts_and_adjustments(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], bolt: Material
) -> None:
    steps = [
        ("/api/v1/inventory/receipts", {"quantity": "500"}),
        (ADJUSTMENTS, {"quantity_delta": "-20", "reason": "Recount"}),
        ("/api/v1/inventory/receipts", {"quantity": "40"}),
        (ADJUSTMENTS, {"quantity_delta": "3", "reason": "Found in bin"}),
    ]
    for n, (url, body) in enumerate(steps):
        response = db_client.post(
            url,
            json={"material_id": bolt.id, **body},
            headers={**warehouse, "Idempotency-Key": f"mixed-key-{n:04d}"},
        )
        assert response.status_code == 201, response.text
    lines = db_session.scalars(
        select(InventoryTransaction).where(InventoryTransaction.material_id == bolt.id)
    ).all()
    on_hand, reserved, _ = state(db_session, bolt)
    assert sum(line.on_hand_delta for line in lines) == on_hand == Decimal(523)
    assert sum(line.reserved_delta for line in lines) == reserved == 0
