"""Balances, the ledger and reconciliation: D-25, D-23, BR-INV-04 (test 10 of B15)."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.master_data import Material


@pytest.fixture
def warehouse(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WAREHOUSE)
    return headers


@pytest.fixture
def admin(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.ADMIN)
    return headers


@pytest.fixture
def b6(material_factory) -> dict[str, Material]:
    """The three materials of the B6 reservation example, with minimum stock."""
    return {
        "STEEL-001": material_factory(
            "STEEL-001", unit="kg", decimal_places=3, minimum_stock=Decimal(50)
        ),
        "BOLT-M8": material_factory(
            "BOLT-M8", unit="pcs", decimal_places=0, minimum_stock=Decimal(200)
        ),
        "PAINT-RED": material_factory(
            "PAINT-RED", unit="kg", decimal_places=3, minimum_stock=Decimal(10)
        ),
    }


class Stock:
    """Drives receipts and adjustments through the API with fresh idempotency keys."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client, self.headers, self.n = client, headers, 0

    def _post(self, url: str, body: dict[str, Any]) -> Any:
        self.n += 1
        response = self.client.post(
            url, json=body, headers={**self.headers, "Idempotency-Key": f"stock-key-{self.n:04d}"}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def receive(self, material: Material, quantity: str) -> Any:
        return self._post(
            "/api/v1/inventory/receipts", {"material_id": material.id, "quantity": quantity}
        )

    def adjust(self, material: Material, delta: str) -> Any:
        return self._post(
            "/api/v1/inventory/adjustments",
            {"material_id": material.id, "quantity_delta": delta, "reason": "Cycle count"},
        )


def seed_reservation(session: Session, material: Material, reserved: str) -> None:
    """Reservations arrive with production orders (Phase 5): seed balance and ledger
    together so the ledger stays in step, as a RESERVE would."""
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(
            text(
                "UPDATE inventory SET reserved_quantity = reserved_quantity + :q "
                "WHERE material_id = :id"
            ),
            {"q": reserved, "id": material.id},
        )
        session.execute(
            text(
                "INSERT INTO inventory_transactions (type, material_id, warehouse_id, "
                "on_hand_delta, reserved_delta, on_hand_after, reserved_after) "
                "SELECT 'RESERVE', material_id, warehouse_id, 0, :q, on_hand_quantity, "
                "reserved_quantity FROM inventory WHERE material_id = :id"
            ),
            {"q": reserved, "id": material.id},
        )


# --- GET /inventory and D-25 -----------------------------------------------------------


def test_d25_low_stock_compares_available_not_on_hand(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    b6: dict[str, Material],
) -> None:
    stock = Stock(db_client, warehouse)
    stock.receive(b6["STEEL-001"], "250")
    stock.receive(b6["BOLT-M8"], "600")
    stock.receive(b6["PAINT-RED"], "30")
    seed_reservation(db_session, b6["BOLT-M8"], "450")  # on hand 600 >= 200, available 150 < 200

    page = db_client.get("/api/v1/inventory", headers=warehouse).json()
    assert page["total"] == 3
    rows = {item["material_code"]: item for item in page["items"]}
    assert [item["material_code"] for item in page["items"]] == [
        "BOLT-M8",
        "PAINT-RED",
        "STEEL-001",
    ]
    bolt = rows["BOLT-M8"]
    assert (bolt["on_hand_quantity"], bolt["reserved_quantity"], bolt["available_quantity"]) == (
        "600",
        "450",
        "150",
    )
    assert (bolt["low_stock"], bolt["below_minimum_by"]) == (True, "50")
    assert (rows["STEEL-001"]["low_stock"], rows["STEEL-001"]["below_minimum_by"]) == (
        False,
        "0.000",
    )

    low = db_client.get("/api/v1/inventory", params={"low_stock": "true"}, headers=warehouse)
    assert [item["material_code"] for item in low.json()["items"]] == ["BOLT-M8"]
    assert low.json()["total"] == 1


def test_d25_available_equal_to_minimum_is_not_low(
    db_client: TestClient, warehouse: dict[str, str], b6: dict[str, Material]
) -> None:
    Stock(db_client, warehouse).receive(b6["PAINT-RED"], "10")
    low = db_client.get("/api/v1/inventory", params={"low_stock": "true"}, headers=warehouse)
    assert "PAINT-RED" not in [item["material_code"] for item in low.json()["items"]]


# --- GET /inventory/transactions --------------------------------------------------------


def test_br_inv_03_ledger_is_listed_newest_first_and_filterable(
    db_client: TestClient, warehouse: dict[str, str], b6: dict[str, Material]
) -> None:
    stock = Stock(db_client, warehouse)
    stock.receive(b6["STEEL-001"], "250")
    stock.adjust(b6["STEEL-001"], "-0.5")
    stock.receive(b6["BOLT-M8"], "600")

    everything = db_client.get("/api/v1/inventory/transactions", headers=warehouse).json()
    assert [(i["type"], i["material_code"]) for i in everything["items"]] == [
        ("RECEIVE", "BOLT-M8"),
        ("ADJUSTMENT", "STEEL-001"),
        ("RECEIVE", "STEEL-001"),
    ]
    steel = db_client.get(
        "/api/v1/inventory/transactions",
        params={"material_id": b6["STEEL-001"].id, "type": "ADJUSTMENT"},
        headers=warehouse,
    ).json()
    [line] = steel["items"]
    assert (line["on_hand_delta"], line["on_hand_after"], line["reason"]) == (
        "-0.500",
        "249.500",
        "Cycle count",
    )


def test_d23_ledger_date_filters_use_utc_and_reject_naive_datetimes(
    db_client: TestClient,
    warehouse: dict[str, str],
    b6: dict[str, Material],
) -> None:
    Stock(db_client, warehouse).receive(b6["STEEL-001"], "1")
    past = "2000-01-01T00:00:00+00:00"
    future = "2999-01-01T00:00:00Z"
    url = "/api/v1/inventory/transactions"
    inside = db_client.get(
        url, params={"created_from": past, "created_to": future}, headers=warehouse
    )
    assert inside.json()["total"] == 1
    after = db_client.get(url, params={"created_from": future}, headers=warehouse)
    assert after.json()["total"] == 0

    naive = db_client.get(url, params={"created_from": "2026-01-01T00:00:00"}, headers=warehouse)
    assert naive.status_code == 422
    reversed_range = db_client.get(
        url, params={"created_from": future, "created_to": past}, headers=warehouse
    )
    assert reversed_range.json()["error"]["code"] == "INVALID_DATE_RANGE"


# --- BR-INV-04: reconciliation (test 10) ------------------------------------------------


def test_br_inv_04_reconciliation_is_consistent_after_a_mixed_scenario(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    admin: dict[str, str],
    b6: dict[str, Material],
    material_factory,
) -> None:
    material_factory("UNUSED-1")  # zero balance, no ledger lines: also consistent
    stock = Stock(db_client, warehouse)
    stock.receive(b6["STEEL-001"], "250")
    stock.receive(b6["BOLT-M8"], "600")
    stock.adjust(b6["BOLT-M8"], "-15")
    seed_reservation(db_session, b6["BOLT-M8"], "100")
    stock.adjust(b6["STEEL-001"], "0.125")
    stock.receive(b6["PAINT-RED"], "30")

    report = db_client.get("/api/v1/admin/inventory-reconciliation", headers=admin).json()
    assert report == {"consistent": True, "checked_materials": 4, "mismatches": []}


def test_br_inv_04_reconciliation_detects_a_balance_changed_behind_the_ledger(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    admin: dict[str, str],
    b6: dict[str, Material],
) -> None:
    Stock(db_client, warehouse).receive(b6["BOLT-M8"], "600")
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():  # an UPDATE that bypasses the service and the ledger
        db_session.execute(
            text("UPDATE inventory SET on_hand_quantity = 650 WHERE material_id = :id"),
            {"id": b6["BOLT-M8"].id},
        )

    report = db_client.get("/api/v1/admin/inventory-reconciliation", headers=admin).json()
    assert report["consistent"] is False
    assert report["mismatches"] == [
        {
            "material_id": b6["BOLT-M8"].id,
            "material_code": "BOLT-M8",
            "on_hand_quantity": "650.0000",
            "on_hand_ledger_sum": "600.0000",
            "reserved_quantity": "0.0000",
            "reserved_ledger_sum": "0.0000",
        }
    ]


def test_br_inv_04_reconciliation_detects_reserved_changed_behind_the_ledger(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    admin: dict[str, str],
    b6: dict[str, Material],
) -> None:
    Stock(db_client, warehouse).receive(b6["BOLT-M8"], "600")
    if db_session.in_transaction():
        db_session.commit()
    with db_session.begin():  # a reservation without its RESERVE ledger line
        db_session.execute(
            text("UPDATE inventory SET reserved_quantity = 80 WHERE material_id = :id"),
            {"id": b6["BOLT-M8"].id},
        )

    report = db_client.get("/api/v1/admin/inventory-reconciliation", headers=admin).json()
    assert report["consistent"] is False
    [mismatch] = report["mismatches"]
    assert (mismatch["material_code"], mismatch["on_hand_quantity"]) == ("BOLT-M8", "600.0000")
    assert (mismatch["reserved_quantity"], mismatch["reserved_ledger_sum"]) == ("80.0000", "0.0000")


def test_b4_only_admin_can_run_reconciliation(
    db_client: TestClient, warehouse: dict[str, str]
) -> None:
    response = db_client.get("/api/v1/admin/inventory-reconciliation", headers=warehouse)
    assert response.status_code == 403
