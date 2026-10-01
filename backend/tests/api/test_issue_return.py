"""ISSUE and RETURN against order lines: test 8 of B15, D-10, C-05, BR-INV-03/04."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.master_data import Inventory, Material, Product
from app.models.production import ProductionOrder, ProductionOrderMaterial


@pytest.fixture
def warehouse(login_as) -> dict[str, str]:
    headers: dict[str, str] = login_as(Role.WAREHOUSE)
    return headers


@pytest.fixture
def bolt(material_factory) -> Material:
    material: Material = material_factory("BOLT-M8", unit="pcs", decimal_places=0)
    return material


@pytest.fixture
def ready(product_factory, order_factory) -> ProductionOrder:
    order: ProductionOrder = order_factory(
        product_factory("FRAME-A"), status="READY_TO_PRODUCE", number="PO-2026-00001"
    )
    return order


@pytest.fixture
def line(order_line_factory, ready: ProductionOrder, bolt: Material) -> ProductionOrderMaterial:
    """840 bolts required and reserved; 1000 on hand."""
    created: ProductionOrderMaterial = order_line_factory(
        ready, bolt, required="840", reserved="840", on_hand="1000"
    )
    return created


class Mover:
    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client, self.headers, self.n = client, headers, 0

    def __call__(self, kind: str, line_id: int, quantity: Any) -> Any:
        self.n += 1
        return self.client.post(
            f"/api/v1/inventory/{kind}",
            json={"order_material_id": line_id, "quantity": quantity},
            headers={**self.headers, "Idempotency-Key": f"move-key-{self.n:04d}"},
        )


def state(session: Session, line: ProductionOrderMaterial) -> dict[str, Decimal]:
    session.expire_all()
    stored = session.get(ProductionOrderMaterial, line.id)
    balance = session.scalars(
        select(Inventory).where(Inventory.material_id == line.material_id)
    ).one()
    assert stored is not None
    return {
        "on_hand": balance.on_hand_quantity,
        "reserved": balance.reserved_quantity,
        "line_reserved": stored.reserved_quantity,
        "line_issued": stored.issued_quantity,
        "line_returned": stored.returned_quantity,
    }


def set_order_status(session: Session, order: ProductionOrder, status: str) -> None:
    if session.in_transaction():
        session.commit()
    with session.begin():
        session.execute(
            text("UPDATE production_orders SET status = :s WHERE id = :id"),
            {"s": status, "id": order.id},
        )


# --- ISSUE ---------------------------------------------------------------------------------


def test_d10_issue_moves_reserved_stock_to_issued(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    line: ProductionOrderMaterial,
) -> None:
    response = Mover(db_client, warehouse)("issues", line.id, "500")
    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["on_hand_delta"], body["reserved_delta"]) == (
        "ISSUE",
        "-500",
        "-500",
    )
    assert (body["order_number"], body["line_reserved_quantity"], body["line_issued_quantity"]) == (
        "PO-2026-00001",
        "340",
        "500",
    )
    assert state(db_session, line) == {
        "on_hand": Decimal(500),
        "reserved": Decimal(340),
        "line_reserved": Decimal(340),
        "line_issued": Decimal(500),
        "line_returned": Decimal(0),
    }
    [ledger] = db_session.scalars(
        select(InventoryTransaction).where(InventoryTransaction.type == "ISSUE")
    ).all()
    assert (ledger.production_order_id, ledger.order_material_id) == (
        line.production_order_id,
        line.id,
    )
    [audit] = db_session.scalars(select(AuditLog).where(AuditLog.action == "INVENTORY_ISSUE"))
    assert (audit.entity_type, audit.entity_id) == ("production_order_material", line.id)
    assert audit.new_value == {  # the B10 example
        "material_code": "BOLT-M8",
        "quantity": "500",
        "unit": "pcs",
        "order_number": "PO-2026-00001",
    }


@pytest.mark.parametrize("first", [None, "500"])
def test_d10_issue_beyond_what_is_still_reserved_is_409_and_nothing_moves(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    line: ProductionOrderMaterial,
    first: str | None,
) -> None:
    """Test 8 of B15: 840 reserved; after issuing 500 only 340 is still reserved."""
    move = Mover(db_client, warehouse)
    if first:
        move("issues", line.id, first)
    before = state(db_session, line)
    too_much = "841" if first is None else "341"
    response = move("issues", line.id, too_much)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "EXCEEDS_RESERVED"
    assert error["details"] == [
        {"quantity": too_much, "still_reserved": "840" if first is None else "340"}
    ]
    assert state(db_session, line) == before


def test_d10_line_can_be_issued_in_parts_up_to_exactly_the_requirement(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    line: ProductionOrderMaterial,
) -> None:
    move = Mover(db_client, warehouse)
    for quantity in ("400", "440"):
        assert move("issues", line.id, quantity).status_code == 201
    assert state(db_session, line)["line_issued"] == Decimal(840)
    assert move("issues", line.id, "1").json()["error"]["code"] == "EXCEEDS_RESERVED"


@pytest.mark.parametrize("status", ["DRAFT", "MATERIAL_SHORTAGE", "IN_PROGRESS", "CANCELLED"])
def test_c05_issue_only_while_the_order_is_ready(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    ready: ProductionOrder,
    line: ProductionOrderMaterial,
    status: str,
) -> None:
    set_order_status(db_session, ready, status)
    response = Mover(db_client, warehouse)("issues", line.id, "1")
    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["details"][0]["current_status"]) == (
        "INVALID_ORDER_STATUS",
        status,
    )


# --- RETURN --------------------------------------------------------------------------------


def test_c05_return_only_after_cancel_or_completion(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    ready: ProductionOrder,
    line: ProductionOrderMaterial,
) -> None:
    move = Mover(db_client, warehouse)
    move("issues", line.id, "840")
    refused = move("returns", line.id, "10")  # still READY: returning would undo "issued in full"
    assert refused.json()["error"]["code"] == "INVALID_ORDER_STATUS"

    for status in ("CANCELLED", "COMPLETED"):
        set_order_status(db_session, ready, status)
        response = move("returns", line.id, "10")
        assert response.status_code == 201
        assert response.json()["type"] == "RETURN"
    assert state(db_session, line) == {
        "on_hand": Decimal(180),  # 1000 - 840 + 2 x 10
        "reserved": Decimal(0),
        "line_reserved": Decimal(0),
        "line_issued": Decimal(840),
        "line_returned": Decimal(20),
    }


def test_b6_return_beyond_issued_minus_returned_is_409(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    ready: ProductionOrder,
    line: ProductionOrderMaterial,
) -> None:
    move = Mover(db_client, warehouse)
    move("issues", line.id, "100")
    set_order_status(db_session, ready, "CANCELLED")
    move("returns", line.id, "60")
    response = move("returns", line.id, "41")
    assert response.status_code == 409
    assert response.json()["error"]["details"] == [{"quantity": "41", "returnable": "40"}]


# --- Validation, idempotency, reconciliation -------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "code"),
    [("0", "INVALID_QUANTITY"), ("1.5", "INVALID_QUANTITY_SCALE"), (5, "VALIDATION_ERROR")],
)
def test_b6_invalid_issue_quantity_is_422(
    db_client: TestClient,
    warehouse: dict[str, str],
    line: ProductionOrderMaterial,
    quantity: Any,
    code: str,
) -> None:
    response = Mover(db_client, warehouse)("issues", line.id, quantity)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


def test_unknown_order_line_is_422(db_client: TestClient, warehouse: dict[str, str]) -> None:
    response = Mover(db_client, warehouse)("issues", 999999, "1")
    assert response.json()["error"]["code"] == "ORDER_MATERIAL_NOT_FOUND"


def test_d22_issue_requires_a_key_and_a_retry_issues_once(
    db_client: TestClient,
    db_session: Session,
    warehouse: dict[str, str],
    line: ProductionOrderMaterial,
) -> None:
    body = {"order_material_id": line.id, "quantity": "100"}
    missing = db_client.post("/api/v1/inventory/issues", json=body, headers=warehouse)
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    headers = {**warehouse, "Idempotency-Key": "issue-key-0001"}
    first = db_client.post("/api/v1/inventory/issues", json=body, headers=headers)
    second = db_client.post("/api/v1/inventory/issues", json=body, headers=headers)
    assert second.json() == first.json()
    assert state(db_session, line)["line_issued"] == Decimal(100)


def test_br_inv_04_reconciliation_after_plan_issue_cancel_return(
    db_client: TestClient,
    db_session: Session,
    login_as,
    product_factory,
    material_factory,
    work_center_factory,
    bom_factory,
    routing_factory,
    order_factory,
) -> None:
    """Receipt, plan, issue, cancel, return: all through the API, so the ledger must
    explain every balance."""
    warehouse, pm, admin = login_as(Role.WAREHOUSE), login_as(Role.PRODUCTION_MANAGER), login_as()
    product: Product = product_factory("FRAME-B")
    steel = material_factory("STEEL-002", unit="kg", decimal_places=3)
    bom_factory(product, [(steel, "2", "0")], status="ACTIVE")
    routing_factory(product, [(10, "QC", work_center_factory())], status="ACTIVE")
    db_client.post(
        "/api/v1/inventory/receipts",
        json={"material_id": steel.id, "quantity": "100"},
        headers={**warehouse, "Idempotency-Key": "recon-receipt-1"},
    )
    order = order_factory(product, planned_quantity=10)
    planned = db_client.post(
        f"/api/v1/production-orders/{order.id}/plan",
        headers={**pm, "Idempotency-Key": "recon-plan-1"},
    ).json()
    assert planned["status"] == "READY_TO_PRODUCE"
    [line] = db_session.scalars(
        select(ProductionOrderMaterial).where(
            ProductionOrderMaterial.production_order_id == order.id
        )
    ).all()
    move = Mover(db_client, warehouse)
    assert move("issues", line.id, "12.5").status_code == 201
    cancelled = db_client.post(
        f"/api/v1/production-orders/{order.id}/cancel",
        json={"reason": "Customer cancelled"},
        headers={**pm, "Idempotency-Key": "recon-cancel-1"},
    )
    assert cancelled.json()["status"] == "CANCELLED"  # releases the 7.5 kg still reserved
    assert move("returns", line.id, "12.5").status_code == 201

    report = db_client.get("/api/v1/admin/inventory-reconciliation", headers=admin).json()
    assert report["consistent"] is True
    assert state(db_session, line)["on_hand"] == Decimal(100)
