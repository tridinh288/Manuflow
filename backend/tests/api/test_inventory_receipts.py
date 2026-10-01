"""Receipts: B6, BR-INV-01..04, D-22 (test 12 sequential part), C-15."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material

RECEIPTS = "/api/v1/inventory/receipts"


@pytest.fixture
def warehouse(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WAREHOUSE)
    return headers


@pytest.fixture
def steel(material_factory) -> Material:
    material: Material = material_factory("STEEL-001", unit="kg", decimal_places=3)
    return material


def post(
    client: TestClient,
    headers: dict[str, str],
    body: dict[str, Any],
    key: str = "receipt-key-0001",
) -> Any:
    return client.post(RECEIPTS, json=body, headers={**headers, "Idempotency-Key": key})


def ledger(session: Session, material: Material) -> list[InventoryTransaction]:
    return list(
        session.scalars(
            select(InventoryTransaction)
            .where(InventoryTransaction.material_id == material.id)
            .order_by(InventoryTransaction.id)
        )
    )


def balance(session: Session, material: Material) -> Inventory:
    row: Inventory = session.scalars(
        select(Inventory)
        .where(Inventory.material_id == material.id)
        .execution_options(populate_existing=True)
    ).one()
    return row


def test_br_inv_03_receipt_adds_stock_and_writes_one_ledger_line(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], steel: Material
) -> None:
    response = post(
        db_client,
        warehouse,
        {"material_id": steel.id, "quantity": "250", "reference": "GRN-2026-001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["material_code"], body["unit"]) == ("RECEIVE", "STEEL-001", "kg")
    assert (body["on_hand_delta"], body["reserved_delta"]) == ("250.000", "0.000")
    assert (body["on_hand_quantity"], body["available_quantity"]) == ("250.000", "250.000")

    [line] = ledger(db_session, steel)
    assert (line.type, line.on_hand_delta, line.reserved_delta) == (
        "RECEIVE",
        Decimal("250"),
        Decimal("0"),
    )
    assert (line.on_hand_after, line.reserved_after) == (Decimal("250"), Decimal("0"))
    assert line.reference == "GRN-2026-001"
    assert line.created_by is not None and line.request_id is not None
    assert balance(db_session, steel).on_hand_quantity == Decimal("250")


def test_br_inv_04_ledger_sums_match_the_balance_after_several_receipts(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], steel: Material
) -> None:
    for n, quantity in enumerate(["100", "0.5", "49.125"]):
        body = {"material_id": steel.id, "quantity": quantity}
        assert post(db_client, warehouse, body, key=f"receipt-key-{n:04d}").status_code == 201
    lines = ledger(db_session, steel)
    row = balance(db_session, steel)
    assert sum(line.on_hand_delta for line in lines) == row.on_hand_quantity == Decimal("149.625")
    assert sum(line.reserved_delta for line in lines) == row.reserved_quantity == 0
    assert [line.on_hand_after for line in lines] == [
        Decimal("100"),
        Decimal("100.5"),
        Decimal("149.625"),
    ]


def test_d22_same_key_replays_and_stock_moves_once(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], steel: Material
) -> None:
    body = {"material_id": steel.id, "quantity": "40"}
    first, second = post(db_client, warehouse, body), post(db_client, warehouse, body)
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len(ledger(db_session, steel)) == 1
    assert balance(db_session, steel).on_hand_quantity == Decimal("40")


def test_d22_receipt_without_idempotency_key_is_422(
    db_client: TestClient, warehouse: dict[str, str], steel: Material
) -> None:
    response = db_client.post(
        RECEIPTS, json={"material_id": steel.id, "quantity": "1"}, headers=warehouse
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "IDEMPOTENCY_KEY_REQUIRED",
    )


@pytest.mark.parametrize(
    ("quantity", "code"),
    [
        ("0", "INVALID_QUANTITY"),
        ("1.2345", "INVALID_QUANTITY_SCALE"),
        ("-5", "VALIDATION_ERROR"),
        (5, "VALIDATION_ERROR"),
    ],
    ids=["zero", "scale", "negative", "number"],
)
def test_b6_invalid_quantity_is_422_and_nothing_moves(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    steel: Material,
    quantity: Any,
    code: str,
) -> None:
    response = post(db_client, warehouse, {"material_id": steel.id, "quantity": quantity})
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    assert ledger(db_session, steel) == []
    assert balance(db_session, steel).on_hand_quantity == 0


def test_c15_inactive_material_cannot_be_received(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], material_factory
) -> None:
    retired = material_factory("OLD-PART", active=False)
    response = post(db_client, warehouse, {"material_id": retired.id, "quantity": "1"})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "MATERIAL_INACTIVE")
    assert ledger(db_session, retired) == []


def test_unknown_material_is_422(db_client: TestClient, warehouse: dict[str, str]) -> None:
    response = post(db_client, warehouse, {"material_id": 999999, "quantity": "1"})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "MATERIAL_NOT_FOUND")


def test_br_aud_01_receipt_is_audited_in_the_same_transaction(
    db_client: TestClient, db_session: Session, warehouse: dict[str, str], steel: Material
) -> None:
    transaction_id = post(
        db_client, warehouse, {"material_id": steel.id, "quantity": "204", "reference": "GRN-9"}
    ).json()["transaction_id"]
    [row] = db_session.scalars(select(AuditLog).where(AuditLog.action == "INVENTORY_RECEIVE"))
    assert (row.entity_type, row.entity_id) == ("inventory_transaction", transaction_id)
    assert row.new_value == {
        "material_code": "STEEL-001",
        "quantity": "204.000",
        "unit": "kg",
        "reference": "GRN-9",
        "on_hand_after": "204.000",
    }


def test_b4_admin_cannot_receive_stock(
    db_client: TestClient, db_session: Session, login_as, steel: Material
) -> None:
    response = post(db_client, login_as(Role.ADMIN), {"material_id": steel.id, "quantity": "1"})
    assert response.status_code == 403
    count = db_session.scalar(select(func.count()).select_from(InventoryTransaction))
    assert count == 0
